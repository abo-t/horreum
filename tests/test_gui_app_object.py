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

from horreum import db, repo, resolver
from horreum.gui import i18n, queries
from horreum.gui.app import (
    AssignObjectDialog, ConfirmPathObjectsDialog, ObjectAxisView, COPY_COL_PATH, COPY_COL_REASON,
    OBJ_COL_CANON, OBJ_COL_FRAMES)

from fixture_s8 import seed_object_axis

from PySide6.QtWidgets import QApplication, QDialog, QHeaderView

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


def test_combo_teleskopow_mowi_canonem_gdy_nienazwany(view):
    """Etykieta comba idzie od JEDNEGO właściciela (`queries.telescope_label`, P-B) — teleskopy
    fixture są `proposed` (label=NULL), więc lista mówi nagłówkiem, nie pustkami; po nazwaniu
    przechodzi na nazwę usera. Bez tej asercji tekst pozycji był niepilnowany (testy trzymały
    tylko `count`/`itemData`), a to on jest widoczny."""
    v, con, ids = view
    assert [v.combo_tel.itemText(i) for i in range(1, v.combo_tel.count())] == \
        ["A140R", "A140R-bis", "RC8", "76EDPH"]         # ORDER BY id, canon zamiast pustki
    repo.label_telescope(con, telescope_id=ids["A"], label="Askar 140", now="2026-06-29T14:00:00")
    v._load_facets()
    assert v.combo_tel.itemText(1) == "Askar 140"       # nazwa usera bije canon


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
    # fixture §8 nie ma oznaczonych kopii → 0. KUBEŁEK PUSTY NIE MA DOKĄD PROWADZIĆ (wiz T2 N6):
    # drążenie w zero otwierało tabelę bez ani jednego wiersza i bez zdania, a wyszarzony wiersz
    # zaznaczalny spadał na podświetleniu do 1,84:1 kontrastu (T2 N3). Jedna reguła dla wszystkich
    # kubełków — `nameless` zachowywał się tak od początku. Klikalny wraca przy n>0 (#13/Z6).
    assert any(t.startswith("— kopie nieczytelne: 0") and tag is None for t, tag in items)
    # nota „rozwiązywanie w przygotowaniu" zawężona do dwóch kanałów bez akcji (R#9)
    assert any("config-review: 4" in t and "bez nagłówka: 1" in t
               and "rozwiązywanie w przygotowaniu" in t and tag is None for t, tag in items)


def test_kolejka_pokazuje_ktora_pozycja_prowadzi_dalej(view):
    """WIZ #11: pięć wierszy kolejki miało identyczny krój i kolor, a klikalne były dwa — nic na
    ekranie nie mówiło, który prowadzi dalej („do przypisania ręcznie" wzywało do akcji i nie
    prowadziło nigdzie). Znacznik „›" niesie WYŁĄCZNIE wiersz z drogą; jest pochodną tagu, więc
    nie może się z dispatchem rozjechać."""
    v, con, ids = view
    for r in range(v.review.count()):
        it = v.review.item(r)
        assert it.text().endswith("›") == (it.data(UROLE) is not None)


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
    v.review.clearSelection()                  # brak pozycji ⇒ przycisk gaśnie. Fixture nie ma już
    v._sync_assign_enabled()                    # innego KLIKALNEGO kubełka: pusty `unreadable` jest
    assert not v.assign_btn.isEnabled()         # od T2 N6 informacyjny, więc nie da się go zaznaczyć
    _select_review_tag(v, "object_raw")
    v.set_busy(True)                                         # pipeline w biegu → wygaszony
    assert not v.assign_btn.isEnabled()
    v.set_busy(False)
    assert v.assign_btn.isEnabled()


def test_dialog_wymaga_jawnego_wyboru_istniejacego(view):
    """Dialog (#8): placeholder nie jest realnym celem; akcja rusza dopiero po jawnym wyborze.

    PRZESTEMPLOWANY w S4: `alias_norm` zniknął z konstruktora (klucz liczy dialog, bo dopiero on
    zna wybraną nazwę), a `selected` niesie CZWARTY człon — ten właśnie klucz."""
    v, con, ids = view
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", frame_count=2, parent=v)
    assert dlg.combo.currentData() is None
    assert not dlg.accept_btn.isEnabled()
    assert dlg.accept_btn.text() == "Przypisz 2 klatki"
    dlg._validate_and_accept()
    assert dlg.selected is None
    assert "Wybierz istniejący obiekt" in dlg.error.text()
    dlg.combo.setCurrentIndex(1)                            # M42 (ORDER canon)
    assert dlg.accept_btn.isEnabled()
    dlg._validate_and_accept()
    assert dlg.selected == ("M42", "Messier", None, "FLATWIZARD")
    dlg.close()


def test_dialog_nowa_nazwa_nadpisuje_combo(view):
    """Nazwa wpisana ręcznie nadpisuje wybór z listy i rozwiązuje się jak w resolverze
    („IC 1795" → canon IC1795, catalog IC, kind deep_sky).

    PRZESTEMPLOWANY w S4: kanon i pola obiektu biorą się z `resolver.resolve_name` (dawniej
    `catalog_canon`→`xref` + zaszyte `deep_sky`), a klucz aliasu zostaje z ZEZNANIA — grupa ma
    `object_raw`, więc alias ma zapamiętać „FlatWizard", nie kanon."""
    v, con, ids = view
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", frame_count=2, parent=v)
    dlg.designation.setText("IC 1795")
    assert dlg.accept_btn.isEnabled()
    dlg._validate_and_accept()
    assert dlg.selected == ("IC1795", "IC", "deep_sky", "FLATWIZARD")
    dlg.close()


def test_dialog_nazwa_nierozwiazywalna_odrzuca(view):
    """Nazwa, której NIE ROZWIĄŻE przebieg → czerwona nota, `selected` zostaje None (dialog by
    został otwarty — bez `accept()`).

    PRZESTEMPLOWANY w S4: bramką jest cała drabina (`resolver.name_resolves`), nie sama gramatyka
    katalogowa — komunikat mówi o NAZWIE, bo o nazwę było pytanie."""
    v, con, ids = view
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", frame_count=2, parent=v)
    dlg.designation.setText("???")
    assert not dlg.accept_btn.isEnabled()
    assert "Nie rozpoznaję nazwy" in dlg.error.text()        # live feedback, disabled ma widoczny powód
    dlg._validate_and_accept()
    assert dlg.selected is None
    assert "Nie rozpoznaję nazwy" in dlg.error.text()
    dlg.close()


def test_dialog_konflikt_aliasu_odrzuca_pre_check(view):
    """Pre-check UX (R#8/TOCTOU): alias nazwy wskazuje INNY obiekt niż wybrany → nota konfliktu,
    `selected` None; wybór właściwego obiektu przechodzi. Ostateczny guard = `repo` (osobne testy).

    PRZESTEMPLOWANY w S4: pre-check liczy się PO walidacji nazwy, na TYM SAMYM kluczu, którego
    użyje zapis — dawniej klucz przychodził parametrem konstruktora, więc dwa przypadki z trzech
    nie miały go z czego wziąć."""
    v, con, ids = view
    repo.add_object_alias(con, alias_norm="FLATWIZARD", object_id=ids["objects"]["NGC7000"],
                          source="user", now="2026-07-21T12:00:00")
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", frame_count=2, parent=v)
    dlg.combo.setCurrentIndex(1)                            # jawny wybór M42 ≠ NGC7000 → konflikt
    dlg._validate_and_accept()
    assert dlg.selected is None
    assert "wskazuje już" in dlg.error.text()
    for i in range(dlg.combo.count()):
        data = dlg.combo.itemData(i)
        if data is not None and data[0] == ids["objects"]["NGC7000"]:
            dlg.combo.setCurrentIndex(i)
            break
    assert dlg.error.text() == ""                            # zmieniony cel kasuje nieaktualny konflikt
    dlg._validate_and_accept()
    assert dlg.selected == ("NGC7000", "NGC", None, "FLATWIZARD")
    dlg.close()


def test_pre_check_nie_widzi_konfliktu_tam_gdzie_zapis_przechodzi(view):
    """Adjudykacja recenzji diffu S4 (P2 #3): id obiektu do pre-checku bierze się TĄ SAMĄ frazą,
    której użyje klinga (`SELECT id FROM object WHERE canon = ?`), a nie z biblioteki.

    Falsyfikator jest konkretny: obiekt BEZ klatek nie istnieje dla `library_objects` (`JOIN frame`),
    więc dawna gałąź liczyła `object_id=None` i meldowała konflikt aliasu wskazującego DOKŁADNIE
    ten obiekt — komunikat kłamiący o przyczynie, przy poprawnym kluczu i przechodzącym zapisie."""
    v, con, ids = view
    con.execute("INSERT INTO object(canon, catalog, kind) VALUES ('IC1795','IC','deep_sky')")
    con.commit()
    pusty = con.execute("SELECT id FROM object WHERE canon='IC1795'").fetchone()[0]
    repo.add_object_alias(con, alias_norm="FLATWIZARD", object_id=pusty,
                          source="user", now="2026-07-21T12:00:00")
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", frame_count=2, parent=v)
    dlg.designation.setText("IC 1795")
    dlg._validate_and_accept()
    assert dlg.error.text() == "", "alias wskazuje TEN sam obiekt — to nie jest konflikt"
    assert dlg.selected == ("IC1795", "IC", "deep_sky", "FLATWIZARD")
    dlg.close()


def test_uszkodzony_slownik_melduje_sie_zamiast_wywalac_okno(view, monkeypatch):
    """Adjudykacja recenzji diffu S4 (P2 #5): `objects_own.json` jest plikiem CZŁOWIEKA i jego edycja
    to operacja wspierana — literówka ma zostać ZGŁOSZONA, nie wywalić okno tracebackiem przy
    naciśnięciu klawisza. Ta sama reguła, którą kolejka przeglądu ma od S2."""
    v, con, ids = view

    def wybuch(*_a, **_k):
        raise ValueError("objects_own.json: rekord bez kanonu `c`")

    dlg = AssignObjectDialog(con, object_raw="FlatWizard", frame_count=2, parent=v)
    # Uszkodzony asset wywala OBIE drogi drabiny (obie idą przez `_own_index`), więc symulacja
    # patchująca jedną z nich sprawdzałaby połowę okna i przepuściła zapis przez drugą połowę.
    monkeypatch.setattr(resolver, "name_resolves", wybuch)
    monkeypatch.setattr(resolver, "resolve_name", wybuch)
    dlg.designation.setText("IC 1795")
    assert not dlg.accept_btn.isEnabled()
    assert "objects_own.json" in dlg.error.text()
    dlg._validate_and_accept()
    assert dlg.selected is None                       # zero zapisu, dialog zostaje otwarty
    dlg.close()


def test_on_assign_po_sukcesie_zaznacza_cel(view, monkeypatch):
    """Po zapisie grupa znika, a widok pokazuje obiekt docelowy zamiast pierwszego alfabetycznie."""
    v, con, ids = view

    class AcceptedM42:
        selected = ("M42", "Messier", None, "FLATWIZARD")

        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr("horreum.gui.app.AssignObjectDialog", AcceptedM42)
    for i in range(v.combo_filter.count()):
        if v.combo_filter.itemData(i) == "Ha":
            v.combo_filter.setCurrentIndex(i)
            break
    assert "M42" not in _obj_rows(v)                         # cel ukryty przez filtr, kolejka globalna
    _select_review_tag(v, "object_raw")
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_assign()

    assert v.combo_tel.currentData() is None and v.combo_filter.currentData() is None
    assert v._selected_object_id() == ids["objects"]["M42"]
    assert v.frames.rowCount() == 5                           # 3 istniejące + 2 przypisane
    assert msgs[-1] == "Przypisano 2 z 2 klatek → M42."
    assert not any("FlatWizard" in v.review.item(r).text() for r in range(v.review.count()))


def test_on_assign_zero_assigned_nie_udaje_wyboru_celu(view, monkeypatch):
    """Gdy cała grupa zdryfowała, komunikat jest szczery, ale widok nie udaje sukcesu wyborem celu."""
    v, con, ids = view

    class AcceptedM42:
        selected = ("M42", "Messier", None, "FLATWIZARD")

        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr("horreum.gui.app.AssignObjectDialog", AcceptedM42)
    monkeypatch.setattr(repo, "user_assign_object",
                        lambda *a, **k: repo.ObjectGesture(assigned=0, skipped_drift=2))
    _select_review_tag(v, "object_raw")
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_assign()

    assert v._selected_object_id() is None
    assert not v.objects.selectedItems() and v.frames.rowCount() == 0
    assert msgs[-1].startswith("Przypisano 0 z 2 klatek → M42.")


def test_przypisanie_zmniejsza_kolejke_i_zapisuje_user(view):
    """DoD #8: po przypisaniu grupy (ścieżka repo z `_on_assign`) pozycja review ZNIKA z kolejki,
    klatki widnieją pod obiektem docelowym z `object_source='user'`; biblioteka liczy nowe klatki.
    (Dialog `exec()` jest modalny — ścieżkę widget↔dialog pokrywają testy dialogu powyżej.)"""
    v, con, ids = view
    rows = queries.object_review_frames(con, "FlatWizard")
    assert len(rows) == 2
    g = repo.user_assign_object(
        con, alias_norm="FLATWIZARD", canon="M42", catalog="Messier", kind=None,
        frame_ids=[r["frame_id"] for r in rows], now="2026-07-21T12:00:00")
    assert (g.assigned, g.skipped) == (2, 0)
    v.refresh()
    texts = [v.review.item(r).text() for r in range(v.review.count())]
    assert not any("FlatWizard" in t for t in texts)         # nigdy nie wraca do kolejki
    assert _obj_rows(v) == {"M42": 5, "NGC7000": 5}          # M42: 3+2
    for f in ("objrev1", "objrev2"):
        r = con.execute("SELECT object_id, object_source FROM frame WHERE id=?",
                        (ids["frames"][f],)).fetchone()
        assert (r["object_id"], r["object_source"]) == (ids["objects"]["M42"], "user")


# --- drążenie „kopie nieczytelne" (Z6/P4) ---

def test_kopie_nieczytelne_drazenie_do_dokladnych_kopii(view, qapp):
    """Z6: klik pozycji „kopie nieczytelne" → prawy panel w trybie „kopie" (COPY_HEADERS, dokładne
    location z markerem); wybór obiektu przywraca tabelę klatek (tryb kopii znika, D-P4-5)."""
    v, con, ids = view
    loc = con.execute("SELECT id FROM location WHERE volume = 'vol2'").fetchone()
    long_path = "/backup/" + "/".join(["bardzo-dlugi-segment"] * 20) + "/a1.fits"
    with con:
        con.execute("UPDATE location SET path = ? WHERE id = ?", (long_path, loc["id"]))
    repo.refresh_location_unreadable(con, location_id=loc["id"], sha1_data="sha-a1",
                                     path=long_path, mtime="t2", reason="OSError",
                                     now="2026-07-21T12:00:00")
    v.refresh()
    r = _select_review_tag(v, "unreadable")
    assert "kopie nieczytelne: 1" in v.review.item(r).text()
    hdrs = [v.frames.horizontalHeaderItem(c).text() for c in range(v.frames.columnCount())]
    assert hdrs == ["Ścieżka", "Wolumen", "Obecna", "Oznaczona", "Powód"]  # PL (stałe = klucze)
    assert v.frames.rowCount() == 1
    assert v.frames.item(0, 0).text() == long_path           # dokładna location w komórce
    assert v.frames.item(0, 0).toolTip() == long_path
    # Ścieżka bierze resztę i elidować się jej wolno; „Powód" MUSI zmieścić się w panelu (firsthand
    # 2026-08-01 na żywej pf4: przy `ResizeToContents` 100-znakowa ścieżka wypychała diagnozę poza
    # prawą krawędź — kolumna, dla której powstał cały Z6, była nie do przeczytania bez scrolla).
    hh = v.frames.horizontalHeader()
    assert hh.sectionResizeMode(COPY_COL_PATH) == QHeaderView.Stretch
    assert hh.sectionResizeMode(COPY_COL_REASON) == QHeaderView.ResizeToContents
    # Zawijanie WYŁĄCZONE — inaczej elizja ścieżki (jedno słowo, zero spacji) tnie ją do „R:..."
    # niezależnie od szerokości sekcji i kolumna jest równie nieczytelna, co przed zmianą.
    assert not v.frames.wordWrap()
    v.resize(1073, 720)                       # podłoga sprzed D-0801-1, zmierzona realnym fontem
    #                                           („1146" z sondy offscreen było zawyżone) — węższe
    #                                           okno jest tu OSTRZEJSZYM testem niż dzisiejsze 1310
    qapp.processEvents()
    assert (hh.sectionPosition(COPY_COL_REASON) + hh.sectionSize(COPY_COL_REASON)
            <= v.frames.viewport().width())
    assert v.frames.item(0, 1).text() == "vol2"
    assert v.frames.item(0, 2).text() == "tak"               # kopia nadal obecna
    # Powód z dziennika (Z6): komórka bez prefiksu, tooltip = zapis dosłowny
    assert v.frames.item(0, 4).text() == "OSError"
    assert v.frames.item(0, 4).toolTip() == "kopia nieczytelna: OSError"
    assert v.frames_label.text() == "Kopie nieczytelne (1)"
    # kopia bez pokrycia w dzienniku (przemianowana po awarii) → „—", nie pustka: „nie wiem,
    # dlaczego" jest faktem, a pusta komórka czyta się jak brak danych w kolumnie
    with con:
        con.execute("UPDATE location SET path = ? WHERE id = ?", ("/backup/a1-NOWA.fits", loc["id"]))
    v.refresh()
    _select_review_tag(v, "unreadable")
    assert v.frames.item(0, 4).text() == "—"
    assert not v.frames.item(0, 4).toolTip()
    # wybór obiektu → powrót do tabeli klatek (tryb „kopie" znika)
    _select_object_canon(v, "NGC7000")
    hdrs = [v.frames.horizontalHeaderItem(c).text() for c in range(v.frames.columnCount())]
    assert hdrs == ["sha1 danych", "Teleskop", "Kamera", "Filtr", "Data", "Obecny", "Ścieżka"]
    assert v.frames.rowCount() == 5


# --- i18n: EN renderuje z katalogu (§4 rollout `app`) ---

def test_en_render_z_katalogu(qapp, tmp_path):
    """§5: `set_lang('en')` PRZED budową widoku → nagłówki i etykiety renderują EN z katalogu —
    dowód, że stałe trzymają KLUCZE rozwiązywane w czasie budowy, nie zamrożony PL. Autouse-fixture
    `_reset_i18n_lang` wraca na PL po teście (bez skażenia baterii)."""
    i18n.set_lang("en")
    con = db.open_db(str(tmp_path / "en.db"))
    seed_object_axis(con)
    v = ObjectAxisView(con)
    try:
        hdrs = [v.objects.horizontalHeaderItem(c).text() for c in range(v.objects.columnCount())]
        assert hdrs == ["Object", "Catalog", "Frames"]
        assert v.assign_btn.text() == "Assign object…"
        assert v.lib_empty.text() == "No objects for this filter — change the filter or resolve."
    finally:
        v.close()
        con.close()


# ============================================================ P-D: „Napraw nagłówek…" (wariant C)
# Nazwa wraca do PLIKU (karta OBJECT), oś obiektu wypełnia potem zwykły `Rozwiąż`. Testy jadą na
# REALNYCH plikach FITS — writeback rusza bajty, więc atrapa nie dowodzi niczego. Worker inline
# (`_runner.async_ok = False`, seam jak w gridzie): ten sam rdzeń, sygnały direct = synchronicznie.

NOW_PD = "2026-08-01T00:00:00Z"


def _nameless_tree(root, names=("NGC7635_20230103_a.fits", "NGC7635_20230103_b.fits"), seed=0):
    """Drzewo `…/LIGHTS/NGC7635/RC8_2600MC/L-eXtreme/NGC7635_*.fits` — lighty BEZ karty OBJECT.
    Kotwicą propozycji jest segment PO `LIGHTS`, więc struktura katalogu jest częścią testu."""
    import numpy as np
    from astropy.io import fits
    d = root / "LIGHTS" / "NGC7635" / "RC8_2600MC" / "L-eXtreme"
    d.mkdir(parents=True, exist_ok=True)
    made = []
    for i, name in enumerate(names):
        p = d / name
        hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16) + seed + i)  # różne DANE = różne klatki
        hdu.header["TELESCOP"] = "RC8"
        hdu.header["IMAGETYP"] = "Light"
        hdu.writeto(str(p), overwrite=True)
        made.append(p)
    return made


@pytest.fixture
def repair(qapp, tmp_path):
    """ObjectAxisView + fabryka dialogu naprawy nad bazą z DWOMA realnymi lightami bez OBJECT."""
    from horreum import scan
    from horreum.gui.app import RepairHeaderDialog
    files = _nameless_tree(tmp_path)
    con = db.open_db(str(tmp_path / "pd.db"))
    for p in files:
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW_PD,
                           summary=scan.ScanSummary())
    v = ObjectAxisView(con, now_fn=lambda: NOW_PD)

    def _open(run_stage_fn=None):
        dlg = RepairHeaderDialog(con, rows=queries.nameless_frames(con),
                                 db_path=queries.db_path_of(con), now_fn=lambda: NOW_PD,
                                 run_stage_fn=run_stage_fn, parent=v)
        dlg._runner.async_ok = False        # inline: commit/undo synchronicznie, bez QThread
        return dlg

    yield v, con, files, _open
    v.close()
    con.close()


def test_kubelek_bezimiennych_drazy_i_aktywuje_akcje(repair):
    """Kubełek przestał być samym licznikiem: ma tag, drąży do klatek i włącza „Napraw nagłówek…".
    Obie akcje kolejki nigdy nie są aktywne naraz — śledzą różne tagi."""
    v, con, files, _open = repair
    assert queries.review_queue(con)["nameless_count"] == 2
    _select_review_tag(v, "nameless")
    assert v.frames.rowCount() == 2
    assert v.repair_btn.isEnabled() and not v.assign_btn.isEnabled()
    v.set_busy(True)                                  # etap w biegu → szczery disabled
    assert not v.repair_btn.isEnabled()
    v.set_busy(False)
    v.set_writeback_busy(True)                        # druga powierzchnia pisze (mutex D-PD-3)
    assert not v.repair_btn.isEnabled()
    v.set_writeback_busy(False)
    assert v.repair_btn.isEnabled()


def test_kubelek_gotowych_stosow_drazy_wlasna_lista(repair):
    """D-0802-1: wiersz „bez nazwy, gotowe stosy" przestał być informacyjny — ma tag, włącza
    „Napraw nagłówek…" i drąży do SWOJEJ listy, nie do lightowej.

    To jest falsyfikator pomyłki, która by nie bolała od razu: gdyby akcja brała zawsze
    `nameless_frames`, przycisk działałby, okno by się otwierało i naprawiałoby CUDZĄ populację —
    user kliknąłby licznik stosów, a poprawił lighty archiwum."""
    v, con, files, _open = repair
    fid, _ = repo.upsert_frame(con, sha1_data="sha-gui-stack", kind="master_light",
                               filetype="xisf", camera_id=None, now=NOW_PD)
    repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=None, now=NOW_PD)
    v.refresh()

    assert queries.review_queue(con)["nameless_stacks_count"] == 1
    _select_review_tag(v, "nameless_stacks")
    assert v.frames.rowCount() == 1                    # SWOJA lista, nie dwa lighty fixture'u
    assert v.repair_btn.isEnabled() and not v.assign_btn.isEnabled()
    assert [r["frame_id"] for r in queries.nameless_stack_frames(con)] == [fid]

    _select_review_tag(v, "nameless")                  # ten sam przycisk, druga populacja
    assert v.frames.rowCount() == 2 and v.repair_btn.isEnabled()


def test_propozycja_z_dwoch_swiadkow_i_domyslne_zaznaczenie(repair):
    """D-PD-2: folder po `LIGHTS` i nazwa pliku mówią to samo → pole wypełnione, grupa ZAZNACZONA
    (bez tego obietnica „≤ 4 interakcje" jest nieprawdziwa). Podgląd pokazuje DOKŁADNIE to, co
    pójdzie do pliku — z `repr`."""
    v, con, files, _open = repair
    dlg = _open()
    assert len(dlg._groups) == 1                      # jeden folder = jedna grupa, dwie klatki
    g = dlg._groups[0]
    assert g["edit"].text() == "NGC7635" and g["check"].isChecked()
    assert g["preview"].text() == "do pliku: OBJECT = 'NGC7635'"
    assert dlg.save_btn.isEnabled() and "2" in dlg.save_btn.text()
    dlg.reject()


def test_rozjazd_swiadkow_zostawia_pole_puste(repair, tmp_path):
    """Ścieżka jest DOWODEM, nie prawdą: folder mówi `NGC7635`, nazwa pliku `NGC1491` → propozycji
    NIE MA, grupa niezaznaczona, zapis wygaszony. Zgadywanie tu byłoby zapisem do cudzego pliku."""
    from horreum import scan
    v, con, files, _open = repair
    p = _nameless_tree(tmp_path, names=("NGC1491_20220130_x.fits",), seed=7)[0]
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW_PD,
                       summary=scan.ScanSummary())
    dlg = _open()
    assert len(dlg._groups) == 1 and len(dlg._groups[0]["rows"]) == 3   # ten sam folder
    g = dlg._groups[0]
    assert g["edit"].text() == "" and not g["check"].isChecked()
    assert not dlg.save_btn.isEnabled()
    dlg.reject()


def test_walidacja_kanonu_bramki_odmowy(repair):
    """D-PD-4: kolejność `strip` → `catalog_canon` → bramki. Do pliku idzie forma KANONICZNA
    (kolaps spacji + upper), nigdy surowy segment; nie-ASCII, przepełnienie rekordu i nazwa
    nierozpoznawalna przez resolver są ODMOWĄ (zero zapisu), nie 'failed' po commicie."""
    from horreum.gui.app import _validate_object_value as val
    v, con, files, _open = repair
    assert val(con, "  ngc 7635 ")[0] == "NGC7635"           # normalizacja PRZED zapisem
    assert val(con, "M 42")[0] == "M42"
    assert val(con, "")[1] and val(con, "   ")[1]            # pusto
    assert val(con, "Mgławica Serce")[1]                     # nie-ASCII
    assert val(con, "NGC" + "7" * 70)[1]                     # dłuższe niż rekord nagłówka
    assert val(con, "Wesolinka Kosmiczna 7")[1]              # ani katalog, ani znana nazwa
    # nazwa potoczna, którą resolver ZNA, przechodzi (i idzie do pliku w formie usera)
    assert val(con, "Bubble Nebula")[0] == "Bubble Nebula"


def test_czwarta_bramka_pyta_cala_drabina_nazwy(repair):
    """Adjudykacja czwartej bramki (2026-08-01): pytanie brzmi „czy PRZEBIEG rozpozna tę nazwę",
    a przebieg ma szczeble zależne od nazwy — solar → katalog → SŁOWNIK → ALIAS. Bramka pytająca
    samym `resolve_object` odmawiała zapisu nazw, które resolver rozwiązuje: `Moon`/`C/2023 A3`
    (archiwum ma `_COMETS` i `_SOLAR` jako realne lighty) oraz nazwy nauczonej wcześniej
    „Przypisz obiekt…". To był fałsz o własnym zachowaniu.

    PIN PRZESTEMPLOWANY W S1 (słownik obiektów własnych): `WR134` był tu przykładem nazwy „nieznanej
    NIKOMU, dopóki user jej nie nauczy" — i przestał nim być, bo to właśnie ten rekord przeniósł się
    do `objects_own.json` i drabina zna go teraz z assetu. Przewrócenie pinu jest CELEM segmentu,
    nie jego skutkiem ubocznym; rolę nazwy nieznanej przejmuje string spoza wszystkich szczebli."""
    from horreum.gui.app import _validate_object_value as val
    from horreum import resolver
    v, con, files, _open = repair
    assert val(con, "Moon")[0] == "Moon"                     # szczebel solar
    assert val(con, "C/2023 A3")[0] == "C/2023 A3"           # kometa (IAU-desig)
    assert val(con, "WR134")[0] == "WR134"                   # szczebel SŁOWNIKA (S1) — bez nauki
    assert val(con, "Zupelnie Wymyslona 77")[1]              # nieznana NIKOMU → odmowa
    oid, _ = repo.upsert_object(con, canon="ZW77", catalog=None, kind="deep_sky", now=NOW_PD)
    repo.add_object_alias(con, alias_norm="ZUPELNIEWYMYSLONA77", object_id=oid, source="user",
                          now=NOW_PD)
    assert val(con, "Zupelnie Wymyslona 77")[0] == "Zupelnie Wymyslona 77"   # user nauczył → przejdzie
    assert not resolver.name_resolves(con, "---")            # pusty klucz aliasu NIE łapie wszystkiego


def test_dwa_takty_zapis_do_pliku_i_kolejka_pusta(repair):
    """Takt 1+2 JEDNYM kliknięciem: staging → commit → re-sync zeznania. Karta ląduje w PLIKU,
    `sha1_data` (tożsamość danych) NIE rusza się, a kubełek kolejki gaśnie już po takcie 2.
    Obiektu jeszcze NIE MA — to zadanie taktu 3."""
    from astropy.io import fits
    v, con, files, _open = repair
    before = {r["frame_id"]: r["sha1_data"] for r in queries.nameless_frames(con)}
    dlg = _open()
    dlg._on_save()
    assert [fits.getheader(str(p))["OBJECT"] for p in files] == ["NGC7635", "NGC7635"]
    after = con.execute(
        "SELECT f.id, f.sha1_data, h.object_raw, f.object_id FROM frame f "
        "JOIN header h ON h.frame_id = f.id").fetchall()
    assert {r["id"]: r["sha1_data"] for r in after} == before      # tożsamość przeżyła zapis
    assert {r["object_raw"] for r in after} == {"NGC7635"}         # zeznanie odświeżone re-syncem
    assert {r["object_id"] for r in after} == {None}               # oś czeka na takt 3
    assert queries.review_queue(con)["nameless_count"] == 0
    assert not dlg.undo_btn.isHidden() and not dlg.resolve_btn.isHidden()   # okno bez show(): isVisible() zawodne
    assert "commit 1" in dlg.status.text()                         # commit_id WIDOCZNY (D-PD-7)
    assert not dlg.save_btn.isEnabled()          # karty w plikach → drugi zapis byłby pustym biegiem
    assert "2" not in dlg.save_btn.text()        # licznik mówi ILE ZOSTAŁO (zero), nie ile BYŁO
    dlg.reject()


def test_cofnij_przywraca_plik_i_kubelek(repair):
    """D-PD-7: „Cofnij" żyje od udanego zapisu do zamknięcia okna. Kontrakt jest SEMANTYCZNY —
    karta znika, klatka wraca do kubełka; `sha1_data` stoi (undo nie rusza danych)."""
    from astropy.io import fits
    v, con, files, _open = repair
    dlg = _open()
    dlg._on_save()
    dlg._on_undo()
    assert all("OBJECT" not in fits.getheader(str(p)) for p in files)
    assert queries.review_queue(con)["nameless_count"] == 2
    assert dlg.undo_btn.isHidden()                  # commit ZUŻYTY — drugi undo nie ma czego cofać
    assert dlg.save_btn.isEnabled()                 # karty zdjęte → zapis znów ma sens
    assert "2" in dlg.save_btn.text()               # …i licznik wraca: znów jest co zapisać
    dlg.reject()


def test_takt3_delegowany_a_odmowa_zostawia_okno(repair):
    """D-PD-6: „Rozwiąż teraz" NIE uruchamia resolvera z dialogu — deleguje do etapu Dostawy.
    Odmowa (etap w biegu) ZOSTAWIA okno otwarte i NIE chowa „Cofnij": okno cofania musi przeżyć
    nieudaną delegację, inaczej UI potwierdzałoby sukces, którego nie było."""
    v, con, files, _open = repair
    calls = []

    def _refuse():
        calls.append("x")
        return "etap w biegu — uruchom Rozwiąż po jego zakończeniu"

    dlg = _open(run_stage_fn=_refuse)
    dlg._on_save()
    dlg._on_resolve()
    assert calls == ["x"] and dlg.result() != QDialog.Accepted
    assert not dlg.undo_btn.isHidden() and "etap w biegu" in dlg.error.text()
    dlg.reject()

    ok = _open(run_stage_fn=lambda: None)
    ok._on_save()
    ok._on_resolve()
    assert ok.result() == QDialog.Accepted           # udana delegacja zamyka okno


def test_pominiete_widoczne_z_powodem(repair):
    """Klatka bez OBECNEJ kopii nie jest celem zapisu — i to MA być widać. Powód pochodzi z tej
    samej funkcji, która odsieje ją przy zapisie (`macro.resolve_target`), więc lista pominiętych
    nie jest drugą regułą, tylko tym samym zdaniem powiedzianym wcześniej."""
    v, con, files, _open = repair
    fid = con.execute("SELECT id FROM frame ORDER BY id LIMIT 1").fetchone()[0]
    row = con.execute("SELECT id, path FROM location WHERE frame_id = ?", (fid,)).fetchone()
    repo.mark_location_vanished(con, location_id=row["id"], expected_path=row["path"],
                                root=str(files[0].parent), run_id="r1", now=NOW_PD)
    dlg = _open()
    assert len(dlg._skipped) == 1 and "brak obecnej kopii" in dlg._skipped[0][1]
    assert sum(len(g["rows"]) for g in dlg._groups) == 1        # druga klatka nadal do naprawy
    dlg.reject()


def test_zamkniecie_bez_commitu_nie_zostawia_stagingu(repair):
    """Staging bez commitu jest SIEROTĄ — `run_id` zna tylko to okno, więc zamknięcie go kasuje.
    Po udanym commicie wierszy 'applied' nie ruszamy (są kotwicą undo)."""
    v, con, files, _open = repair
    lid = con.execute("SELECT id FROM location ORDER BY id LIMIT 1").fetchone()[0]
    dlg = _open()
    dlg._run_id = "sierota"
    repo.stage_pending(con, run_id="sierota", location_id=lid, keyword="OBJECT", idx=None,
                       op="add", old_value=None, new_value="X", new_type="str", new_comment=None,
                       expected_header_hash=None)
    dlg.reject()
    assert con.execute("SELECT count(*) FROM pending_changes").fetchone()[0] == 0


# ============================================================ S2: „Zatwierdź ze ścieżki…" (D-OW-2/B)
# Szczebel ścieżki PROPONUJE, a zapis następuje dopiero tu — więc to okno JEST segmentem, nie jego
# ozdobą. Populacja: RAW-owe lighty (`filetype='raw'`), których nagłówek milczy o obiekcie,
# a nazwa mieszka WYŁĄCZNIE w folderze. Fikstura wstawia je surowym SQL — skan RAW-a wymagałby
# realnego pliku DNG/ARW, a testowany jest read-model i klinga, nie czytnik EXIF.

NOW_S2 = "2026-08-03T12:00:00Z"
R_S2 = "R:\\ASTRO_"


@pytest.fixture
def sciezka(qapp, tmp_path):
    """ObjectAxisView nad bazą z 3 klatkami `LMC` i 1 klatką z folderu, którego NIE ZNA żaden
    szczebel. Do 2026-08-03 tę rolę grał `Orion`; po D-OW-3/A słownik go zna, więc czwarta klatka
    musi wskazywać folder ad-hoc — inaczej fikstura przestałaby dawać populację „bez propozycji",
    na której stoją trzy testy niżej (droga awaryjna ręki)."""
    con = db.open_db(str(tmp_path / "s2.db"))
    items = [(rf"{R_S2}\LIGHTS\LMC\A7R3_105\OSC\_7R3880{i}.ARW") for i in range(3)]
    items.append(rf"{R_S2}\LIGHTS\ProbaObiektywu\A7S1_070\OSC\_dsc9412.ARW")
    for i, path in enumerate(items, start=1):
        con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
                    "VALUES (?, 'light', 'raw', ?, ?)", (i, f"sha{i}", NOW_S2))
        con.execute("INSERT INTO header(frame_id, object_raw, raw_json) VALUES (?, NULL, '{}')",
                    (i,))
        con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?,'V',?,1)",
                    (i, path))
    con.commit()
    v = ObjectAxisView(con, now_fn=lambda: NOW_S2)
    yield v, con
    v.close()
    con.close()


def test_kubelek_propozycji_ma_wlasny_wiersz_i_akcje(sciezka):
    """Wiersz stoi POD kubełkiem RAW i mówi OBIE jednostki (nazwy / klatki). Akcja aktywna
    WYŁĄCZNIE przy nim i poza biegiem pipeline'u; „Napraw nagłówek…" tu NIE działa (to inna droga
    — karta w pliku, której RAW mieć nie może)."""
    v, con = sciezka
    q = queries.review_queue(con)
    assert (q["nameless_raw_count"], q["path_proposed_names"], q["path_proposed_frames"]) \
        == (4, 1, 3)                      # folder ad-hoc bez wpisu w słowniku → bez propozycji
    _select_review_tag(v, "path_proposals")
    assert v.confirm_path_btn.isEnabled()
    assert not v.repair_btn.isEnabled() and not v.assign_btn.isEnabled()
    assert v.frames.rowCount() == 3                    # drążenie pokazuje KLATKI propozycji
    v.set_busy(True)
    assert not v.confirm_path_btn.isEnabled()
    v.set_busy(False)
    assert v.confirm_path_btn.isEnabled()


def test_okno_grupuje_PO_NAZWIE_i_oznacza_nowa(sciezka):
    """3 klatki ⇒ JEDNA pozycja (jednostką przeglądu jest NAZWA). Falsyfikator znacznika: `NGC6960`
    przy ISTNIEJĄCYCH `NGC6992`/`Veil` jest NOWY — to jeden obiekt nieba w trzech pozycjach facetu
    i dokładnie po to ten znacznik istnieje."""
    v, con = sciezka
    con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
                "VALUES (9, 'light', 'raw', 'sha9', ?)", (NOW_S2,))
    con.execute("INSERT INTO header(frame_id, object_raw, raw_json) VALUES (9, NULL, '{}')")
    con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (9,'V',?,1)",
                (rf"{R_S2}\LIGHTS\NGC6960\A7R3\OSC\x.ARW",))
    con.execute("INSERT INTO object(canon, catalog, kind) VALUES ('NGC6992','NGC','deep_sky')")
    con.execute("INSERT INTO object(canon, catalog, kind) VALUES ('Veil', NULL, 'region')")
    con.commit()

    dlg = ConfirmPathObjectsDialog(con, proposals=resolver.path_proposals(con),
                                   now_fn=lambda: NOW_S2, parent=v)
    pozycje = {it["proposal"].canon: it["proposal"] for it in dlg._items}
    assert set(pozycje) == {"LMC", "NGC6960"}                     # 4 klatki ⇒ 2 pozycje
    assert pozycje["LMC"].n_frames == 3
    assert pozycje["LMC"].folder == rf"{R_S2}\LIGHTS\LMC"         # folder ŹRÓDŁOWY przy pozycji
    assert pozycje["NGC6960"].is_new and pozycje["LMC"].is_new
    assert all(it["check"].isChecked() for it in dlg._items)      # domyślnie WSZYSTKO zaznaczone
    dlg.reject()


def test_zatwierdz_wszystko_POMIJA_odznaczone(sciezka):
    """„Zatwierdź wszystko" znaczy „wszystko, co zostawiłeś zaznaczone" — odznaczenie jednej z pozycji
    ma zostawić jej klatki nietknięte, a nie zapisać je „przy okazji"."""
    v, con = sciezka
    con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
                "VALUES (9, 'light', 'raw', 'sha9', ?)", (NOW_S2,))
    con.execute("INSERT INTO header(frame_id, object_raw, raw_json) VALUES (9, NULL, '{}')")
    con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (9,'V',?,1)",
                (rf"{R_S2}\LIGHTS\NGC6960\A7R3\OSC\x.ARW",))
    con.commit()

    dlg = ConfirmPathObjectsDialog(con, proposals=resolver.path_proposals(con),
                                   now_fn=lambda: NOW_S2, parent=v)
    for it in dlg._items:
        if it["proposal"].canon == "LMC":
            it["check"].setChecked(False)
    assert "1" in dlg.confirm_btn.text()                  # licznik mówi, ile pójdzie do zapisu
    dlg._on_confirm()
    kanony = {r[0] for r in con.execute("SELECT canon FROM object").fetchall()}
    assert kanony == {"NGC6960"}, "odznaczona pozycja nie ma prawa nic zapisać"
    assert con.execute(
        "SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0] == 1


def test_zatwierdzenie_pisze_klinga_reki_ze_zrodlem_path(sciezka):
    """Falsyfikator §4/19: klatka z propozycji ma dawać się cofnąć akcją z S2b — co działa wtedy
    i tylko wtedy, gdy zapis poszedł TĄ SAMĄ klingą i nadał źródło `path`. Alias ze ścieżki NIE
    powstaje: segment nie trafi żadnego przyszłego `object_raw`."""
    v, con = sciezka
    przed = _events(con)
    dlg = ConfirmPathObjectsDialog(con, proposals=resolver.path_proposals(con),
                                   now_fn=lambda: NOW_S2, parent=v)
    dlg._on_confirm()
    assert dlg.assigned == 3 and dlg.result() == QDialog.Accepted
    stan = con.execute(
        "SELECT object_source, count(*) AS n FROM frame WHERE object_id IS NOT NULL "
        "GROUP BY object_source").fetchall()
    assert [(r["object_source"], r["n"]) for r in stan] == [("path", 3)]
    assert con.execute("SELECT count(*) FROM object_alias").fetchone()[0] == 0
    assert _events(con) > przed
    # kubełek gaśnie razem z populacją — kolejka mówi świeżą prawdę po zapisie
    assert queries.review_queue(con)["path_proposed_frames"] == 0


def test_kubelek_raw_ma_tag_drazenie_i_akcje(sciezka):
    """S4 / bramka 13 — POTRÓJNA RÓWNOŚĆ kubełka RAW: licznik kolejki == długość drążenia ==
    kotwica rdzenia. Do S4 licznik był osobnym COUNT-em (jedyny wyłom wobec D-PD-10 w read-modelu),
    a wiersz nie miał tagu — czyli jedyna droga naprawy tej populacji nie miała powierzchni.

    „Napraw nagłówek…" przy tym kubełku milczy i to nie jest przeoczenie: format nie ma karty
    `OBJECT`, więc okno zapisu do PLIKU otwierałoby listę, której każda pozycja jest pominięta."""
    v, con = sciezka
    from horreum.resolver import nameless_raw_lights
    q = queries.review_queue(con)
    assert q["nameless_raw_count"] == len(queries.nameless_raw_frames(con)) \
        == nameless_raw_lights(con) == 4
    _select_review_tag(v, "nameless_raw")
    assert v.assign_btn.isEnabled()
    assert not v.repair_btn.isEnabled() and not v.confirm_path_btn.isEnabled()
    assert v.frames.rowCount() == 4                     # drążenie pokazuje KLATKI kubełka
    assert "Format nie ma karty OBJECT" in v.assign_btn.toolTip()
    v.set_busy(True)
    assert not v.assign_btn.isEnabled()
    v.set_busy(False)
    assert v.assign_btn.isEnabled()


def test_dialog_bez_zeznania_kanon_ze_slownika_NIE_TWORZY_klucza(sciezka):
    """`catalog`/`kind` idą z WPISU SŁOWNIKA (`None`/`own`), nie z zaszytego `deep_sky`, a nota mówi
    o pustej kolumnie „Katalog" ZANIM user kliknie.

    KLUCZA ALIASU NIE MA — i to jest sedno adjudykacji recenzji diffu S4. Dyskryminatorem jest
    WŁAŚCICIEL DRABINY („czy kanon broni się bez aliasu"), nie sam `catalog_canon`. Gdyby liczył
    tylko gramatykę, ręka zakładałaby na kanonie słownika alias `source='user'` — a wtedy
    `sync_own_aliases` przestaje zasiewać własny (`istniejace == oid` ⇒ `continue`) i
    `retire_alias_and_unassign`, który wycofuje WYŁĄCZNIE `curated`, nie widzi już kanonu jako
    zdjętego. Usunięcie `LMC` ze słownika zostawiałoby klatki przypięte do obiektu, którego słownik
    nie zna, przy `§5.9` ZIELONEJ. Falsyfikator jest niżej — `zero_aliasow_po_zapisie`."""
    v, con = sciezka
    dlg = AssignObjectDialog(con, object_raw=None, frame_count=4, parent=v)
    assert "bez nazwy w metadanych" in dlg.head.text()   # nagłówek nie cytuje nazwy — nie ma której
    dlg.designation.setText("LMC")
    assert dlg.accept_btn.isEnabled()
    # `isHidden()` odwrócone, nie `isVisible()`: przy niepokazanym oknie to drugie kłamie (STANDING)
    assert not dlg.own_note.isHidden() and "obiekt własny" in dlg.own_note.text()
    dlg._validate_and_accept()
    assert dlg.selected == ("LMC", None, "own", None)
    dlg.close()


def test_zapis_ze_slownika_zostawia_odwracalnosc_R_S1_4(sciezka):
    """FALSYFIKATOR naprawy wyżej, na SKUTKU, nie na kształcie krotki: po ręcznym nazwaniu klatek
    kanonem ze słownika `sync_own_aliases` MUSI móc zasiać własny alias `curated` — bo to on jest
    jedynym strażnikiem kanonu przy usunięciu wpisu z assetu (klatki RAW nie mają zeznania, więc
    innego świadka nie ma). Alias `user` na kanonie zabierał mu tę możliwość NA ZAWSZE."""
    v, con = sciezka
    dlg = AssignObjectDialog(con, object_raw=None, frame_count=4, parent=v)
    dlg.designation.setText("LMC")
    dlg._validate_and_accept()
    canon, catalog, kind, alias_norm = dlg.selected
    repo.user_assign_object(con, alias_norm=alias_norm, canon=canon, catalog=catalog, kind=kind,
                            frame_ids=[1, 2, 3], now=NOW_S2)
    assert con.execute("SELECT count(*) FROM object_alias").fetchone()[0] == 0
    resolver.sync_own_aliases(con, NOW_S2)
    zasiane = {(r["alias_norm"], r["source"]) for r in con.execute(
        "SELECT alias_norm, source FROM object_alias").fetchall()}
    assert ("LMC", "curated") in zasiane, "kanon MUSI mieć równoważność `curated` — inaczej " \
                                          "wycofanie wpisu ze słownika nie odepnie klatek"
    dlg.close()


def test_dialog_bez_zeznania_kanon_nieznany_drabinie_BIERZE_klucz(sciezka):
    """Przypadek DRUGI — jedyny, w którym klucz realnie powstaje: kanon, którego ŻADEN szczebel
    drabiny nie zna (tu `Veil`, kanon powstały z REGIONU po współrzędnych). Bez tej równoważności
    przyszły nagłówek mówiący „Veil" nie miałby czym trafić tego obiektu."""
    v, con = sciezka
    con.execute("INSERT INTO object(canon, catalog, kind) VALUES ('Veil', NULL, 'deep_sky')")
    oid = con.execute("SELECT id FROM object WHERE canon='Veil'").fetchone()[0]
    con.commit()
    repo.assign_object(con, frame_id=4, object_id=oid, object_source="region", now=NOW_S2)
    dlg = AssignObjectDialog(con, object_raw=None, frame_count=3, parent=v)
    for i in range(dlg.combo.count()):
        if dlg.combo.itemData(i) is not None and dlg.combo.itemData(i)[1] == "Veil":
            dlg.combo.setCurrentIndex(i)
            break
    dlg._validate_and_accept()
    assert dlg.selected == ("Veil", None, None, "VEIL")
    assert dlg.own_note.isHidden()                  # `catalog` pusty, ale to NIE obiekt własny
    dlg.close()


def test_dialog_bez_zeznania_z_gramatyki_NIE_TWORZY_klucza(sciezka):
    """Przypadek TRZECI — najczęstszy realny gest S4: RAW-y + `NGC 7635`. Klucz aliasu NIE powstaje,
    bo byłby samozwrotny: gramatyka katalogowa stoi w drabinie NAD aliasem, więc nikt o taki klucz
    nigdy nie zapyta, a diff-first słownika by go nie usunął (`source='user'`).

    FALSYFIKATOR: do S4 ta ścieżka kończyła się twardym `ValueError` z `repo` („nazwa bez znaków
    alfanumerycznych") — komunikatem kłamiącym o przyczynie. Dlatego test sprawdza też, że zapis
    przez klingę PRZECHODZI i nie zostawia ani jednego wiersza `object_alias`."""
    v, con = sciezka
    dlg = AssignObjectDialog(con, object_raw=None, frame_count=4, parent=v)
    dlg.designation.setText("NGC 7635")
    dlg._validate_and_accept()
    assert dlg.selected == ("NGC7635", "NGC", "deep_sky", None)
    # `isHidden()` wprost — `not isVisible()` na niepokazanym oknie jest zawsze prawdą, czyli
    # bramką, która nie może się zaczerwienić (ta sama pułapka, co przy nocie wyżej)
    assert dlg.own_note.isHidden()                      # kanon katalogowy — kolumna „Katalog" pełna
    canon, catalog, kind, alias_norm = dlg.selected
    g = repo.user_assign_object(
        con, alias_norm=alias_norm, canon=canon, catalog=catalog, kind=kind,
        frame_ids=[1, 2], now=NOW_S2)
    assert (g.assigned, g.skipped) == (2, 0)
    assert con.execute("SELECT count(*) FROM object_alias").fetchone()[0] == 0
    dlg.close()


def test_dialog_przyjmuje_nazwe_spoza_gramatyki_katalogowej(sciezka):
    """Bramka nazwy to CAŁA drabina, nie `catalog_canon`: nazwa potoczna wpisu słownika („Large
    Magellanic Cloud") i nazwa z drabiny solar („Moon") są rozwiązywalne przez przebieg, więc okno
    nie ma prawa ich odrzucać. Od D-OW-3/A (2026-08-03) dochodzi `Orion` — słownik go zna, więc
    okno przyjmuje go tą samą drogą co `LMC`. Odmowę pinuje odtąd nazwa spoza KAŻDEGO szczebla:
    bez niej test straciłby jedyny człon, który może się zaczerwienić."""
    v, con = sciezka
    dlg = AssignObjectDialog(con, object_raw=None, frame_count=4, parent=v)
    dlg.designation.setText("Large Magellanic Cloud")
    assert dlg.accept_btn.isEnabled()
    dlg._validate_and_accept()
    assert dlg.selected[0] == "LMC"
    dlg.designation.setText("Moon")
    assert dlg.accept_btn.isEnabled()
    dlg.designation.setText("Orion")                     # D-OW-3/A — wpis własny, kanon sam sobą
    assert dlg.accept_btn.isEnabled()
    dlg._validate_and_accept()
    assert dlg.selected[0] == "Orion"
    dlg.designation.setText("ProbaObiektywu")
    assert not dlg.accept_btn.isEnabled()
    assert "Nie rozpoznaję nazwy" in dlg.error.text()
    dlg.close()


def test_on_assign_raw_przypisuje_grupe_podana_parametrem(sciezka, monkeypatch):
    """Cała droga gestu: kubełek RAW → dialog → klinga ręki. Grupa jedzie do zapisu jako LISTA
    `frame_ids` z drążenia tego kubełka (nie z tagu), więc znika CAŁA — łącznie z klatką z folderu
    ad-hoc, której szczebel ścieżki nie umiał zaproponować. To jest droga awaryjna dla wszystkiego, czego
    ścieżka nie domknie."""
    v, con = sciezka

    class AcceptedLMC:
        selected = ("LMC", None, "own", None)      # kanon słownikowy broni się sam → bez klucza

        def __init__(self, *args, **kwargs):
            self.frame_count = kwargs["frame_count"]
            AcceptedLMC.seen = kwargs

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr("horreum.gui.app.AssignObjectDialog", AcceptedLMC)
    _select_review_tag(v, "nameless_raw")
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_assign()

    assert AcceptedLMC.seen["object_raw"] is None and AcceptedLMC.seen["frame_count"] == 4
    assert msgs[-1] == "Przypisano 4 z 4 klatek → LMC."
    stan = con.execute("SELECT object_source, count(*) AS n FROM frame "
                       "WHERE object_id IS NOT NULL GROUP BY object_source").fetchall()
    assert [(r["object_source"], r["n"]) for r in stan] == [("user", 4)]
    assert queries.review_queue(con)["nameless_raw_count"] == 0     # kubełek gaśnie z populacją


def test_cel_gestu_to_ZAZNACZENIE_panelu_nie_cala_lista(sciezka, monkeypatch):
    """Adjudykacja recenzji diffu S4 (P1 #2): kubełek RAW nie jest grupą semantyczną, tylko RESZTĄ —
    na żywej bazie 763 klatki z kilkudziesięciu folderów. Zapis całej listy jednym kliknięciem
    nadałby im JEDEN kanon ze źródłem `user`, którego dzisiejsza aplikacja nie umie cofnąć.

    Trzy człony: (a) drążenie zaznacza wszystko, więc gest „cały kubełek" kosztuje tyle samo co
    przedtem · (b) PRZYCIĘCIE zaznaczenia przycina zapis — reszta kubełka zostaje nietknięta ·
    (c) puste zaznaczenie gasi akcję, a falsyfikator woła SLOT (klik w wyszarzony przycisk
    przeszedłby trywialnie) i nie pisze ani jednego wiersza."""
    v, con = sciezka

    class AcceptedLMC:
        selected = ("LMC", None, "own", None)

        def __init__(self, *args, **kwargs):
            AcceptedLMC.seen = kwargs

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr("horreum.gui.app.AssignObjectDialog", AcceptedLMC)
    _select_review_tag(v, "nameless_raw")
    assert len(v._selected_frame_ids()) == 4          # (a) drążenie zaznacza CAŁY kubełek

    v.frames.clearSelection()                          # (c) puste zaznaczenie
    assert not v.assign_btn.isEnabled()
    przed = _events(con)
    v._on_assign()                                     # falsyfikator: SLOT, nie przycisk
    assert _events(con) == przed
    assert con.execute("SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0] == 0

    v.frames.selectRow(0)                              # (b) przycięcie do JEDNEJ klatki
    assert v.assign_btn.isEnabled()
    v._on_assign()
    assert AcceptedLMC.seen["frame_count"] == 1        # okno mówi o CELU, nie o kubełku
    assert con.execute("SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0] == 1
    assert queries.review_queue(con)["nameless_raw_count"] == 3   # reszta kubełka nietknięta


def test_okno_nie_pisze_dopoki_nie_klikniesz(sciezka):
    """Rdzeń wariantu B po stronie EKRANU: samo otwarcie i przejrzenie listy nie rusza ani jednego
    wiersza. Odznaczenie wszystkiego → akcja wygaszona, zero zapisu, powód na ekranie."""
    v, con = sciezka
    przed = _events(con)
    dlg = ConfirmPathObjectsDialog(con, proposals=resolver.path_proposals(con),
                                   now_fn=lambda: NOW_S2, parent=v)
    for it in dlg._items:
        it["check"].setChecked(False)
    assert not dlg.confirm_btn.isEnabled()
    dlg._on_confirm()                                  # falsyfikator woła SLOT, nie przycisk
    assert dlg.error.text() and dlg.assigned == 0
    assert _events(con) == przed
    assert con.execute("SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0] == 0
    dlg.reject()


# ═════════════════════════ S3/R-S2b-1 — CZŁON „COFNIĘTE RĘKĄ" (bramka 14b, wykonawcza część)


def test_kubelek_RAW_rozszczepia_sie_po_zrodle_a_akcja_przestaje_milczec(sciezka):
    """Bramka 14b, człon, który do S3 nie miał wykonawcy: kubełek z akcją, która na cofniętej
    klatce NIC nie robiła.

    Klatka z nagrobkiem wraca do tego samego kubełka (predykat pyta o sam brak obiektu) i do
    rozszczepienia wyglądała identycznie jak nietknięta. „Przypisz obiekt…" wołało klingę BEZ
    `overwrite_weak`, więc nagrobek wpadał w `source_skip` i user dostawał „przypisano 0 z N"
    bez powodu: kubełek miał akcję, akcja go nie tykała, a jedyna działająca droga leżała
    w zupełnie innym miejscu nawigacji (Zbiory) i nic o niej nie mówiło."""
    v, con = sciezka
    ids = [r["frame_id"] for r in queries.nameless_raw_frames(con)][:2]
    repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                            kind="deep_sky", frame_ids=ids, now=NOW_S2)
    assert repo.clear_object_assignment(con, frame_ids=ids, now=NOW_S2).assigned == 2
    v._load_review()

    q = queries.review_queue(con)
    assert (q["nameless_raw_count"], q["nameless_raw_cleared_count"]) == (2, 2)
    _select_review_tag(v, "nameless_raw_cleared")
    assert v.frames.rowCount() == 2                  # drążenie po PARZE, nie unia obu połówek
    assert v.assign_btn.isEnabled()
    assert "cofnąłeś" in v.assign_btn.toolTip()      # tooltip mówi, że to DRUGI gest człowieka

    v._select_all_frames()
    g = repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                                kind="deep_sky", frame_ids=v._selected_frame_ids(),
                                now=NOW_S2, overwrite_weak=True)
    assert (g.assigned, g.skipped) == (2, 0)         # nagrobek NIE jest już cichym pominięciem


def test_drazenie_po_parze_NIE_zwraca_unii_obu_polowek(sciezka):
    """Falsyfikator rozszczepienia: gdyby klucz został samym stringiem, zapis z jednej połówki
    sięgnąłby klatek spoza klikniętego wiersza — a obie połówki wyglądają na ekranie tak samo."""
    v, con = sciezka
    ids = [r["frame_id"] for r in queries.nameless_raw_frames(con)][:2]
    repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                            kind="deep_sky", frame_ids=ids, now=NOW_S2)
    repo.clear_object_assignment(con, frame_ids=ids, now=NOW_S2)
    swieze = {r["frame_id"] for r in queries.nameless_raw_frames(con)}
    cofniete = {r["frame_id"] for r in queries.nameless_raw_frames(con, cleared=True)}
    assert cofniete == set(ids)
    assert not (swieze & cofniete)                   # ROZŁĄCZNE, nie kubełek i jego podzbiór


def test_delta_daje_nagrobkowi_WLASNA_LICZBE_nie_wyklucza_go(sciezka):
    """R-S2b-2 / brief §5: cofnięta klatka ZOSTAJE w procencie — wykluczenie podnosiłoby
    `object_pct`, czyli metryka nagradzałaby odrzucenie zeznania, a ma mierzyć ROZPOZNANIE.
    Bez własnej liczby raport nie umiał jednak odróżnić WERDYKTU od braku wiedzy.

    Predykat stoi na SAMYM `object_source`, NIEZALEŻNIE od `object_raw` — falsyfikator: klatka RAW
    (bez zeznania w nagłówku) też musi się policzyć, bo bramka 14b żąda wyniku na OBU populacjach."""
    v, con = sciezka
    ids = [r["frame_id"] for r in queries.nameless_raw_frames(con)][:2]
    repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                            kind="deep_sky", frame_ids=ids, now=NOW_S2)
    przed = resolver.delta_report(con)
    repo.clear_object_assignment(con, frame_ids=ids, now=NOW_S2)
    po = resolver.delta_report(con)
    assert (przed.object_cleared, po.object_cleared) == (0, 2)   # RAW bez `object_raw` — liczy się
    # …i NIE ZNIKA z rachunku: wraca dokładnie tam, skąd ją wzięto (kubełek RAW rośnie o 2,
    # „rozwiązane bez nazwy w nagłówku" spada o 2). Sam licznik nagrobków bez tego członu
    # dałoby się zaimplementować jako wykluczenie populacji — i bramka by tego nie zobaczyła.
    assert (przed.object_nameless_raw, po.object_nameless_raw) == (2, 4)
    assert (przed.object_resolved_no_raw, po.object_resolved_no_raw) == (2, 0)
