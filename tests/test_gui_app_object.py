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
    COPY_PATH_MAX_PX, FRAME_COL_PATH, OBJ_COL_CANON, OBJ_COL_FRAMES)

from fixture_s8 import seed_object_axis

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QHeaderView, QTableWidget,
                               QTableWidgetItem)

UROLE = 0x0100   # Qt.UserRole — tag pozycji kolejki
# PAYLOAD ODJECHAŁ Z `UserRole+1` (R-S3-3): tę rolę zajmuje CZŁON DRUGI delegata (`rows.SECONDARY`),
# a `+2` człon trzeci. Test pyta o role po tych samych stałych, których używa widok — inaczej
# pinowałby adres, nie zachowanie.
SECONDARY = UROLE + 1            # „5 klatek  ›" — liczba + znacznik drogi, rysowane od prawej
TERTIARY = UROLE + 2             # „  ·  cofnięte ręką" — adnotacja we własnej kolumnie
UPAYLOAD = UROLE + 4
UINFO = UROLE + 5
UINDENT = UROLE + 6               # rola `rows.INDENT` (W-5) - poziom wcięcia członu pierwszego (int)


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
    # pozycja obiekt-review: dispatch po string-tagu (R#6) — UserRole=tag, UserRole+4=payload
    target = None
    for r in range(v.review.count()):
        if v.review.item(r).data(UROLE) == "object_raw" \
                and v.review.item(r).data(UPAYLOAD) == "FlatWizard":
            target = r
            break
    assert target is not None
    v.review.setCurrentRow(target)
    shas = _frame_shas(v)
    assert "sha-objrev1"[:12] in shas and "sha-objrev2"[:12] in shas
    # zaznaczenie review wyczyściło zaznaczenie obiektu (źródła klatek wzajemnie wykluczające)
    assert not v.objects.selectedItems()


def test_kolejka_liczniki_informacyjne(view):
    """#13/P4: „kopie nieczytelne" to OSOBNA, klikalna pozycja (drążenie Z6); licznik klatek bez
    nagłówka zostaje na pozycji informacyjnej (bez tagu → nieklikana).

    PRZESTEMPLOWANY W R1: oś SPRZĘTU wyszła z tego wiersza i dostała WŁASNY, klikalny (gest
    „Przypisz zestaw…" istnieje, więc nota „rozwiązywanie w przygotowaniu" o niej byłaby dziś
    kłamstwem). Nota zostaje wyłącznie nad klatkami bez nagłówka — tam naprawą jest ponowny
    odczyt pliku, nie decyzja w kolejce."""
    v, con, ids = view
    items = [(v.review.item(r).text(), v.review.item(r).data(UROLE))
             for r in range(v.review.count())]
    # fixture §8 nie ma oznaczonych kopii → 0. KUBEŁEK PUSTY NIE MA DOKĄD PROWADZIĆ (wiz T2 N6):
    # drążenie w zero otwierało tabelę bez ani jednego wiersza i bez zdania, a wyszarzony wiersz
    # zaznaczalny spadał na podświetleniu do 1,84:1 kontrastu (T2 N3). Jedna reguła dla wszystkich
    # kubełków — `nameless` zachowywał się tak od początku. Klikalny wraca przy n>0 (#13/Z6).
    assert any(t.startswith("— kopie nieczytelne") and tag is None for t, tag in items)
    # nota „rozwiązywanie w przygotowaniu" zawężona do JEDNEGO kanału bez akcji (R#9 → R1)
    assert any("bez nagłówka" in t and "config-review" not in t
               and "rozwiązywanie w przygotowaniu" in t and tag is None for t, tag in items)
    # …a oś sprzętu ma odtąd własny wiersz Z DROGĄ (fixture §8: 4 klatki bez zestawu)
    assert any(t.startswith("— bez zestawu (teleskop × kamera)")
               and tag == "config_review" for t, tag in items)
    # LICZBA MIESZKA W CZŁONIE DRUGIM (bramka pakietu, zarzut 2): w członie pierwszym była
    # elidowana bez drogi powrotu, odkąd lista straciła poziomy scroll. I jest ODMIENIONA (5).
    wiersz = _wiersz_kolejki(v, "config_review")
    assert wiersz[1].startswith("4 klatki") and "klatek" not in wiersz[0]


def test_kolejka_pokazuje_ktora_pozycja_prowadzi_dalej(view):
    """WIZ #11: pięć wierszy kolejki miało identyczny krój i kolor, a klikalne były dwa — nic na
    ekranie nie mówiło, który prowadzi dalej („do przypisania ręcznie" wzywało do akcji i nie
    prowadziło nigdzie). Znacznik „›" niesie WYŁĄCZNIE wiersz z drogą; jest pochodną tagu, więc
    nie może się z dispatchem rozjechać.

    OD R-S3-3 ZNACZNIK MIESZKA W CZŁONIE DRUGIM, nie w tekście: doklejony do nazwy jechał za jej
    długością, więc kolumny „co prowadzi dalej" nie dało się skanować wzrokiem. Pinowane jest
    ZACHOWANIE (znacznik ⇔ tag), nie miejsce, w którym string siedzi."""
    v, con, ids = view
    for r in range(v.review.count()):
        it = v.review.item(r)
        czlon2 = it.data(SECONDARY) or ""
        assert czlon2.endswith("›") == (it.data(UROLE) is not None)
        assert not it.text().endswith("›")        # …i NIE został w członie pierwszym


# --- F-2: wiersz informacyjny tłumaczy się sam (firsthand Zdzinia 0804) ---

def test_wiersz_informacyjny_ODPOWIADA_na_klik(view):
    """F-2, sedno zgłoszenia: klik w wiersz informacyjny nie dawał ŻADNEJ odpowiedzi.

    I to dosłownie — wiersz nie jest zaznaczalny, więc `itemSelectionChanged` w ogóle nie leci
    i nie ma nawet podświetlenia; dla użytkownika nieodróżnialne od zawieszenia aplikacji.
    Zmierzone przy zgłoszeniu: 0,1 ms na „config-review: 433 · bez nagłówka: 1", czyli aplikacja
    była gotowa natychmiast i po prostu MILCZAŁA.

    Falsyfikator: odepnij `itemClicked` → żaden wiersz bez tagu nie odezwie się ani słowem."""
    v, con, ids = view
    msgs = []
    v.status_message.connect(msgs.append)
    informacyjne = [v.review.item(r) for r in range(v.review.count())
                    if v.review.item(r).data(UROLE) is None]
    assert informacyjne, "fikstura nie ma ani jednego wiersza informacyjnego"

    for it in informacyjne:
        przed = len(msgs)
        v._on_review_clicked(it)
        assert len(msgs) == przed + 1, f"wiersz {it.text()!r} nie odpowiedział na klik"
        assert msgs[-1].strip(), "odpowiedź jest pusta"


def test_wiersz_informacyjny_MA_TOOLTIP_mowiacy_dlaczego_nie_prowadzi(view):
    """F-2, druga powierzchnia tego samego faktu: tooltip pod kursorem, zanim user w ogóle kliknie.

    Wiersz z DROGĄ tooltipa nie potrzebuje — jego odpowiedzią jest drążenie. Bramka pilnuje więc
    obu stron rozdziału, bo tooltip na wszystkim byłby szumem."""
    v, con, ids = view
    for r in range(v.review.count()):
        it = v.review.item(r)
        if it.data(UROLE) is None:
            assert it.toolTip().strip(), f"wiersz informacyjny {it.text()!r} milczy pod kursorem"


def test_wiersz_licznikow_TLUMACZY_ze_to_INNA_OS(view):
    """F-2: wiersz „bez nagłówka" opisuje INNĄ OŚ i to jest powód, dla którego nie prowadzi nigdzie.
    Zdanie ogólne („to wiersz informacyjny") byłoby prawdziwe, ale bezużyteczne: user dalej nie
    wiedziałby, gdzie tę sprawę załatwić.

    WIERSZ ROZPOZNAJEMY PO JEGO WŁASNYM ZDANIU, nie po fragmencie tekstu licznika — bo tekst
    licznika już raz się zmienił (R1 wyprowadził z niego oś sprzętu) i szukanie po „config-review"
    przewróciło ten test, choć powierzchnia była poprawna. Tożsamością wiersza jest recepta."""
    from horreum.gui import i18n
    v, con, ids = view
    msgs = []
    v.status_message.connect(msgs.append)
    powod = i18n.t("object.review_info_why")
    for r in range(v.review.count()):
        it = v.review.item(r)
        if it.data(UROLE) is None and it.toolTip() == powod:
            v._on_review_clicked(it)
            assert msgs[-1] == powod
            assert msgs[-1] != i18n.t("object.review_info_generic")
            return
    raise AssertionError("nie znaleziono wiersza liczników")


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

def _select_review_tag_or_none(v, tag):
    """Numer pozycji o tym tagu albo `None` — pytanie o NIEOBECNOŚĆ wiersza (sierota vs para)."""
    for r in range(v.review.count()):
        if v.review.item(r).data(UROLE) == tag:
            return r
    return None


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


def test_TRZECI_przycisk_kolejki_tlumaczy_sie_gdy_wygaszony(view):
    """R-S3-7: „Napraw nagłówek…" miał `enabled=False` i PUSTY tooltip dla KAŻDEGO wiersza — jako
    jedyny w rzędzie, bo obaj sąsiedzi tłumaczą się od S2/S4.

    To nie jest kosmetyka: dwie drogi naprawy różnią się tym, CO tykają — ta pisze do PLIKÓW
    archiwum, „Przypisz obiekt…" tylko do bazy. Milczący przycisk zrównywał je wizualnie.

    Bramka pyta o RÓŻNICĘ zdań, nie o samą niepustość: jeden tekst dla wszystkich kubełków
    przeszedłby test „ma tooltip", a dalej nie mówiłby, gdzie iść."""
    v, con, ids = view
    _select_review_tag(v, "object_raw")
    tip_obcy = v.repair_btn.toolTip()
    assert tip_obcy.strip(), "wygaszony przycisk naprawy milczy"
    assert not v.repair_btn.isEnabled()

    v.review.clearSelection()
    v._sync_assign_enabled()
    tip_brak = v.repair_btn.toolTip()
    assert tip_brak.strip() and tip_brak != tip_obcy, "ten sam tekst dla dwóch różnych powodów"


def test_KAZDY_kubelek_kolejki_ma_WLASNA_recepte_naprawy(view):
    """R-S3-7 podniesione do BRAMKI KLASY — bo ten sam defekt złapałem dwa razy z rzędu.

    Drabina `if`-ów rosła o człon na kubełek i dwukrotnie zapomniała o kolejnym: `object_raw`
    (bramka poniżej) i `path_proposals` (firsthand na żywej kopii) dostawały zdanie „zaznacz
    kubełek" o wierszu, który user WŁAŚNIE zaznaczył — odpowiedź na pytanie, którego nie zadał.
    Znalezisko jednostkowe podnosimy więc do kontroli: bramka przechodzi CAŁĄ kolejkę i żąda,
    by żaden zaznaczalny wiersz nie dostawał recepty należącej do „nic nie wybrano".

    Kubełek dodany jutro bez wpisu w `_REPAIR_TIPS` przewróci ten test, zamiast po cichu odesłać
    użytkownika w złe miejsce."""
    from horreum.gui import i18n
    v, con, ids = view
    fallback = i18n.t("repair.tip_pick")

    v.review.clearSelection()
    v._sync_assign_enabled()
    assert v.repair_btn.toolTip() == fallback, "brak zaznaczenia ma dostać właśnie tę receptę"

    zbadane = 0
    for r in range(v.review.count()):
        tag = v.review.item(r).data(UROLE)
        if tag is None:
            continue                      # wiersz informacyjny ma własną powierzchnię (F-2)
        v.review.setCurrentRow(r)
        v._sync_assign_enabled()
        tip = v.repair_btn.toolTip()
        assert tip.strip(), f"kubełek {tag!r} milczy"
        assert tip != fallback, f"kubełek {tag!r} dostał receptę dla BRAKU zaznaczenia"
        zbadane += 1
    assert zbadane, "fikstura nie dała ani jednego klikalnego kubełka"

    # ŚWIADEK NIEZALEŻNY — lista spisana z `_load_review`, nie z mapy, którą sprawdza. Gdyby
    # bramka brała uniwersum tagów z `_REPAIR_TIPS`, byłaby tautologią: kubełek dopisany bez
    # recepty przechodziłby, bo jego brak w mapie znaczyłby też brak w pytaniu. Fikstura pokazuje
    # tylko część kubełków naraz, więc bez tego członu klasa zostałaby niedomknięta.
    from horreum.gui.app import _REPAIR_TIPS
    kubelki = {"object_raw", "object_raw_cleared", "nameless", "nameless_cleared",
               "nameless_raw", "nameless_raw_cleared", "path_proposals",
               "nameless_stacks", "nameless_stacks_cleared", "unreadable",
               # R1: oś SPRZĘTU — inna oś, więc własna recepta; DWA kubełki, bo droga powrotna
               # pomyłki ręki jest osobną populacją (bramka pakietu 3a, zarzut 1).
               "config_review", "config_by_hand"}
    brakuje = kubelki - set(_REPAIR_TIPS)
    assert not brakuje, f"kubełki bez własnej recepty naprawy: {sorted(brakuje)}"
    assert None in _REPAIR_TIPS, "brak zaznaczenia musi mieć jawny wpis, nie wpadać w `.get`"

    teksty = {t: i18n.t(k) for t, k in _REPAIR_TIPS.items()}
    assert all(v.strip() for v in teksty.values()), f"pusta recepta: {teksty}"


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
    """Po zapisie grupa znika, a widok pokazuje obiekt docelowy zamiast pierwszego alfabetycznie.
    Zdanie bez kropki na końcu (R-S2b-13): człony rozbicia doklejają się do niego „ · …", jak
    w zdaniach Zbiorów."""
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
    assert msgs[-1] == "Przypisano 2 z 2 klatek → M42"
    assert not any("FlatWizard" in v.review.item(r).text() for r in range(v.review.count()))


def test_on_assign_zero_assigned_nie_udaje_wyboru_celu(view, monkeypatch):
    """Gdy cała grupa zdryfowała, komunikat jest szczery, ale widok nie udaje sukcesu wyborem celu.

    Zdanie porównujemy W CAŁOŚCI (R-S2b-13): dawny `startswith` przepuszczał każdy ogon, także
    płaskie „(2 pominięte - zajęte…)", więc nie pilnował, JAKIM członem dryf trafia na ekran."""
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
    assert msgs[-1] == "Przypisano 0 z 2 klatek → M42 · zmieniły się w międzyczasie: 2"


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
    location z markerem); wybór obiektu przywraca tabelę klatek (tryb kopii znika, D-P4-5).

    P4-2 (F6): bramka dopasowania karmiona powodem o REALNEJ długości. Firsthand 2026-09-26 na
    kopii pf4: 150-znakowy powód (`PermissionError` z pełną ścieżką - takie wiersze zostają
    w bazach oznaczonych przed naprawą u źródła) przy `ResizeToContents` dawał „Powodowi" 963 px
    w panelu 571 px, a „Ścieżka" ze `Stretch` spadała do 86 px. Siedmioznakowe „OSError" tego nie
    widziało.

    Falsyfikator: wróć `Stretch` na „Ścieżkę", a „Powodowi" daj `ResizeToContents` → asercje
    trybów i szerokości ścieżki czerwienieją; zdejmij zdjęcie sufitu w `_restore_frames_mode` →
    tryb klatek dziedziczy sufit i asercja o nim czerwienieje. Sufit przy DŁUGIEJ nazwie pliku
    pilnuje `test_kopie_nieczytelne_ze_WSPOLNYM_prefiksem_rozroznia_nazwa_w_komorce`."""
    v, con, ids = view
    loc = con.execute("SELECT id FROM location WHERE volume = 'vol2'").fetchone()
    long_path = "/backup/" + "/".join(["bardzo-dlugi-segment"] * 20) + "/a1.fits"
    powod = f"PermissionError: [Errno 13] Permission denied: '{long_path}'"
    assert len(powod) >= 120
    with con:
        con.execute("UPDATE location SET path = ? WHERE id = ?", (long_path, loc["id"]))
    repo.refresh_location_unreadable(con, location_id=loc["id"], sha1_data="sha-a1",
                                     path=long_path, mtime="t2", reason=powod, kind="io",
                                     now="2026-07-21T12:00:00")
    v.refresh()
    r = _select_review_tag(v, "unreadable")
    # Liczba mieszka w CZŁONIE DRUGIM (bramka pakietu, zarzut 2) — w pierwszym była elidowana
    # bez drogi powrotu, odkąd lista straciła poziomy scrollbar.
    assert "kopie nieczytelne" in v.review.item(r).text()
    assert v.review.item(r).data(SECONDARY).startswith("1")
    hdrs = [v.frames.horizontalHeaderItem(c).text() for c in range(v.frames.columnCount())]
    assert hdrs == ["Ścieżka", "Wolumen", "Obecna", "Oznaczona", "Powód"]  # PL (stałe = klucze)
    assert v.frames.rowCount() == 1
    # Komórka niesie NAZWĘ PLIKU, podpowiedź - dokładną location (forma ścieżki z Duplikatów):
    # kopie dzielą długi prefiks archiwum, a sufit 200 px z elizją w środku gubił człon rozróżniający.
    assert v.frames.item(0, 0).text() == "a1.fits"
    assert v.frames.item(0, 0).toolTip() == long_path
    # FH-14: ścieżka elizuje w ŚRODKU (nazwa pliku zostaje), tym samym delegatem co w Duplikatach
    from horreum.gui import grid as grid_mod
    from PySide6.QtWidgets import QStyleOptionViewItem
    delegat = v.frames.itemDelegateForColumn(COPY_COL_PATH)
    assert isinstance(delegat, grid_mod._ElizjaWSrodku)
    opcja = QStyleOptionViewItem()
    delegat.initStyleOption(opcja, v.frames.model().index(0, COPY_COL_PATH))
    assert opcja.textElideMode == Qt.ElideMiddle
    # „Powód" bierze RESZTĘ, „Ścieżka" treść z sufitem, a „Powód" MUSI zmieścić się w panelu
    # (firsthand 2026-08-01 na żywej pf4: przy `ResizeToContents` 100-znakowa ścieżka wypychała
    # diagnozę poza prawą krawędź; firsthand 2026-09-26: 150-znakowy powód zgniatał ścieżkę).
    hh = v.frames.horizontalHeader()
    assert hh.sectionResizeMode(COPY_COL_REASON) == QHeaderView.Stretch
    assert hh.sectionResizeMode(COPY_COL_PATH) == QHeaderView.ResizeToContents
    # Zawijanie WYŁĄCZONE — inaczej elizja ścieżki (jedno słowo, zero spacji) tnie ją do „R:..."
    # niezależnie od szerokości sekcji i kolumna jest równie nieczytelna, co przed zmianą.
    assert not v.frames.wordWrap()
    v.resize(1073, 720)                       # podłoga sprzed D-0801-1, zmierzona realnym fontem
    #                                           („1146" z sondy offscreen było zawyżone) — węższe
    #                                           okno jest tu OSTRZEJSZYM testem niż dzisiejsze 1310
    qapp.processEvents()
    assert (hh.sectionPosition(COPY_COL_REASON) + hh.sectionSize(COPY_COL_REASON)
            <= v.frames.viewport().width())
    # nazwa pliku mieści się w sekcji bez elizji, a sekcja nie przebija sufitu
    assert (v.frames.sizeHintForColumn(COPY_COL_PATH) <= hh.sectionSize(COPY_COL_PATH)
            <= COPY_PATH_MAX_PX)
    assert v.frames.item(0, 1).text() == "vol2"
    assert v.frames.item(0, 2).text() == "tak"               # kopia nadal obecna
    # Powód ze STANU kopii (Z6, P4-2): rodzaj PRZED diagnozą, tooltip = diagnoza dosłowna
    assert v.frames.item(0, 4).text() == f"dysk/dostęp: {powod}"
    assert v.frames.item(0, 4).toolTip() == powod
    assert v.frames_label.text() == "Kopie nieczytelne (1)"
    # kopia przemianowana po awarii NIE gubi powodu (P4-2 - defekt dawnego źródła w dzienniku)
    with con:
        con.execute("UPDATE location SET path = ? WHERE id = ?", ("/backup/a1-NOWA.fits", loc["id"]))
    v.refresh()
    _select_review_tag(v, "unreadable")
    assert v.frames.item(0, 4).text() == f"dysk/dostęp: {powod}"
    # wiersz sprzed 0019 (marker bez rodzaju i powodu) → myślnik `copy.no_reason`, nie pustka:
    # „nie wiem, dlaczego" jest faktem, a pusta komórka czyta się jak brak danych w kolumnie
    with con:
        con.execute("UPDATE location SET unreadable_kind = NULL, unreadable_reason = NULL "
                    "WHERE id = ?", (loc["id"],))
    v.refresh()
    _select_review_tag(v, "unreadable")
    assert v.frames.item(0, 4).text() == "—"
    assert not v.frames.item(0, 4).toolTip()
    # wybór obiektu → powrót do tabeli klatek (tryb „kopie" znika)
    _select_object_canon(v, "NGC7000")
    hdrs = [v.frames.horizontalHeaderItem(c).text() for c in range(v.frames.columnCount())]
    assert hdrs == ["sha1 danych", "Teleskop", "Kamera", "Filtr", "Data", "Obecny", "Ścieżka"]
    assert v.frames.rowCount() == 5
    assert hh.maximumSectionSize() > COPY_PATH_MAX_PX       # sufit trybu „kopie" nie przecieka
    assert not isinstance(v.frames.itemDelegateForColumn(COPY_COL_PATH), grid_mod._ElizjaWSrodku)
    # …a ścieżka trybu klatek elizuje w ŚRODKU tym samym delegatem (nazwa pliku zostaje)
    assert isinstance(v.frames.itemDelegateForColumn(FRAME_COL_PATH), grid_mod._ElizjaWSrodku)


def test_kopie_nieczytelne_ze_WSPOLNYM_prefiksem_rozroznia_nazwa_w_komorce(view):
    """Wizytacja na kopii pf4: pięć kopii nieczytelnych pod `R:\\ASTRO_\\STACKS\\…` - komórka
    z pełną ścieżką w sufit 200 px pokazywała pięć razy prawie to samo („R:\\ASTRO_\\STAC…"), bo
    człon rozróżniający kopie siedział w środku, który zjada elizja. W komórce stoi teraz nazwa
    pliku, a pełna ścieżka w podpowiedzi - jak w Duplikatach.

    Falsyfikator: wróć do pełnej ścieżki w komórce `COPY_COL_PATH` → teksty komórek zaczynają się
    od wspólnego prefiksu i asercja o nazwach pada; zdejmij sufit z `_show_copies` → długa nazwa
    rozpycha kolumnę ponad `COPY_PATH_MAX_PX`."""
    v, con, ids = view
    prefiks = r"R:\ASTRO_\STACKS\2026\M31_Andromeda\WBPP_wyniki\master"
    locs = con.execute("SELECT id, frame_id FROM location ORDER BY id LIMIT 2").fetchall()
    sciezki = [prefiks + r"\masterLight_A_integration.xisf",
               prefiks + r"\masterLight_BIN-1_8000x5320_EXPOSURE-121.00s_FILTER-NoFilter_RGB.xisf"]
    for loc, sciezka in zip(locs, sciezki):
        with con:
            con.execute("UPDATE location SET path = ? WHERE id = ?", (sciezka, loc["id"]))
        sha = con.execute("SELECT sha1_data FROM frame WHERE id = ?", (loc["frame_id"],)).fetchone()[0]
        repo.refresh_location_unreadable(con, location_id=loc["id"], sha1_data=sha, path=sciezka,
                                         mtime="t2", reason="ParseError: y", kind="parse",
                                         now="2026-07-21T12:00:00")
    v.refresh()
    _select_review_tag(v, "unreadable")
    komorki = {v.frames.item(r, COPY_COL_PATH).text(): v.frames.item(r, COPY_COL_PATH).toolTip()
               for r in range(v.frames.rowCount())}
    assert komorki == {"masterLight_A_integration.xisf": sciezki[0],
                       "masterLight_BIN-1_8000x5320_EXPOSURE-121.00s_FILTER-NoFilter_RGB.xisf":
                           sciezki[1]}, komorki
    from horreum.gui import grid as grid_mod
    hh = v.frames.horizontalHeader()
    assert hh.sectionSize(COPY_COL_PATH) <= COPY_PATH_MAX_PX
    assert isinstance(v.frames.itemDelegateForColumn(COPY_COL_PATH), grid_mod._ElizjaWSrodku)


def test_przeglad_obiektow_nadmiar_szerokosci_bierze_prawy_panel(view, qapp):
    """Wizytacja przy 1400 px: splitter dzielił nadmiar 2:3, więc biblioteka (trzy wąskie kolumny)
    zostawiała za sobą pusty pas, a panel kopii obok ucinał „Powód". Nadmiar bierze teraz prawy
    panel, a w bibliotece resztę szerokości - kolumna nazwy obiektu (bez pustego pasa).

    Pomiar względny, nie w pikselach (szerokości zależą od fontu platformy): przyrost szerokości
    okna trafia w całości do prawego panelu, a kolumny biblioteki wypełniają jej viewport.

    Falsyfikator: wróć do `setStretchFactor(0, 2)` / `(1, 3)` → lewy panel rośnie razem z oknem
    i asercja po poszerzeniu pada; zdejmij `Stretch` z kolumny nazwy → za kolumnami biblioteki
    zostaje pusty pas."""
    v, con, ids = view
    v.resize(1400, 800)
    v.show()
    qapp.processEvents()
    try:
        lewy, prawy = v.objects.parentWidget(), v.frames.parentWidget()
        lewy_przed, prawy_przed = lewy.width(), prawy.width()
        przyrost = 400
        v.resize(1400 + przyrost, 800)
        qapp.processEvents()
        assert lewy.width() == lewy_przed, "nadmiar poziomu poszedł do biblioteki"
        assert prawy.width() - prawy_przed == przyrost, (prawy_przed, prawy.width())
        oh = v.objects.horizontalHeader()
        assert oh.length() >= v.objects.viewport().width() - 1, "pusty pas za kolumnami biblioteki"
    finally:
        v.hide()


@pytest.mark.parametrize("lang", ["pl", "en"])
@pytest.mark.parametrize("kind, reason, klucz", [
    ("io", "OSError: [Errno 5] Input/output error", "copy.reason_io"),
    ("parse", "ParseError: line 4", "copy.reason_parse"),
    ("db", "OperationalError: database is locked", "copy.reason_db"),
    (None, "ParseError: line 4", None),          # rodzaj nieznany → sama diagnoza
    (None, None, None),                          # nic nie wiadomo → myślnik
    ("io", None, "copy.reason_io"),              # rodzaj bez diagnozy → myślnik w miejscu opisu
], ids=["io", "parse", "db", "bez_rodzaju", "bez_niczego", "rodzaj_bez_diagnozy"])
def test_komorka_powod_mowi_KTORA_to_sytuacja_PL_i_EN(kind, reason, klucz, lang):
    """P4-2: `_copy_reason` - jedyny właściciel komórki „Powód" - stawia RODZAJ przed diagnozą, bo
    to on mówi, gdzie szukać winy (dysk/dostęp → plik może być zdrowy; parser → plik do
    zgłoszenia; baza danych → błąd po naszej stronie). Brak rodzaju (rodzaj nieznany: wiersz sprzed
    0019 albo wyjątek bez kodu systemu) → sama diagnoza; brak obu → myślnik; rodzaj bez diagnozy
    nie znika.

    Każda gałąź w OBU językach, a oczekiwany tekst idzie z WPISU katalogu dla tego języka
    (`CATALOG[klucz][lang]`), nie z literału i nie przez `i18n.t`: ten spada na PL, gdy wpisu EN
    brak, więc porównanie z nim byłoby zielone dokładnie wtedy, gdy EN jest dziurawy. Do tej
    poprawki EN sprawdzał tylko `io` i `parse`.

    Falsyfikator: zdejmij `en` z `copy.no_reason` albo `copy.reason_db` → odpowiedni wariant EN
    czerwienieje (`KeyError` na wpisie); wróć do `_copy_reason(raw)` bez rodzaju → komórka mówi
    samą diagnozę i warianty z kluczem czerwienieją; zdejmij gałąź `'db'` → wariant `db` dostaje
    samą diagnozę."""
    from horreum.gui.app import _copy_reason
    from horreum.gui.i18n_catalog import CATALOG
    i18n.set_lang(lang)
    diagnoza = reason if reason is not None else CATALOG["copy.no_reason"][lang]
    oczekiwane = CATALOG[klucz][lang].format(reason=diagnoza) if klucz else diagnoza
    if klucz:                                  # etykieta rodzaju naprawdę stoi przed diagnozą
        assert oczekiwane.endswith(diagnoza) and oczekiwane != diagnoza
    assert _copy_reason(kind, reason) == oczekiwane


def test_wiersz_kopii_nieczytelnych_podpowiada_rozbicie_po_rodzaju(view):
    """P4-2: wiersz kubełka „kopie nieczytelne" z drogą niesie w podpowiedzi rozbicie PO KOPIACH
    na rodzaje - sama liczba klatek nie mówiła, czy szukać winy w dysku, czy w pliku. Pusty kubełek
    zostaje przy swoim zdaniu informacyjnym (rozbijać nie ma czego).

    Falsyfikator: usuń `tip=` z wołania `_add_review_item` dla tego kubełka (albo `setToolTip(tip)`
    w gałęzi z tagiem) → podpowiedź wiersza jest pusta i asercja czerwienieje."""
    v, con, ids = view
    v._load_review()
    pusty = next(v.review.item(r) for r in range(v.review.count())
                 if "kopie nieczytelne" in v.review.item(r).text())
    assert pusty.toolTip() == i18n.t("object.unreadable_info_empty")
    locs = con.execute("SELECT id, path FROM location WHERE frame_id = ? ORDER BY id",
                       (ids["frames"]["a1"],)).fetchall()
    repo.refresh_location_unreadable(con, location_id=locs[0]["id"], sha1_data="sha-a1",
                                     path=locs[0]["path"], mtime="t2", reason="OSError: x",
                                     kind="io", now="2026-07-21T12:00:00")
    repo.refresh_location_unreadable(con, location_id=locs[1]["id"], sha1_data="sha-a1",
                                     path=locs[1]["path"], mtime="t2", reason="ParseError: y",
                                     kind="parse", now="2026-07-21T12:00:00")
    v._load_review()
    r = _select_review_tag(v, "unreadable")
    assert v.review.item(r).toolTip() == "kopie: dysk/dostęp 1 · nagłówek 1"
    assert v.review.item(r).data(SECONDARY).startswith("1")      # licznik wiersza = KLATKI


def test_podpowiedz_kopii_nieczytelnych_liczy_blad_bazy_OSOBNO(view):
    """P4-2 (F1): błąd bazy po naszej stronie (`'db'`) ma własny człon podpowiedzi, pokazywany jak
    „rodzaj nieznany" tylko przy liczbie > 0. Wpadnięcie do rodzajów plikowych kazałoby szukać winy
    w pliku, a do „nieznanego" - ukryłoby, że wiadomo, co zawiodło.

    Falsyfikator: zdejmij człon `'db'` z `pipeline.unreadable_kinds_text` → podpowiedź nie ma „baza 1"
    i asercja czerwienieje."""
    v, con, ids = view
    loc = con.execute("SELECT id, path FROM location WHERE frame_id = ? ORDER BY id",
                      (ids["frames"]["a1"],)).fetchone()
    repo.refresh_location_unreadable(con, location_id=loc["id"], sha1_data="sha-a1",
                                     path=loc["path"], mtime="t2",
                                     reason="OperationalError: database is locked", kind="db",
                                     now="2026-07-21T12:00:00")
    v._load_review()
    r = _select_review_tag(v, "unreadable")
    assert v.review.item(r).toolTip() == "kopie: dysk/dostęp 0 · nagłówek 0 · baza 1"


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
        assert hdrs == ["Object", "Catalog", "Frames", "Hours"]
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


def test_zdanie_podpowiedzi_ROZNE_dla_drzewa_STACKS_i_ukladu_WBPP():
    """Tooltip `⟨…⟩` mówi prawdę o SWOIM układzie: w drzewie `STACKS` folder niesie nazwę i jest
    droga potwierdzenia ze ścieżki, w układzie WBPP nazwy nie niesie nic (zdanie bez zmian). Belka
    grupy mieszającej oba układy milczy, bo żadne z dwóch zdań nie jest prawdą o całej grupie.

    Scenariusz jedzie przez politykę komórki (`queries.object_cell`) i wybór zdania gridu."""
    from horreum.gui import grid
    stos = {"kind": "master_light", "object_canon": None, "object_raw": None,
            "path": r"R:\ASTRO_\STACKS\vdB30\A140R_2600MM\G\vdB30_G.xisf"}
    wbpp = {"kind": "master_light", "object_canon": None, "object_raw": None,
            "path": r"R:\ARCHIWUM\vdB30\master\masterLight_BIN-1.xisf"}
    assert queries.object_cell(stos) == queries.object_cell(wbpp) == ("⟨vdB30⟩", "hint")
    assert grid._object_tip(stos, "hint") == i18n.t("grid.cell.object_hint_stacks_tip")
    assert grid._object_tip(wbpp, "hint") == i18n.t("grid.cell.object_hint_tip")
    assert "Zatwierdź ze ścieżki" in i18n.t("grid.cell.object_hint_stacks_tip")
    model = grid.GridTableModel.__new__(grid.GridTableModel)
    assert model._group_tip_mode([stos, dict(stos)], "hint") == "exact"
    assert model._group_tip_mode([stos, wbpp], "hint") is None
    assert model._group_tip_mode([wbpp], "hint") == "exact"


def _stary_podzial(con, rows):
    """Reguła `_split_rows` SPRZED drzewa stosów, przepisana znak w znak - świadek niezależny dla
    bramki niżej. Grupuje po RODZICU pliku i pyta `path_proposal` BEZ rodzaju."""
    import os as _os
    from horreum import macro as macro_mod
    targets = {}
    for t in queries.writeback_frame_targets(con, [r["frame_id"] for r in rows]):
        targets.setdefault(int(t["frame_id"]), []).append(t)
    groups, skipped = {}, []
    for r in rows:
        trows = targets.get(int(r["frame_id"]))
        if not trows:
            skipped.append((r["path"] or "", i18n.t("repair.skip.gone")))
            continue
        target, reason = macro_mod.resolve_target(trows)
        if target is None:
            skipped.append((r["path"] or "", reason or ""))
            continue
        groups.setdefault(_os.path.dirname(target["path"]), []).append(
            dict(frame_id=r["frame_id"], path=target["path"]))
    out = []
    for folder, items in groups.items():
        proposals = {resolver.path_proposal(con, it["path"]) for it in items}
        out.append((folder, items, proposals.pop() if len(proposals) == 1 else None))
    return out, skipped


def test_naprawa_LIGHTOW_bez_zmian_co_do_bajtu(repair):
    """Grupowanie stosu po folderze obiektu nie ma prawa ruszyć lightów: grupy (folder, wiersze,
    propozycja) i lista pominiętych są IDENTYCZNE jak przy regule sprzed zmiany. Wiersz RAW-owy
    (format bez karty) odpada przed grupowaniem - też tak samo jak przedtem."""
    v, con, files, _open = repair
    raw_id, _ = repo.upsert_frame(con, sha1_data="sha-raw-pd", kind="light", filetype="raw",
                                  camera_id=None, now=NOW_PD)
    repo.record_header(con, frame_id=raw_id, raw_json="{}", object_raw=None, now=NOW_PD)
    repo.add_location(con, frame_id=raw_id, volume="V", header_hash="h-raw", now=NOW_PD,
                      path=str(files[0].parent / "_7R38821.ARW"))
    wiersze = list(queries.nameless_frames(con)) + list(queries.nameless_raw_frames(con))
    stare_grupy, stare_pominiete = _stary_podzial(con, wiersze)
    from horreum.gui.app import RepairHeaderDialog
    dlg = RepairHeaderDialog(con, rows=wiersze, db_path=queries.db_path_of(con),
                             now_fn=lambda: NOW_PD, parent=v)
    try:
        assert [(g["folder"], g["rows"], g["proposal"]) for g in dlg._groups] == stare_grupy
        assert dlg._skipped == stare_pominiete and len(stare_pominiete) == 1
        assert stare_grupy[0][2] == "NGC7635"              # dwaj zgodni świadkowie, jak przedtem
    finally:
        dlg.reject()


def _stos_pd(con, sha, path):
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="master_light", filetype="xisf",
                               camera_id=None, now=NOW_PD)
    repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=None, now=NOW_PD)
    repo.add_location(con, frame_id=fid, volume="V", header_hash=f"h-{sha}", now=NOW_PD, path=path)
    return fid


def test_naprawa_STOSU_grupuje_po_folderze_OBIEKTU_z_propozycja(qapp, tmp_path):
    """FC-4 w oknie „Napraw nagłówek…": w `STACKS\\<OBIEKT>\\<KONFIG>\\<FILTR>\\plik` rodzicem jest
    FILTR, więc trzy stosy vdB30 dawały trzy grupy `Ha`/`OIII`/`SII` bez propozycji. Teraz: jedna
    grupa pod folderem obiektu, etykieta `vdB30`, propozycja z DWÓCH zgodnych świadków (folder po
    `STACKS` + człon nazwy pliku) - ta sama reguła co u lightów. Układ WBPP (poza `STACKS`) zostaje
    przy rodzicu i bez propozycji."""
    from horreum.gui.app import RepairHeaderDialog
    con = db.open_db(str(tmp_path / "st.db"))
    R = r"R:\ASTRO_\STACKS\vdB30\A140R_2600MM"
    for filtr in ("Ha", "OIII", "SII"):
        _stos_pd(con, f"st-{filtr}", rf"{R}\{filtr}\vdB30_2026-03-06_A140R_2600MM_{filtr}_5s_mono.xisf")
    wbpp = r"R:\ARCHIWUM\A7R3_105_LMC\master"
    _stos_pd(con, "st-wbpp", rf"{wbpp}\masterLight_BIN-1_6024x4024_EXPOSURE-60.00s.xisf")
    dlg = RepairHeaderDialog(con, rows=queries.nameless_stack_frames(con),
                             db_path=queries.db_path_of(con), now_fn=lambda: NOW_PD)
    try:
        grupy = {g["folder"]: (len(g["rows"]), g["proposal"]) for g in dlg._groups}
        assert grupy == {r"R:\ASTRO_\STACKS\vdB30": (3, "vdB30"), wbpp: (1, None)}
        etykieta = next(g["check"].text() for g in dlg._groups
                        if g["folder"] == r"R:\ASTRO_\STACKS\vdB30")
        assert "vdB30" in etykieta and "Ha" not in etykieta
    finally:
        dlg.reject()
        con.close()


def test_kolumna_sciezki_pokazuje_SCIEZKE_bo_nazwa_pliku_nie_rozroznia(repair):
    """FIRSTHAND ZDZINIA 0808 — DWA zgłoszenia tej samej klasy: najpierw „nie widzę napisu IC443
    ani LMC" (kubełek stosów), potem „nie widzę ścieżki" (kubełek RAW).

    Kolumna nazywa się „Ścieżka", a pokazywała `basename` — czyli dokładnie to, co w tych
    kubełkach nie niesie tożsamości: `masterLight_BIN-1_….xisf` u stosów i `astro_dsc4198.dng`
    u RAW-ów. Recepta („nazwij ten obraz") była nie do wykonania.

    PIERWSZA NAPRAWA CIĘŁA TO PO `kind='master_light'` z uzasadnieniem „light niesie oznaczenie
    we własnej nazwie" — POMIAR JE OBALIŁ: 703 RAW-y bez obiektu mają nazwy bez oznaczenia,
    a rozróżnia je dopiero para katalogów (3 różne wartości dla samego rodzica, 34 dla dwóch).
    Stąd JEDNA reguła bez gałęzi per rodzaj — i ten test pilnuje OBU populacji naraz, żeby
    zawężenie nie wróciło."""
    v, con, files, _open = repair
    fid, _ = repo.upsert_frame(con, sha1_data="sha-folder-stack", kind="master_light",
                               filetype="xisf", camera_id=None, now=NOW_PD)
    repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=None, now=NOW_PD)
    repo.add_location(
        con, frame_id=fid, volume="V", drive_letter="R",
        path=r"R:\ARCHIWUM\OBIEKTY_DNG\A7R3_105_LMC\master\masterLight_BIN-1.xisf",
        now=NOW_PD)
    v.refresh()

    _select_review_tag(v, "nameless_stacks")
    tekst = v.frames.item(0, FRAME_COL_PATH).text()
    assert "A7R3_105_LMC" in tekst, "katalog jest JEDYNYM rozróżnikiem tych wierszy"
    assert "masterLight_BIN-1.xisf" in tekst, "nazwa pliku nie ma zniknąć, ma dostać kontekst"
    assert "ARCHIWUM" not in tekst, "korzeń archiwum jest wspólny wszystkim — sam szum"

    _select_review_tag(v, "nameless")
    swiatlo = v.frames.item(0, FRAME_COL_PATH).text()
    assert "\\" in swiatlo, "klatka nieba dostaje ogon ścieżki TAK SAMO (pomiar obalił wyjątek)"


# ═════════════════════════ R-S3-1 — CZŁON „COFNIĘTE RĘKĄ" W DWÓCH KUBEŁKACH KARTOWYCH


def _cofnij_reka(con, fid, now):
    """Nazwij klatkę i ZDEJMIJ nazwę — jedyna droga, którą powstaje nagrobek `user_cleared`."""
    repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                            kind="deep_sky", frame_ids=[fid], now=now)
    assert repo.clear_object_assignment(con, frame_ids=[fid], now=now).assigned == 1
    return fid


class _StubNaprawa:
    """Podstawka pod `RepairHeaderDialog` — łapie LISTĘ, na której okno zostało otwarte.

    Pytanie bramki brzmi „którą populację user zobaczy", a nie „czy okno się otworzyło": defekt
    siedzi w wyborze wejścia, a okno wygląda tak samo dla obu połówek."""

    class _Sygnal:
        def connect(self, _):
            pass

    def __init__(self, con, *, rows, **kwargs):
        _StubNaprawa.rows = rows
        self.changed = self.busy_changed = _StubNaprawa._Sygnal()

    def exec(self):
        return 0


def test_polowka_cofnieta_lightow_drazy_i_NAPRAWIA_wlasna_liste(repair, monkeypatch):
    """R-S3-1, człon wykonawczy: kubełek „bez nazwy w nagłówku" rozszczepia się po źródle — a okno
    naprawy otwiera się na TEJ POŁÓWCE, którą user kliknął.

    Bez członu `cleared` w `_on_repair` kliknięcie w „cofnięte ręką" otwierało okno z populacją
    NIETKNIĘTĄ: listą ROZŁĄCZNĄ z tą, którą user widział pod spodem — i to akcją, która pisze
    do PLIKÓW archiwum. To ta sama klasa co defekt stosów wyżej („user kliknął jeden licznik,
    poprawił inną populację"), tylko druga oś tego samego wyboru.

    Falsyfikator: przywróć w `_on_repair` `cleared=False` → `_StubNaprawa.rows` niesie klatkę
    nietkniętą zamiast cofniętej i obie ostatnie asercje czerwienieją."""
    v, con, files, _open = repair
    wszystkie = [r["frame_id"] for r in queries.nameless_frames(con)]
    assert len(wszystkie) == 2
    cofniety = _cofnij_reka(con, wszystkie[0], NOW_PD)
    nietkniety = wszystkie[1]
    v.refresh()

    q = queries.review_queue(con)
    assert (q["nameless_count"], q["nameless_cleared_count"]) == (1, 1)
    _select_review_tag(v, "nameless_cleared")
    assert v.frames.rowCount() == 1                     # drążenie po PARZE, nie unia obu połówek
    assert [r["frame_id"] for r in queries.nameless_frames(con, cleared=True)] == [cofniety]
    # Kubełek naprawiany KARTĄ zostaje kartowy także w połówce cofniętej: writeback gasi nagrobek,
    # więc przycisk jest aktywny, a ręka (droga kubełka RAW) — nie jego drogą.
    assert v.repair_btn.isEnabled() and not v.assign_btn.isEnabled()

    monkeypatch.setattr("horreum.gui.app.RepairHeaderDialog", _StubNaprawa)
    v._on_repair()
    assert [r["frame_id"] for r in _StubNaprawa.rows] == [cofniety]
    assert nietkniety not in [r["frame_id"] for r in _StubNaprawa.rows]


def test_BLIZNIACZE_kubelki_cofniete_tez_maja_znacznik(repair):
    """FIRSTHAND 0810, znalezisko 2: trzy z czterech rodzin kubełków dostały tylko DWA sygnały.

    Etykieta połówki cofniętej jest DOSŁOWNIE tym samym zdaniem, co etykieta nietkniętej
    (`object.nameless_line` ≡ `object.nameless_cleared_line`), więc bez `↺` na początku dwa
    sąsiednie wiersze różnią się wyłącznie kolorem i adnotacją w trzeciej kolumnie — czyli tam,
    gdzie wzrok trafia ostatni, a obcięcie pierwszy. Znacznik `↺` miała do dziś wyłącznie pętla
    `object_review`.

    Wcięcia te wiersze NIE dostają i to jest różnica wobec tamtej pętli: są bliźniakami
    w partycji, a nie połówkami jednej nazwy — nie ma czego podwieszać.

    Falsyfikator: zdejmij `_ZNACZNIK` z któregokolwiek z trzech wywołań → jego asercja pada."""
    v, con, files, _open = repair
    _cofnij_reka(con, [r["frame_id"] for r in queries.nameless_frames(con)][0], NOW_PD)
    # DWA stosy, bo porównujemy etykiety obu połówek: wiersz nietknięty znika przy zerze (QUIET),
    # a wtedy test nie miałby z czym zestawić bliźniaka.
    for sha, cofnij in (("sha-stack-swiezy-znacznik", False), ("sha-stack-cofniety-znacznik", True)):
        fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="master_light",
                                   filetype="xisf", camera_id=None, now=NOW_PD)
        repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=None, now=NOW_PD)
        if cofnij:
            _cofnij_reka(con, fid, NOW_PD)
    v.refresh()

    # TRZECIA rodzina - RAW (`resolver.NO_OBJECT_CARD_FILETYPES`). Bez niej falsyfikator tego testu
    # był NIEPRAWDZIWY: docstring obiecywał „któregokolwiek z trzech wywołań", a pętla brała dwa
    # (bramka pakietu 0810, zarzut 3 - obietnica pokrycia szersza niż pokrycie).
    for sha, cofnij in (("sha-raw-swiezy-znacznik", False), ("sha-raw-cofniety-znacznik", True)):
        fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="light", filetype="raw",
                                   camera_id=None, now=NOW_PD)
        repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=None, now=NOW_PD)
        if cofnij:
            _cofnij_reka(con, fid, NOW_PD)
    v.refresh()

    for tag in ("nameless_cleared", "nameless_stacks_cleared", "nameless_raw_cleared"):
        it = v.review.item(_select_review_tag(v, tag))
        nietknieta = v.review.item(_select_review_tag(v, tag.replace("_cleared", "")))
        assert it.text().startswith("↺"), f"{tag}: brak znacznika na POCZĄTKU wiersza"
        assert not it.text().startswith(" "), f"{tag}: bliźniak nie jest podwierszem — bez wcięcia"
        assert it.text().lstrip("↺ ") == nietknieta.text(),             f"{tag}: etykiety przestały być tym samym zdaniem — test mierzy już co innego"


def test_polowka_cofnieta_gotowych_stosow_ma_WLASNY_wiersz_i_wlasna_liste(repair, monkeypatch):
    """R-S3-1 na czwartym kubełku — i to NIE jest droga hipotetyczna: D-OW-7 wpuściło gest osi
    obiektu na gotowy obraz, więc cofnięcie na stosie jest jednym kliknięciem.

    Dwa stosy, jeden cofnięty: wiersze muszą być dwa, a każdy drążyć do SWOJEJ klatki. Do R-S3-1
    oba siedziały w jednym wierszu, więc werdykt człowieka wyglądał jak brak wiedzy."""
    v, con, files, _open = repair
    stosy = []
    for sha in ("sha-stack-fresh", "sha-stack-cleared"):
        fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="master_light", filetype="xisf",
                                   camera_id=None, now=NOW_PD)
        repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=None, now=NOW_PD)
        stosy.append(fid)
    swiezy, cofniety = stosy[0], _cofnij_reka(con, stosy[1], NOW_PD)
    v.refresh()

    q = queries.review_queue(con)
    assert (q["nameless_stacks_count"], q["nameless_stacks_cleared_count"]) == (1, 1)
    _select_review_tag(v, "nameless_stacks")
    assert [r["frame_id"] for r in queries.nameless_stack_frames(con)] == [swiezy]
    _select_review_tag(v, "nameless_stacks_cleared")
    assert v.frames.rowCount() == 1
    assert [r["frame_id"] for r in queries.nameless_stack_frames(con, cleared=True)] == [cofniety]

    # …a okno naprawy dostaje STOS, nie lighta archiwum: wybór idzie po PARZE (populacja, źródło),
    # więc pomyłka na którejkolwiek osi otwiera cudzą listę.
    monkeypatch.setattr("horreum.gui.app.RepairHeaderDialog", _StubNaprawa)
    v._on_repair()
    assert [r["frame_id"] for r in _StubNaprawa.rows] == [cofniety]


def test_wiersz_cofnietych_MOWI_co_stanie_sie_z_werdyktem(repair):
    """R-S3-1 / doktryna repo „wygaszony przycisk tłumaczy się sam" — tu w wariancie trudniejszym:
    przycisk jest AKTYWNY, a mimo to musi się wytłumaczyć.

    Nad wierszem „cofnięte ręką" user widzi aktywne „Napraw nagłówek…" i ma prawo nie wiedzieć,
    czy zapis uszanuje jego werdykt, czy go zdepcze. Recepta ma to powiedzieć WPROST, i musi być
    INNA niż recepta połówki nietkniętej — inaczej dwa różne stany dostają jedno zdanie."""
    from horreum.gui import i18n
    v, con, files, _open = repair
    wszystkie = [r["frame_id"] for r in queries.nameless_frames(con)]
    _cofnij_reka(con, wszystkie[0], NOW_PD)
    v.refresh()

    _select_review_tag(v, "nameless")
    tip_nietkniety = v.repair_btn.toolTip()
    _select_review_tag(v, "nameless_cleared")
    tip_cofniety = v.repair_btn.toolTip()

    assert tip_cofniety.strip() and tip_cofniety != tip_nietkniety
    assert tip_cofniety != i18n.t("repair.tip_pick")     # nie recepta „nic nie wybrano"
    assert "cofnięcie" in tip_cofniety or "zdjąłeś" in tip_cofniety

    # …a przycisk zostaje aktywny nad OBIEMA połówkami: droga naprawy jest ta sama, różni się
    # tylko zdanie, którym się tłumaczy. Fixture ma dwie klatki, jedna poszła pod nagrobek — więc
    # połówka nietknięta liczy JEDNĄ (gdyby liczyła dwie, rozszczepienie by nie działało).
    _select_review_tag(v, "nameless")                  # ten sam przycisk, druga populacja
    assert v.frames.rowCount() == 1 and v.repair_btn.isEnabled()


def test_propozycja_z_dwoch_swiadkow_i_domyslne_zaznaczenie(repair):
    """D-PD-2: folder po `LIGHTS` i nazwa pliku mówią to samo → pole wypełnione, grupa ZAZNACZONA
    (bez tego obietnica „≤ 4 interakcje" jest nieprawdziwa). Podgląd pokazuje DOKŁADNIE to, co
    pójdzie do pliku - z `repr`. Od Q6 (2026-09-26) to FORMA NAGŁÓWKA kanonu (`NGC 7635`), a pole
    edycji dalej pokazuje propozycję ze ścieżki."""
    v, con, files, _open = repair
    dlg = _open()
    assert len(dlg._groups) == 1                      # jeden folder = jedna grupa, dwie klatki
    g = dlg._groups[0]
    assert g["edit"].text() == "NGC7635" and g["check"].isChecked()
    assert g["preview"].text() == "do pliku: OBJECT = 'NGC 7635'"
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
    """D-PD-4: kolejność `strip` → `catalog_canon` → `xref` → `header_form` → bramki. Do pliku
    idzie FORMA NAGŁÓWKA kanonu Horreum (Q6 2026-09-26, D-PD-9 odwrócone: `M 42` → `NGC 1976`),
    nigdy surowy segment; nie-ASCII, przepełnienie rekordu i nazwa nierozpoznawalna przez resolver
    są ODMOWĄ (zero zapisu), nie 'failed' po commicie."""
    from horreum.gui.app import _validate_object_value as val
    v, con, files, _open = repair
    assert val(con, "  ngc 7635 ")[0] == "NGC 7635"          # forma nagłówka PRZED zapisem
    assert val(con, "M 42")[0] == "NGC 1976"                 # po `xref` (NGC-wins), ze spacją
    assert val(con, "M82")[0] == "NGC 3034"                  # folder `M82` → karta `NGC 3034`
    assert val(con, "Sh2 131")[0] == "Sh2-131"               # dywiz jest częścią oznaczenia
    assert val(con, "")[1] and val(con, "   ")[1]            # pusto
    assert val(con, "Mgławica Serce")[1]                     # nie-ASCII
    assert val(con, "NGC" + "7" * 70)[1]                     # dłuższe niż rekord nagłówka
    assert val(con, "Wesolinka Kosmiczna 7")[1]              # ani katalog, ani znana nazwa
    # D2: nazwa zwyczajowa, którą resolver ZNA, idzie jako forma nagłówka kanonu (jedna wersja
    # na obiekt), a nazwa po polsku ze słownika własnego zdejmuje przy okazji znak spoza ASCII
    assert val(con, "Bubble Nebula")[0] == "NGC 7635"
    assert val(con, "Wielki Obłok Magellana")[0] == "LMC"


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
    assert val(con, "C/2023 A3")[0] == "C/2023 A3 (Tsuchinshan-ATLAS)"   # kometa → kanon (D2)
    assert val(con, "WR134")[0] == "WR134"                   # szczebel SŁOWNIKA (S1) — bez nauki
    assert val(con, "Zupelnie Wymyslona 77")[1]              # nieznana NIKOMU → odmowa
    oid, _ = repo.upsert_object(con, canon="ZW77", catalog=None, kind="deep_sky", now=NOW_PD)
    repo.add_object_alias(con, alias_norm="ZUPELNIEWYMYSLONA77", object_id=oid, source="user",
                          now=NOW_PD)
    # user nauczył → przejdzie; kanon `ZW77` z własnego zapisu NIE wraca (zna go tylko alias),
    # więc do pliku idzie tekst usera, nie kanon (`forma_karty_object` → None)
    assert val(con, "Zupelnie Wymyslona 77")[0] == "Zupelnie Wymyslona 77"
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
    assert [fits.getheader(str(p))["OBJECT"] for p in files] == ["NGC 7635", "NGC 7635"]
    after = con.execute(
        "SELECT f.id, f.sha1_data, h.object_raw, f.object_id FROM frame f "
        "JOIN header h ON h.frame_id = f.id").fetchall()
    assert {r["id"]: r["sha1_data"] for r in after} == before      # tożsamość przeżyła zapis
    assert {r["object_raw"] for r in after} == {"NGC 7635"}        # zeznanie odświeżone re-syncem
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


def test_propozycja_STOSU_ma_wiersz_pod_stosami_i_wlasna_populacje(sciezka):
    """E3-1: stos z drzewa `STACKS` bez `OBJECT` dostaje wiersz „…z tego ze ścieżki" POD kubełkiem
    stosów, z liczbą WYŁĄCZNIE swojej populacji. Ten sam tag i ta sama akcja co pod RAW-em; payload
    rozdziela drążenie i okno, więc żaden wiersz nie otwiera klatek drugiej populacji."""
    from horreum.gui.app import PATH_STACKS_PAYLOAD, path_proposals_for
    v, con = sciezka
    fid, _ = repo.upsert_frame(con, sha1_data="sha-stos", kind="master_light", filetype="xisf",
                               camera_id=None, now=NOW_S2)
    repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=None, now=NOW_S2)
    repo.add_location(con, frame_id=fid, volume="V", now=NOW_S2,
                      path=rf"{R_S2}\STACKS\LMC\A7R3_105\OSC\LMC_stack.xisf")
    v.refresh()

    wiersze = [(v.review.item(r).data(UROLE), r) for r in range(v.review.count())]
    stos_r = [r for tag, r in wiersze if tag == "nameless_stacks"]
    prop_r = [r for tag, r in wiersze if tag == "path_proposals"]
    assert len(stos_r) == 1 and len(prop_r) == 2, "jeden wiersz propozycji pod KAŻDYM kubełkiem"
    assert prop_r[1] > stos_r[0], "propozycja stosu stoi pod kubełkiem stosów"

    v.review.setCurrentRow(prop_r[1])
    assert v._selected_review() == ("path_proposals", PATH_STACKS_PAYLOAD)
    assert v.confirm_path_btn.isEnabled()
    assert v.frames.rowCount() == 1                       # drążenie: sam stos, bez RAW-ów
    assert [p.frame_ids for p in path_proposals_for(con, PATH_STACKS_PAYLOAD)] == [(fid,)]

    v.review.setCurrentRow(prop_r[0])
    assert v.frames.rowCount() == 3                       # RAW-owy wiersz bez zmian: 3 klatki LMC
    assert all(not p.stack_tree for p in path_proposals_for(con, None))


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
    ścieżka nie domknie. (Zdanie bez kropki - R-S2b-13, człony rozbicia doklejają się „ · …".)"""
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
    assert msgs[-1] == "Przypisano 4 z 4 klatek → LMC"
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


def test_akcja_kubelka_cofnietych_gasi_nagrobek_PRZEZ_SLOT_nie_obok_niego(sciezka, monkeypatch):
    """PIN JEDYNEJ PRODUKCYJNEJ LINII NAPRAWY R-S2b-1 (`overwrite_weak=cofniete`, `gui/app.py`).

    Bramka obok woła klingę WPROST z `overwrite_weak=True`, więc dowodzi tylko tego, że klinga
    umie nadpisać nagrobek — a defekt siedział w POWIERZCHNI: to `_on_assign` nie podawał tego
    kwargu. Usunięcie go z `app.py` zostawiało tamtą bramkę zieloną. To ta sama klasa, którą
    kolejka trzyma jako lekcję STANDING: „bramka pyta klingę, defekt siedzi w powierzchni".

    Falsyfikator: skasuj `overwrite_weak=cofniete` z `gui/app.py` → komunikat spada na
    „Przypisano 0 z 2" i asercja stanu bazy czerwienieje. (Zdanie bez kropki - R-S2b-13.)"""
    v, con = sciezka

    class AcceptedNGC:
        selected = ("NGC7000", "NGC", "deep_sky", None)

        def __init__(self, *args, **kwargs):
            AcceptedNGC.seen = kwargs

        def exec(self):
            return QDialog.Accepted

    ids = [r["frame_id"] for r in queries.nameless_raw_frames(con)][:2]
    repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                            kind="deep_sky", frame_ids=ids, now=NOW_S2)
    repo.clear_object_assignment(con, frame_ids=ids, now=NOW_S2)
    v._load_review()

    monkeypatch.setattr("horreum.gui.app.AssignObjectDialog", AcceptedNGC)
    _select_review_tag(v, "nameless_raw_cleared")
    v._select_all_frames()
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_assign()

    # SKUTEK W BAZIE, nie „slot się wykonał": nagrobek zgasł i klatki mają obiekt.
    assert msgs[-1] == "Przypisano 2 z 2 klatek → NGC7000"
    assert con.execute(
        "SELECT count(*) FROM frame WHERE id IN (?,?) AND object_id IS NOT NULL "
        "AND object_source = 'user'", ids).fetchone()[0] == 2
    assert queries.review_queue(con)["nameless_raw_cleared_count"] == 0
    # …i OKNO o tym uprzedziło, zanim user kliknął (ostrzeżenie na drodze kliknięcia, nie w tooltipie)
    assert AcceptedNGC.seen["cleared_n"] == 2


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


def test_przeladowanie_tabeli_nie_jest_kwadratowe(qapp):
    """Przeładowanie tabeli, która JEST zaznaczona w całości, musi zejść z wierszami — nie z
    zaznaczeniem (`_przeladuj_wiersze`).

    Bramka wisi na ZMIERZONEJ szkodzie, nie na stylu. Firsthand 2026-08-04 na kopii żywej `pf4`:
    kliknięcie kubełka RAW (763 klatki) po wcześniejszym drążeniu innego kubełka zajmowało wątek
    GUI na **138 s** (offscreen 57,7 s) i Windows dopisywał oknu „(brak odpowiedzi)". Przyczyna:
    `setRowCount(n)` zostawia stare wiersze i ich zaznaczenie, więc model zaznaczenia przelicza
    zakresy przy każdym z 5341 `setItem`.

    Dwie asercje, bo każda sama by przepuściła inny regres:
      * BRAK ZAZNACZENIA po przeładowaniu — pilnuje, że stare wiersze zeszły;
      * BUDŻET CZASU — pilnuje, że zeszły WŁAŚCIWĄ drogą. `clearSelection()` też zostawia puste
        zaznaczenie, a mierzy **228 s**, czyli gorzej niż brak poprawki: kasowanie zaznaczenia
        z 763 wierszy samo jest kwadratem. Sama asercja strukturalna świeciłaby na to zielono.

    Budżet 10 s przy zmierzonych 0,10 s (naprawione) i 57,7 s (zepsute) — margines ~570×, więc
    wolna maszyna testu nie przewróci, a powrót defektu nie ma jak się przecisnąć."""
    from horreum.gui.app import _przeladuj_wiersze
    import time

    N, KOLUMN, BUDZET_S = 800, 7, 10.0
    t = QTableWidget(0, KOLUMN)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setWordWrap(False)
    fh = t.horizontalHeader()
    fh.setSectionResizeMode(QHeaderView.ResizeToContents)   # jak panel klatek osi obiektu
    t.show()
    qapp.processEvents()

    def wypelnij():
        _przeladuj_wiersze(t, N)
        for r in range(N):
            for c in range(KOLUMN):
                it = QTableWidgetItem(f"{r}-{c}")
                it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                t.setItem(r, c, it)

    wypelnij()
    t.selectAll()                                   # lustro `_select_all_frames` (kubełek z akcją)
    qapp.processEvents()
    assert len(t.selectionModel().selectedRows()) == N, "fikstura nie zaznaczyła całości"

    t0 = time.perf_counter()
    wypelnij()                                      # DRUGIE drążenie — na tabeli zaznaczonej
    dt = time.perf_counter() - t0

    assert not t.selectionModel().selectedRows(), "stare zaznaczenie przeżyło przeładowanie"
    assert t.rowCount() == N
    assert dt < BUDZET_S, f"przeładowanie {N}×{KOLUMN} trwało {dt:.1f} s (budżet {BUDZET_S} s)"
    t.close()


# ═════════════════════════ R-S3-3 / R-S3-10 — WIERSZ KOLEJKI JEST TRÓJCZŁONOWY

NOW_S3 = "2026-08-10T12:00:00Z"


def _wiersz_kolejki(v, tag):
    """Pozycja kolejki o danym tagu jako trójka członów (nazwa, liczba+znacznik, adnotacja)."""
    it = v.review.item(_select_review_tag(v, tag))
    return it.text(), (it.data(SECONDARY) or ""), (it.data(TERTIARY) or "")


def test_polowka_cofnieta_ma_znacznik_NA_POCZATKU_i_kolor(view):
    """R-S3-3: różnicownikiem połówek były DWA SZARE SŁOWA na końcu obcinanej linii.

    Lista obcina poziomo (nie elizją), więc przy wąskim oknie ginęło dokładnie to, co niesie
    znaczenie. Odtąd sygnałów są trzy i wszystkie przeżywają obcięcie: znacznik `↺` na POCZĄTKU,
    kolor werdyktu na CAŁYM wierszu i adnotacja we WŁASNEJ kolumnie (człon trzeci).

    ZMIANA W-5 (wizytacja 0810): przynależność podwiersza do rodzica nie jest już spacjami
    w `DisplayRole` (jechały do schowka/EN i kradły miejsce nazwie przy elizji) - to rola
    `rows.INDENT` (int), którą delegat zamienia na px z metryki fontu. Do W-5 druga asercja
    sprawdzała `nazwa.startswith(" ")`; ta prawda ZNIKNĘŁA (sierota i podwiersz mają identyczny
    `DisplayRole`, różni je wyłącznie dana wcięcia) - zastępuje ją odczyt roli. Pierwsza asercja
    ZAOSTRZONA z `nazwa.lstrip().startswith(...)` na goły `startswith(...)`: `lstrip()` maskowałby
    dokładnie regresję, którą W-5 usuwa (powrót wiodącej spacji w tekście).

    Falsyfikatory: zdejmij `↺` z prefiksu → pierwsza asercja; przestań ustawiać `rows.INDENT` dla
    podwiersza (`_add_review_item(..., indent=0)`) → druga; zdejmij `fg` → czwarta; przenieś
    „cofnięte ręką" z powrotem do tekstu → trzecia."""
    v, con, ids = view
    _cofnij_reka(con, ids["frames"]["objrev1"], NOW_S3)
    v._load_review()

    nazwa, drugi, trzeci = _wiersz_kolejki(v, "object_raw_cleared")
    assert nazwa.startswith("↺"), "znacznik nie stoi na POCZĄTKU wiersza"
    it = v.review.item(_select_review_tag(v, "object_raw_cleared"))
    assert it.data(UINDENT), "podwiersz nie niesie poziomu wcięcia w danych delegata (rows.INDENT)"
    assert "cofnięte ręką" in trzeci and "cofnięte ręką" not in nazwa
    assert "›" in drugi

    swiezy = v.review.item(_select_review_tag(v, "object_raw"))
    assert it.foreground().color() != swiezy.foreground().color(), \
        "połówka cofnięta ma ten sam kolor co nietknięta — werdykt nie jest widoczny"


def test_DWA_OSTATNIE_liczniki_kolejki_tez_sa_odmienione(view):
    """FIRSTHAND 0810, znalezisko 4: R-S3-10 odmieniło sześć wierszy i przeoczyło dwa.

    „— bez nagłówka · 1" i „— kopie nieczytelne · 1" jechały gołym `str(...)`, więc sąsiadowały
    z odmienionym „1 klatka" w tej samej kolumnie — rozjazd widoczny obok siebie.

    JEDNOSTKĄ OBU JEST KLATKA, mimo że drugi kubełek nazywa się od KOPII: `resolver.review_state`
    liczy tam `count(DISTINCT f.id)` (klatki z ≥1 kopią oznaczoną nieczytelną) i robi to
    świadomie — „spójność z resztą liczników". Dlatego klucz jest ten sam, co u sąsiadów, a nie
    własny „N kopii": ten mówiłby o czymś, czego nie policzono.

    Falsyfikator: wróć do `count=str(...)` → obie asercje czerwienieją."""
    from horreum.gui import i18n
    v, con, ids = view
    v._load_review()
    teksty = {v.review.item(r).data(UROLE): (v.review.item(r).data(SECONDARY) or "")
              for r in range(v.review.count())}
    liczby = [v.review.item(r).data(SECONDARY) or "" for r in range(v.review.count())
              if v.review.item(r).data(UROLE) is None]
    q = queries.review_queue(con)
    assert any(i18n.t_plural("object.review_count", q["headerless_count"]) in t for t in liczby),         "wiersz bez nagłówka podaje liczbę bez odmiany"
    assert any(i18n.t_plural("object.review_count", q["unreadable_count"]) in t
               for t in list(liczby) + [teksty.get("unreadable", "")]),         "wiersz kopii nieczytelnych podaje liczbę bez odmiany"


def test_SIEROTA_cofnieta_nie_udaje_podwiersza_obcej_nazwy(view):
    """FIRSTHAND 0810, znalezisko 1 (blokada odbioru): wcięcie było bezwarunkowe.

    Nazwa, której cofnięto WSZYSTKIE klatki, oddaje jeden wiersz `cleared=1` bez połówki
    nietkniętej — a wcięcie podwieszało go wzrokowo pod OBCĄ nazwą stojącą wyżej. Zmierzone
    przez wizytatora na 45 pozycjach: prawdziwe pary DWIE, reszta sierot. To ta sama szkoda,
    przed którą broniło R-S3-2 („user załatwia rodzica i zostawia podwiersz"), tylko wpuszczona
    z drugiej strony — i przypadek CZĘSTSZY od pary, bo gest z kolejki zdejmuje nazwę CAŁEJ
    grupie naraz.

    Sierota traci WYŁĄCZNIE wcięcie: znacznik i kolor zostają, bo werdykt ręki jest faktem
    niezależnym od sąsiedztwa.

    W-5 DOPISEK (wizytacja 0810): wcięcie od W-5 jest rolą `rows.INDENT`, nie tekstem - asercja
    tekstowa niżej zostaje (wciąż prawdziwa: `DisplayRole` nigdy nie niesie wiodącej spacji), ale
    sama w sobie nie łapałaby już regresji „sierota dostała wcięcie", bo tekst sieroty i podwiersza
    są dziś IDENTYCZNE. Dlatego dochodzi asercja o roli - TA jest właściwym falsyfikatorem.

    Falsyfikatory: wróć do bezwarunkowego prefiksu TEKSTEM → druga asercja czerwienieje; wróć do
    bezwarunkowego `indent=1` w `_load_review` (rola zamiast tekstu) → trzecia."""
    v, con, ids = view
    _cofnij_reka(con, ids["frames"]["objrev1"], NOW_S3)
    _cofnij_reka(con, ids["frames"]["objrev2"], NOW_S3)     # ...i druga połowa tej samej nazwy
    v._load_review()

    assert _select_review_tag_or_none(v, "object_raw") is None,         "fikstura nie oddała sieroty — została połówka nietknięta, czyli to dalej para"
    nazwa, _, trzeci = _wiersz_kolejki(v, "object_raw_cleared")
    assert nazwa.startswith("↺"), "znacznik należy się KAŻDEJ cofniętej pozycji"
    assert not nazwa.startswith(" "), "sierota nie ma rodzica na ekranie — wcięcie by go zmyśliło"
    it = v.review.item(_select_review_tag(v, "object_raw_cleared"))
    assert not it.data(UINDENT), "sierota nie ma rodzica na ekranie - rola rows.INDENT (W-5) by go zmyśliła"
    assert "cofnięte ręką" in trzeci


def test_podwiersz_display_role_bez_wiodacych_bialych_znakow(view):
    """W-5: `DisplayRole` podwiersza NIE MOŻE zaczynać się białym znakiem w ŻADNYM języku -
    inaczej wraca dokładnie ten sam dług (kopiuj-wklej ze schowka i wersja EN niosłyby wcięcie
    tekstem, tak jak dawne `app._WCIECIE`). Sprawdzone w PL i EN, bo `i18n.set_lang` przełącza
    WSZYSTKIE stałe renderowane przez `_load_review` - literał wcięcia, gdyby wrócił choćby dla
    jednego języka, jest tu złapany w obu (autouse `_reset_i18n_lang` z `conftest.py` wraca na PL
    po teście).

    Falsyfikator: w `_load_review` wróć do `etykieta = ("        " if podwiersz else "") +
    _etykieta_cofnieta(etykieta)` → obie iteracje pętli czerwienieją na pierwszej asercji."""
    v, con, ids = view
    _cofnij_reka(con, ids["frames"]["objrev1"], NOW_S3)
    for lang in ("pl", "en"):
        i18n.set_lang(lang)
        v._load_review()
        nazwa, _, _ = _wiersz_kolejki(v, "object_raw_cleared")
        assert nazwa == nazwa.lstrip(), \
            f"[{lang}] DisplayRole podwiersza niesie wiodące białe znaki: {nazwa!r}"
        it = v.review.item(_select_review_tag(v, "object_raw_cleared"))
        assert it.data(UINDENT) == 1, \
            f"[{lang}] podwiersz nie niesie poziomu wcięcia w roli rows.INDENT"


def test_BP2_jeden_wlasciciel_glifu_cofniecia(view, monkeypatch):
    """BP-2 (bramka pakietu, wizytacja 0810): znacznik cofnięcia miał DWÓCH właścicieli -
    `queries.CLEARED_MARK` i niezależny literał `app._ZNACZNIK`. Podmiana `queries.CLEARED_MARK`
    MUSI przełożyć się na etykietę kolejki - inaczej `app` wciąż trzyma WŁASNĄ kopię glifu i drugi
    właściciel żyje dalej pod inną nazwą.

    WIĄZANIE MUSI CZYTAĆ `queries.CLEARED_MARK` PRZEZ ATRYBUT MODUŁU w momencie wołania, nie
    importem nazwy: `from horreum.gui.queries import CLEARED_MARK` na poziomie modułu związałby
    wartość PRZED tym monkeypatchem (import kopiuje referencję raz, przy starcie procesu) i ten
    test pozostałby zielony dla ZEPSUTEJ (podwójnej) implementacji - dlatego `app._etykieta_cofnieta`
    woła `queries.CLEARED_MARK`, a `queries` jest zaimportowany jako MODUŁ (`from horreum.gui import
    …, queries, …`), nie jako pojedyncza nazwa.

    Falsyfikator: przywróć w `app.py` niezależny literał (np. `_ZNACZNIK = "↺  "` i użycie go
    zamiast `_etykieta_cofnieta`) → ta asercja czerwienieje, bo etykieta nie widzi podmiany."""
    v, con, ids = view
    monkeypatch.setattr(queries, "CLEARED_MARK", "*")
    _cofnij_reka(con, ids["frames"]["objrev1"], NOW_S3)
    v._load_review()
    nazwa, _, _ = _wiersz_kolejki(v, "object_raw_cleared")
    assert nazwa.startswith("*"), f"etykieta nie widzi podmiany queries.CLEARED_MARK: {nazwa!r}"
    assert "↺" not in nazwa, "stary glif przeżył podmianę - drugi właściciel wciąż żyje"


def test_polowki_tej_samej_nazwy_sasiaduja_w_widoku(view):
    """R-S3-2 na powierzchni: podwiersz stoi ZARAZ POD swoją połówką, nie ekran dalej."""
    v, con, ids = view
    _cofnij_reka(con, ids["frames"]["objrev1"], NOW_S3)
    v._load_review()
    swiezy = _select_review_tag(v, "object_raw")
    cofniety = _select_review_tag(v, "object_raw_cleared")
    assert cofniety == swiezy + 1
    # …i obie połówki mówią o TEJ SAMEJ nazwie (payload), więc sąsiedztwo nie jest przypadkiem
    assert v.review.item(swiezy).data(UPAYLOAD) == v.review.item(cofniety).data(UPAYLOAD)


def test_liczba_klatek_jest_ODMIENIONA(view):
    """R-S3-10: kolejka pisała „NGC7023 · 1 klatek" jedną formą dla każdej liczby.

    Falsyfikator: wróć do `i18n.t(...)` ze stałym „{n} klatek" → forma pojedyncza czerwienieje."""
    from horreum.gui import i18n
    v, con, ids = view
    i18n.set_lang("pl")
    _cofnij_reka(con, ids["frames"]["objrev1"], NOW_S3)      # zostawia 1 klatkę w połówce świeżej
    v._load_review()
    assert "1 klatka" in _wiersz_kolejki(v, "object_raw")[1]
    assert "1 klatka" in _wiersz_kolejki(v, "object_raw_cleared")[1]


# ═════════════════════════ R-S3-6 — DWUKLIK W KOLEJCE ODPALA AKCJĘ POZYCJI


def test_dwuklik_w_pozycje_odpala_JEJ_akcje(view, monkeypatch):
    """R-S3-6: naprawa kubełka kosztowała wędrówkę do rzędu przycisków (6 interakcji → 5).

    Akcja bierze się ze STANU PRZYCISKÓW, nie z własnej mapy tag→akcja: `_sync_assign_enabled`
    jest jej jedynym właścicielem, więc dwuklik nie może się z nim rozjechać.

    Falsyfikator: rozłącz `itemDoubleClicked` → `odpalone` zostaje puste."""
    v, con, ids = view
    odpalone = []
    monkeypatch.setattr(v, "_on_assign", lambda: odpalone.append("assign"))
    v.assign_btn.clicked.disconnect()
    v.assign_btn.clicked.connect(v._on_assign)

    r = _select_review_tag(v, "object_raw")
    assert v.assign_btn.isEnabled(), "fikstura nie ustawiła pozycji z akcją"
    v.review.itemDoubleClicked.emit(v.review.item(r))
    assert odpalone == ["assign"]


def test_dwuklik_w_wiersz_BEZ_DROGI_nie_odpala_akcji_sasiada(view, monkeypatch):
    """Wiersz informacyjny nie jest zaznaczalny, więc dwuklik w niego NIE zmienia zaznaczenia —
    bez jawnego warunku na tagu odpaliłby akcję pozycji zaznaczonej wcześniej."""
    v, con, ids = view
    odpalone = []
    monkeypatch.setattr(v, "_on_assign", lambda: odpalone.append("assign"))
    v.assign_btn.clicked.disconnect()
    v.assign_btn.clicked.connect(v._on_assign)

    _select_review_tag(v, "object_raw")                  # akcja WŁĄCZONA…
    assert v.assign_btn.isEnabled()
    informacyjny = next(v.review.item(i) for i in range(v.review.count())
                        if v.review.item(i).data(UROLE) is None)
    v.review.itemDoubleClicked.emit(informacyjny)        # …ale dwuklik pada w wiersz bez drogi
    assert odpalone == []


# ═════════════════════════ BRAMKA PAKIETU 3a — NAPRAWY PRZYJĘTYCH ZARZUTÓW


def test_KAZDY_wiersz_kolejki_trzyma_liczbe_w_czlonie_DRUGIM(view):
    """Zarzut 2 bramki: R-S3-3 przeniósł licznik tylko dla `object_review`, a `ScrollBarAlwaysOff`
    odebrał poziomy scroll CAŁEJ liście — więc w pozostałych 11 wierszach liczba (często jedyna
    treść) zaczęła się ucinać elizją BEZ drogi powrotu. Naprawa odwrotna do zamierzenia paczki
    była tu gorsza niż stan sprzed niej.

    Falsyfikator: wróć z liczbą do `{n}` w którymkolwiek `*_line` → człon pierwszy znów ją niesie."""
    v, con, ids = view
    for r in range(v.review.count()):
        it = v.review.item(r)
        pierwszy = it.text()
        assert "klatek" not in pierwszy and "klatki" not in pierwszy, \
            f"liczba została w członie ELIDOWANYM: {pierwszy!r}"
        # …a każdy wiersz o niezerowej treści liczbowej ma ją w członie drugim
        if it.data(UROLE) is not None:
            assert (it.data(SECONDARY) or "").strip(), f"wiersz z drogą bez członu drugiego: {pierwszy!r}"


def test_liczby_kubelkow_sa_ODMIENIONE(view):
    """Zarzut 5 bramki: R-S3-10 zamknięto dla JEDNEGO z trzech producentów tej samej listy, więc
    na jednym ekranie stało „1 klatka" nad „1 klatek"."""
    from horreum.gui import i18n
    i18n.set_lang("pl")
    v, con, ids = view
    v._load_review()
    czlony = [(v.review.item(r).data(SECONDARY) or "") for r in range(v.review.count())]
    assert not any("1 klatek" in c for c in czlony), czlony


# ═════════════════════════ R-S2b-13 - JEDNA GRAMATYKA ZDANIA OSI OBIEKTU NA TRZECH POWIERZCHNIACH


def _pozycja(wzor, canon, frame_ids):
    """Pozycja okna zatwierdzania: tożsamość propozycji `wzor`, inny kanon i klatki. Testy niżej
    pytają o ZDANIE i niezmiennik liczb, nie o derywację propozycji (tę pinują testy wyżej)."""
    from dataclasses import replace
    return replace(wzor, canon=canon, frame_ids=tuple(frame_ids))


def test_zatwierdzenie_ze_sciezki_mowi_ROZBICIEM_per_fakt(sciezka):
    """R-S2b-13: okno sumowało ręcznie `assigned` i `skipped`, więc gubiło rozbicie per fakt
    i o KAŻDEJ pominiętej klatce mówiło „pominięte - zajęte między oknem a zapisem", także
    o darku, którego nikt nie zajął. Zdanie niesie teraz te same człony, co gesty Zbiorów.

    Pozycja: trzy lighty LMC, z których jeden dostał obiekt z nagłówka między otwarciem okna
    a zapisem (klinga bez `overwrite_weak` liczy go jako dryf), plus dark - kalibracja obiektu
    nie ma z definicji. Porównujemy KONIEC zdania, bo pytanie brzmi też „czego w nim nie ma".

    Falsyfikator: przywróć w `_on_confirm` ręczną sumę `assigned, skipped` z płaskim ogonem albo
    zdejmij `grid.zdanie_pominiec(gest)` → zdanie traci „kalibracja: 1" i „zmieniły się
    w międzyczasie: 1"."""
    v, con = sciezka
    con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
                "VALUES (10, 'dark', 'raw', 'sha10', ?)", (NOW_S2,))
    con.commit()
    lmc = next(p for p in resolver.path_proposals(con) if p.canon == "LMC")
    dlg = ConfirmPathObjectsDialog(con, proposals=[_pozycja(lmc, "LMC", lmc.frame_ids + (10,))],
                                   now_fn=lambda: NOW_S2, parent=v)
    oid, _ = repo.upsert_object(con, canon="NGC7000", catalog="NGC", kind="deep_sky", now=NOW_S2)
    repo.assign_object(con, frame_id=lmc.frame_ids[0], object_id=oid, object_source="header",
                       now=NOW_S2)
    dlg._on_confirm()

    assert dlg.status.text().endswith(
        "przypisano 2 z 4 klatek · kalibracja: 1 · zmieniły się w międzyczasie: 1"), \
        dlg.status.text()
    assert "pominięte" not in dlg.status.text()
    assert dlg.assigned == 2 and dlg.result() == QDialog.Accepted


def test_zatwierdzenie_po_BLEDZIE_pozycji_liczy_reszte_jako_odmowe_klingi(sciezka, monkeypatch):
    """R-S2b-13, drugi człon: po `break` na `ValueError` klatki pozycji, która padła, i pozycji
    po niej nie liczyły się nigdzie - „z M" mówiło o samych pozycjach zapisanych. Pozycja, która
    padła, wycofała się w całości (`_immediate`), a dalsze do klingi nie doszły - ta sama reguła,
    co przy przywracaniu w Zbiorach.

    Bramka pakietu: do tej poprawki ta bramka pinowała je jako DRYF („zmieniły się
    w międzyczasie"), a klinga pada tu na KONFLIKCIE ALIASU - nic się nie zmieniło, klinga
    odmówiła. Liczą się więc jako `skipped_failed` („nie zapisano, klinga odmówiła").

    Trzy pozycje (2 + 1 + 1 klatka), klinga pada na DRUGIEJ: pierwsza zapisana, odmowa 2,
    a `assigned + skipped` równa się liczbie klatek zaznaczonych pozycji.

    Falsyfikator: zdejmij doliczenie przed `break` → „2 z 2" zamiast „2 z 4"; dolicz resztę
    z powrotem do `skipped_drift` → zdanie kończy się dryfem i asercja końcówki czerwienieje."""
    v, con = sciezka
    lmc = next(p for p in resolver.path_proposals(con) if p.canon == "LMC")
    pozycje = [_pozycja(lmc, "LMC", (1, 2)), _pozycja(lmc, "NGC6960", (3,)),
               _pozycja(lmc, "NGC6992", (4,))]
    prawdziwa = repo.user_assign_object
    wolania = []

    def _pada_na_drugiej(con_, **kw):
        wolania.append(kw["canon"])
        if len(wolania) == 2:
            raise ValueError("alias 'X' wskazuje już object:1 - konflikt, zero zapisu")
        return prawdziwa(con_, **kw)

    monkeypatch.setattr(repo, "user_assign_object", _pada_na_drugiej)
    dlg = ConfirmPathObjectsDialog(con, proposals=pozycje, now_fn=lambda: NOW_S2, parent=v)
    dlg._on_confirm()

    assert wolania == ["LMC", "NGC6960"], "po błędzie klinga nie ma prawa pisać dalej"
    razem = sum(p.n_frames for p in pozycje)
    assert dlg.status.text().endswith(
        f"przypisano 2 z {razem} klatek · nie zapisano, klinga odmówiła: 2"), dlg.status.text()
    assert dlg.assigned == 2
    # R-S2b-14: „nazw" liczy pozycje, które przeszły klingę (1), nie zaznaczone (3), i się odmienia
    assert dlg.status.text().startswith("Zatwierdzono 1 nazwę · "), dlg.status.text()
    assert "konflikt" in dlg.error.text() and dlg.result() != QDialog.Accepted
    zapisane = con.execute("SELECT id FROM frame WHERE object_id IS NOT NULL ORDER BY id")
    assert [r["id"] for r in zapisane] == [1, 2]


def test_zatwierdzenie_odmienia_liczbe_nazw(sciezka):
    """R-S2b-14: „Zatwierdzono N nazw" bez odmiany (1 nazw). Dwie pozycje → „2 nazwy".

    Falsyfikator: wróć `i18n.t("path.done", names=…)` → „2 nazw"."""
    v, con = sciezka
    lmc = next(p for p in resolver.path_proposals(con) if p.canon == "LMC")
    pozycje = [_pozycja(lmc, "LMC", (1, 2)), _pozycja(lmc, "NGC6960", (3,))]
    dlg = ConfirmPathObjectsDialog(con, proposals=pozycje, now_fn=lambda: NOW_S2, parent=v)
    dlg._on_confirm()
    assert dlg.status.text().startswith("Zatwierdzono 2 nazwy · "), dlg.status.text()


def test_nadanie_z_kolejki_mowi_ROZBICIEM_per_fakt(view, monkeypatch):
    """R-S2b-13: bliźniak zdania Zbiorów po nadaniu z kolejki spłaszczał pominięcia do
    „(N pominięte - zajęte między dialogiem a zapisem)", choć klinga oddaje rozbicie per fakt -
    więc klatka kalibracyjna w zaznaczeniu szła na ekran jako „zajęta". Zaznaczenie z drążenia
    rozszerzamy o flat z fikstury: drążenie kubełka jest kind-scoped, więc inną drogą kalibracja
    do celu nie wejdzie, a pytamy o ZDANIE, nie o dobór celu.

    Falsyfikator: zdejmij `grid.zdanie_pominiec(g)` z `_on_assign` → zdanie gubi
    „ · kalibracja: 1" i asercja równości czerwienieje."""
    v, con, ids = view

    class AcceptedM42:
        selected = ("M42", "Messier", None, "FLATWIZARD")

        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr("horreum.gui.app.AssignObjectDialog", AcceptedM42)
    _select_review_tag(v, "object_raw")
    cel = v._selected_frame_ids() + [ids["frames"]["calib_flat"]]
    monkeypatch.setattr(v, "_selected_frame_ids", lambda: cel)
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_assign()

    assert msgs[-1] == "Przypisano 2 z 3 klatek → M42 · kalibracja: 1", msgs[-1]


def test_oba_zdania_osi_w_oknie_skladaja_czlony_JEDNYM_domem(sciezka, monkeypatch):
    """SPOT (R-S2b-13): pętla „iteruj `skipped_breakdown`, doklej człon" żyła w trzech siedzibach,
    a dwie z nich (`gui.app`) mówiły płasko. Trzy siedziby jednej pętli to trzy okazje, żeby
    człon dołożony do rozbicia pojawił się na jednym ekranie, a z dwóch pozostałych zniknął.
    Dlatego pytamy, czy oba zdania okna osi idą przez `grid.zdanie_pominiec`, a nie tylko, jak
    brzmią - brzmienie zgodziłoby się też z wierną kopią pętli, która rozjedzie się przy pierwszym
    nowym członie.

    Falsyfikator: wpisz w `_on_confirm` albo `_on_assign` własną pętlę po `skipped_breakdown`
    zamiast wołania helpera → znacznik nie trafia do zdania tego handlera."""
    from horreum.gui import grid
    v, con = sciezka
    wolane = []

    def _znacznik(gest, **kw):
        wolane.append(gest)
        return " · <dom>"

    monkeypatch.setattr(grid, "zdanie_pominiec", _znacznik)
    dlg = ConfirmPathObjectsDialog(con, proposals=resolver.path_proposals(con),
                                   now_fn=lambda: NOW_S2, parent=v)
    dlg._on_confirm()
    assert dlg.status.text().endswith(" · <dom>"), dlg.status.text()

    class AcceptedLMC:
        selected = ("LMC", None, "own", None)

        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr("horreum.gui.app.AssignObjectDialog", AcceptedLMC)
    v._load_review()
    _select_review_tag(v, "nameless_raw")
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_assign()
    assert msgs[-1].endswith(" · <dom>"), msgs[-1]
    assert len(wolane) == 2


# ═══════════════════ ALIASY W OKNIE „Przypisz obiekt" + FORMA NAGŁÓWKA (decyzja usera 2026-09-26)

NOW_AL = "2026-09-26T12:00:00Z"


def _dopisz_obiekt(con, canon, catalog, kind, aliasy=()):
    """Obiekt z JEDNĄ klatką light (lista okna = `library_objects`, a ta ma `JOIN frame`) i aliasami
    w `object_alias` jako `(alias_norm, source)`."""
    oid, _ = repo.upsert_object(con, canon=canon, catalog=catalog, kind=kind, now=NOW_AL)
    fid, _ = repo.upsert_frame(con, sha1_data=f"sha-al-{canon}", kind="light", filetype="fits",
                               camera_id=None, now=NOW_AL)
    repo.assign_object(con, frame_id=fid, object_id=oid, object_source="header", now=NOW_AL)
    for alias_norm, source in aliasy:
        repo.add_object_alias(con, alias_norm=alias_norm, object_id=oid, source=source, now=NOW_AL)
    return oid


@pytest.fixture
def aliasy(view):
    """Fixture §8 + cztery obiekty, które pokrywają źródła aliasów okna: xref w bazie (NGC4258 ←
    M106), xref WYŁĄCZNIE z assetu (NGC7023 ← C4, LDN1174 - bez wiersza w `object_alias`), nazwa
    potoczna (Sh2-131) i obiekt własny ze słownika (LMC). Aliasy techniczne (zapis kanonu) celowo
    obecne - okno ma je pominąć."""
    v, con, ids = view
    _dopisz_obiekt(con, "NGC4258", "NGC", "deep_sky",
                   [("M106", "catalog_xref"), ("NGC4258", "header")])
    _dopisz_obiekt(con, "NGC7023", "NGC", "deep_sky", [("NGC7023", "header")])
    _dopisz_obiekt(con, "Sh2-131", "Sh2", "deep_sky",
                   [("SH2131", "header"), ("ELEPHANTSTRUNKNEBULA", "common_name")])
    _dopisz_obiekt(con, "LMC", None, "own",
                   [("LMC", "curated"), ("LARGEMAGELLANICCLOUD", "curated")])
    return v, con, ids


def _pozycje(dlg):
    """Tekst każdej pozycji combo poza zerową, kluczowany kanonem z danych pozycji."""
    return {dlg.combo.itemData(i)[1]: dlg.combo.itemText(i) for i in range(1, dlg.combo.count())}


def test_lista_pokazuje_kanon_katalog_i_aliasy_bez_technicznych(aliasy):
    v, con, ids = aliasy
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", frame_count=2, parent=v)
    poz = _pozycje(dlg)
    assert poz["NGC4258"] == "NGC4258  ·  NGC  ·  M106"          # `NGC4258` z nagłówka pominięty
    assert poz["NGC7023"] == "NGC7023  ·  NGC  ·  C4, LDN1174"     # równoważność z assetu
    assert poz["Sh2-131"] == "Sh2-131  ·  Sh2  ·  ELEPHANTSTRUNKNEBULA"
    # Obiekt własny: brzmienie ze słownika zamiast `alias_norm`, pusty katalog jako `-`.
    assert poz["LMC"] == "LMC  ·  -  ·  Large Magellanic Cloud"
    assert poz["NGC7000"] == "NGC7000  ·  NGC"                     # bez aliasów - bez ogona
    dlg.close()


def test_AR15_alias_z_naglowka_pokazany_brzmieniem_karty_OBJECT(aliasy):
    """AR-15: alias spoza gramatyk i słownika (`ELEPHANTSTRUNKNEBULA`, `KSIEZYC`) pokazuje się
    brzmieniem z `header.object_raw` - najczęstszym, remis do pierwszego spotkanego - a klucz
    zostaje kluczem (szukajka dalej trafia po `alias_norm`)."""
    v, con, ids = aliasy
    oid = queries.object_id_by_canon(con, "Sh2-131")
    for i, raw in enumerate(["Elephant's Trunk Nebula", "Elephant's Trunk Nebula",
                             "elephants trunk nebula"]):
        fid, _ = repo.upsert_frame(con, sha1_data=f"sha-et-{i}", kind="light", filetype="fits",
                                   camera_id=None, now=NOW_AL)
        repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=raw, now=NOW_AL)
        repo.assign_object(con, frame_id=fid, object_id=oid, object_source="header", now=NOW_AL)
    moon = _dopisz_obiekt(con, "Moon", None, "solar_system", [("KSIEZYC", "solar")])
    fid, _ = repo.upsert_frame(con, sha1_data="sha-ks", kind="light", filetype="fits",
                               camera_id=None, now=NOW_AL)
    # Brzmienie z archiwum (pf4: 287 klatek „ksiezyc”); „Księżyc” z ogonkami ma inny klucz
    # `norm_alnum`, więc do aliasu `KSIEZYC` nie należy.
    repo.record_header(con, frame_id=fid, raw_json="{}", object_raw="ksiezyc", now=NOW_AL)
    repo.assign_object(con, frame_id=fid, object_id=moon, object_source="header", now=NOW_AL)

    dlg = AssignObjectDialog(con, object_raw="FlatWizard", frame_count=2, parent=v)
    poz = _pozycje(dlg)
    assert poz["Sh2-131"] == "Sh2-131  ·  Sh2  ·  Elephant's Trunk Nebula"
    assert poz["Moon"] == "Moon  ·  -  ·  ksiezyc"
    assert "ELEPHANTSTRUNKNEBULA" not in "".join(poz.values())
    dlg.search.setText("elephants trunk")
    assert list(_pozycje(dlg)) == ["Sh2-131"]
    dlg.close()


def test_szukajka_zaweza_liste_po_aliasie_i_zachowuje_wybor(aliasy):
    """`M 106` (i `m106`) znajduje NGC4258 przez alias; fraza bez trafień mówi to w pozycji zerowej;
    wybór przeżywa zawężenie, a schowany wybór gaśnie (akcja nie celuje w niewidoczny obiekt)."""
    v, con, ids = aliasy
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", frame_count=2, parent=v)
    dlg.search.setText("M 106")
    assert list(_pozycje(dlg)) == ["NGC4258"]
    dlg.search.setText("m106")
    assert list(_pozycje(dlg)) == ["NGC4258"]
    dlg.search.setText("magellanic")
    assert list(_pozycje(dlg)) == ["LMC"]
    dlg.search.setText("xyz 123")
    assert list(_pozycje(dlg)) == []
    assert dlg.combo.itemText(0) == "(żaden obiekt nie pasuje do „xyz 123”)"
    assert not dlg.accept_btn.isEnabled()
    dlg.search.setText("LDN 1174")                     # alias WYŁĄCZNIE z assetu xref
    assert list(_pozycje(dlg)) == ["NGC7023"]
    dlg.combo.setCurrentIndex(1)
    assert dlg.accept_btn.isEnabled()
    dlg.search.setText("NGC")                          # szersza fraza - wybór zostaje
    assert dlg.combo.currentData()[1] == "NGC7023"
    dlg.search.setText("LMC")                          # fraza chowa wybór - combo wraca na zero
    assert dlg.combo.currentData() is None
    assert not dlg.accept_btn.isEnabled()
    dlg.search.setText("")
    assert len(_pozycje(dlg)) == 6                     # M42, NGC7000 + cztery dopisane
    dlg.close()


def test_szukajka_sklada_ogonki_a_lista_nie_dubluje_nazwy_z_ogonkami_i_bez(aliasy):
    """Wizytacja na kopii pf4: „Księżyc" nie znajdował Księżyca - `norm_alnum` wycina litery
    z ogonkami („KSIYC"), a alias w bazie to `KSIEZYC`. Lista pokazywała też „Wielki Oblok
    Magellana, Wielki Obłok Magellana" - jedna nazwa w dwóch zapisach, bo klucze różniły się
    o wyciętą „ł". Okno składa teraz ogonki po swojej stronie (igła szukajki i deduplikacja form);
    klucze w bazie zostają bez zmian.

    Falsyfikator: zdejmij `bez_diakrytykow` z igły w `_fill_combo` → „Księżyc" daje pustą listę;
    wróć do `norm_alnum` w `aliasy_obiektu` → LMC pokazuje obie formy."""
    from horreum.gui.assign_dialog import aliasy_obiektu
    from horreum.resolve._text import norm_alnum
    v, con, ids = aliasy
    _dopisz_obiekt(con, "Moon", None, "solar_system", [("KSIEZYC", "solar"), ("MOON", "solar")])
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", frame_count=2, parent=v)
    try:
        for fraza in ("Księżyc", "księżyc", "Ksiezyc"):
            dlg.search.setText(fraza)
            assert list(_pozycje(dlg)) == ["Moon"], fraza
        assert norm_alnum("Księżyc") == "KSIYC"       # klucz zapisu i kluczy bazy NIE ruszamy
    finally:
        dlg.close()
    pretty = {"WIELKIOBLOKMAGELLANA": "Wielki Oblok Magellana",
              "WIELKIOBOKMAGELLANA": "Wielki Obłok Magellana"}
    formy = aliasy_obiektu("LMC", {"WIELKIOBLOKMAGELLANA", "WIELKIOBOKMAGELLANA"}, pretty)
    assert formy == ["Wielki Obłok Magellana"], formy     # forma z ogonkami wygrywa
    # niezależnie od kolejności, w której przyszły
    odwrotnie = aliasy_obiektu("LMC", {"WIELKIOBOKMAGELLANA", "WIELKIOBLOKMAGELLANA"},
                               dict(reversed(list(pretty.items()))))
    assert odwrotnie == ["Wielki Obłok Magellana"], odwrotnie


def test_lista_obiektow_ma_sufit_wysokosci(aliasy, qapp):
    """Wizytacja: rozwinięta lista „Przypisz obiekt" miała 1778 px mimo `maxVisibleItems` 10 -
    styl Fusion domyślnie rozwija listę na wysokość ekranu. `combobox-popup: 0` w stylu combo
    przełącza go na listę z suwakiem, która limit szanuje. Pomiar względny: wysokość listy
    w wierszach, nie w pikselach.

    Falsyfikator: zdejmij `setStyleSheet` z combo w `AssignObjectDialog` → lista rozwija się
    na wszystkie pozycje i asercja pada."""
    from PySide6.QtWidgets import QApplication as _App
    v, con, ids = aliasy
    for i in range(40):
        _dopisz_obiekt(con, f"Cr{100 + i}", "Collinder", "deep_sky")
    stary_styl = _App.style().name()                  # styl aplikacji wraca po teście (sesja)
    _App.setStyle("Fusion")                           # styl okna aplikacji (`apply_theme`)
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", frame_count=2, parent=v)
    try:
        dlg.show()
        assert dlg.combo.count() > 40
        dlg.combo.showPopup()
        qapp.processEvents()
        widok = dlg.combo.view()
        wiersz = widok.sizeHintForRow(0)
        assert wiersz > 0
        assert widok.height() <= wiersz * (dlg.combo.maxVisibleItems() + 1), \
            (widok.height(), wiersz, dlg.combo.maxVisibleItems())
        dlg.combo.hidePopup()
    finally:
        dlg.close()
        _App.setStyle(stary_styl)


@pytest.mark.parametrize("fraza, trafione", [
    ("C4", ["NGC7023"]),                   # podciąg trafiłby też `NGC4258` („NGC4…") - dokładnie
    ("Caldwell 4", ["NGC7023"]),           # inna pisownia tego samego oznaczenia
    ("M 106", ["NGC4258"]),
    ("Messier 106", ["NGC4258"]),
    ("NGC 4258", ["NGC4258"]),
    ("NGC 42", []),                        # oznaczenie bez obiektu - nie podciąg `NGC4258`
    ("Sh2 131", ["Sh2-131"]),
    ("NGC", ["NGC4258", "NGC7000", "NGC7023"]),   # sam skrót nie jest oznaczeniem - podciąg
    ("elephant", ["Sh2-131"]),             # nazwa potoczna - podciąg
    ("magellanic", ["LMC"]),               # obiekt własny - podciąg
])
def test_szukajka_oznaczenie_katalogowe_DOKLADNIE_reszta_podciagiem(aliasy, fraza, trafione):
    """B1: fraza rozpoznana przez `catalog_canon` przechodzi przez kanon i `xref` i trafia obiekt
    TEGO kanonu; nazwy nie-katalogowe dalej trafiają podciągiem."""
    v, con, ids = aliasy
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", frame_count=2, parent=v)
    dlg.search.setText(fraza)
    assert sorted(_pozycje(dlg)) == trafione
    dlg.close()


@pytest.mark.parametrize("wpisane, zdanie", [
    ("M 106", "M 106 → NGC4258 · w nagłówku: NGC 4258"),
    ("M106", "M106 → NGC4258 · w nagłówku: NGC 4258"),
    ("Heart Nebula", "Heart Nebula → IC1805 · w nagłówku: IC 1805"),
    ("Large Magellanic Cloud", "Large Magellanic Cloud → LMC · w nagłówku: LMC"),
    ("Sh2 131", "Sh2 131 → Sh2-131 · w nagłówku: Sh2-131"),
])
def test_zdanie_na_zywo_kanon_i_forma_naglowka(aliasy, wpisane, zdanie):
    """Pod polem nazwy stoi „wpisane → kanon · w nagłówku: forma" PRZED kliknięciem - z tej samej
    tożsamości, którą zapisze okno. Warunek widoczności czytamy przez `isHidden()`, bo okno nie
    jest pokazane (`isVisible()` zwraca wtedy False niezależnie od `setVisible`)."""
    v, con, ids = aliasy
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", frame_count=2, parent=v)
    assert dlg.canon_preview.isHidden()
    dlg.designation.setText(wpisane)
    assert not dlg.canon_preview.isHidden()
    assert dlg.canon_preview.text() == zdanie
    dlg._validate_and_accept()
    assert dlg.selected[0] == zdanie.split(" → ")[1].split(" · ")[0]   # zapis = kanon ze zdania
    dlg.close()


def test_zdanie_na_zywo_gasnie_dla_nazwy_nierozpoznanej(aliasy):
    v, con, ids = aliasy
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", frame_count=2, parent=v)
    dlg.designation.setText("M 106")
    assert not dlg.canon_preview.isHidden()
    dlg.designation.setText("???")
    assert dlg.canon_preview.isHidden()
    assert "Nie rozpoznaję nazwy" in dlg.error.text()   # dzisiejszy komunikat, bez zmian
    dlg.designation.setText("")
    assert dlg.canon_preview.isHidden()
    dlg.close()


# ═══════════ O3 krok 1: „Zatwierdź ze ścieżki…" dopisuje kartę OBJECT = header_form(kanon) do PLIKU
# Realne pliki FITS w tmp (writeback rusza bajty - atrapa nie dowodzi niczego), worker inline.

NOW_O3 = "2026-09-26T14:00:00Z"
LATER_O3 = "2026-09-26T15:00:00Z"


def _stos_fits(root, obj, nazwa, *, seed, object_card=None):
    """Gotowy stos FITS pod `STACKS\\<obj>\\RC8_2600MC\\Ha` BEZ zeznania o obiekcie
    (`object_card=''` = karta JEST, ale pusta - nagłówek dalej milczy)."""
    import numpy as np
    from astropy.io import fits
    d = root / "STACKS" / obj / "RC8_2600MC" / "Ha"
    d.mkdir(parents=True, exist_ok=True)
    p = d / nazwa
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16) + seed)
    hdu.header["IMAGETYP"] = "Master Light"
    hdu.header["TELESCOP"] = "RC8"
    if object_card is not None:
        hdu.header["OBJECT"] = object_card
    hdu.writeto(str(p), overwrite=True)
    return p


@pytest.fixture
def sciezka_karty(qapp, tmp_path):
    """Cztery klatki jednej propozycji `NGC7635`, każda z innym losem karty:
    `zapis` (plik czysty - karta pójdzie), `pusta` (karta OBJECT jest, pusta - pominięta, nie
    nadpisana), `dwie` (dwie obecne kopie - bramka D-W1), `raw` (RAW - read-only)."""
    from horreum import scan
    pliki = {
        "zapis": _stos_fits(tmp_path, "NGC7635", "NGC7635_Ha_a.fits", seed=1),
        "pusta": _stos_fits(tmp_path, "NGC7635", "NGC7635_Ha_b.fits", seed=2, object_card=""),
        "dwie": _stos_fits(tmp_path, "NGC7635", "NGC7635_Ha_c.fits", seed=3),
    }
    con = db.open_db(str(tmp_path / "o3.db"))
    for p in pliki.values():
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW_O3,
                           summary=scan.ScanSummary())
    fid = {k: con.execute("SELECT frame_id FROM location WHERE path = ?", (str(p),)).fetchone()[0]
           for k, p in pliki.items()}
    kopia = tmp_path / "STACKS" / "NGC7635" / "kopia" / "NGC7635_Ha_c.fits"
    repo.add_location(con, frame_id=fid["dwie"], volume="V", header_hash="h-kopia", now=NOW_O3,
                      path=str(kopia))
    raw, _ = repo.upsert_frame(con, sha1_data="sha-o3-raw", kind="light", filetype="raw",
                               camera_id=None, now=NOW_O3)
    repo.record_header(con, frame_id=raw, raw_json="{}", object_raw=None, now=NOW_O3)
    repo.add_location(con, frame_id=raw, volume="V", header_hash="h-raw", now=NOW_O3,
                      path=str(tmp_path / "LIGHTS" / "NGC7635" / "A7R3" / "_7R38821.ARW"))
    fid["raw"] = raw
    v = ObjectAxisView(con, now_fn=lambda: NOW_O3)
    yield v, con, pliki, fid
    v.close()
    con.close()


def _okno_sciezki(v, con):
    dlg = ConfirmPathObjectsDialog(con, proposals=resolver.path_proposals(con),
                                   now_fn=lambda: NOW_O3, db_path=queries.db_path_of(con), parent=v)
    dlg._runner.async_ok = False            # inline: commit/undo synchronicznie, bez QThread
    return dlg


def _karta_object(path):
    from astropy.io import fits
    with fits.open(str(path)) as h:
        return h[0].header.get("OBJECT")


def _stan_obiektu(con, fid):
    return tuple(con.execute(
        "SELECT o.canon, f.object_source, h.object_raw FROM frame f "
        "LEFT JOIN object o ON o.id = f.object_id LEFT JOIN header h ON h.frame_id = f.id "
        "WHERE f.id = ?", (fid,)).fetchone())


def test_okno_mowi_PRZED_kliknieciem_ile_kart_i_dlaczego_reszta_bez(sciezka_karty):
    v, con, pliki, fid = sciezka_karty
    dlg = _okno_sciezki(v, con)
    try:
        stos = next(it for it in dlg._items if it["proposal"].stack_tree)
        assert stos["value"] == "NGC 7635" and stos["n_cards"] == 1     # forma nagłówka, 1 z 3
        powody = [dlg.cards_skipped.item(i).text() for i in range(dlg.cards_skipped.count())]
        assert len(powody) == 3, powody
        assert any("juz istnieje" in p for p in powody)                  # pusta karta: nie nadpisujemy
        assert any("wiele obecnych kopii" in p for p in powody)
        assert any("RAW" in p for p in powody)
        assert "zapisane w plikach" not in dlg.status.text()        # zero zapisu przed klikiem
        assert _karta_object(pliki["zapis"]) is None
    finally:
        dlg.reject()


def test_zatwierdzenie_zapisuje_BAZE_i_KARTE_a_Rozwiaz_przenosi_na_naglowek_przy_TYM_SAMYM_obiekcie(
        sciezka_karty):
    """Jeden klik: wszystkie cztery klatki nazwane w bazie (`path`), karta `OBJECT = 'NGC 7635'`
    tylko w pliku, który bramki przepuszczają; re-sync w commicie odczytuje zeznanie. Po `Rozwiąż`
    ta klatka ma źródło z nagłówka i TEN SAM obiekt; reszta zostaje przy folderze, pliki nietknięte."""
    v, con, pliki, fid = sciezka_karty
    bajty_pustej = pliki["pusta"].read_bytes()
    dlg = _okno_sciezki(v, con)
    dlg._on_confirm()
    assert dlg.assigned == 4
    assert "karty OBJECT zapisane w plikach: 1" in dlg.status.text()
    assert dlg.undo_btn.isVisibleTo(dlg) and not dlg.confirm_btn.isEnabled()
    assert _karta_object(pliki["zapis"]) == "NGC 7635"
    assert pliki["pusta"].read_bytes() == bajty_pustej                    # pusta karta NIE nadpisana
    assert _stan_obiektu(con, fid["zapis"]) == ("NGC7635", "path", "NGC 7635")   # re-sync zeznania
    for k in ("pusta", "dwie", "raw"):
        assert _stan_obiektu(con, fid[k])[:2] == ("NGC7635", "path"), k
    assert con.execute("SELECT count(*) FROM pending_changes WHERE status = 'pending'"
                       ).fetchone()[0] == 0
    dlg.reject()

    resolver.run_resolver(con, LATER_O3)
    assert _stan_obiektu(con, fid["zapis"])[:2] == ("NGC7635", "header")
    for k in ("pusta", "dwie", "raw"):
        assert _stan_obiektu(con, fid[k])[:2] == ("NGC7635", "path"), k


def test_cofnij_karty_przywraca_plik_a_potwierdzenie_z_folderu_zostaje(sciezka_karty):
    v, con, pliki, fid = sciezka_karty
    przed = pliki["zapis"].read_bytes()
    dlg = _okno_sciezki(v, con)
    dlg._on_confirm()
    assert _karta_object(pliki["zapis"]) == "NGC 7635"
    dlg._on_undo()
    assert pliki["zapis"].read_bytes() == przed
    assert not dlg.undo_btn.isVisibleTo(dlg)
    assert _stan_obiektu(con, fid["zapis"])[:2] == ("NGC7635", "path")
    dlg.reject()


def test_bez_plikow_do_zapisu_okno_zachowuje_sie_jak_przed_kartami(sciezka_karty):
    """Pozycja wyłącznie z RAW-ów: zero stagingu, okno zamyka się po zapisie bazy jak dawniej."""
    v, con, pliki, fid = sciezka_karty
    raw = [p for p in resolver.path_proposals(con) if not p.stack_tree]
    dlg = ConfirmPathObjectsDialog(con, proposals=raw, now_fn=lambda: NOW_O3, parent=v)
    dlg._runner.async_ok = False
    dlg._on_confirm()
    assert dlg.result() == QDialog.Accepted and dlg.assigned == 1
    assert con.execute("SELECT count(*) FROM pending_changes").fetchone()[0] == 0


def test_przycisk_zatwierdzania_gasnie_gdy_druga_powierzchnia_pisze_do_plikow(sciezka_karty):
    v, con, pliki, fid = sciezka_karty
    v.refresh()
    _select_review_tag(v, "path_proposals")
    assert v.confirm_path_btn.isEnabled()
    v.set_writeback_busy(True)
    assert not v.confirm_path_btn.isEnabled()
    v.set_writeback_busy(False)
    assert v.confirm_path_btn.isEnabled()


# ═══════════ Tura naprawcza po bramce 0926 (C1, C2, C4) - oba okna piszące karty


class _WorkerWBiegu:
    """Atrapa workera w locie: `WritebackRunner.is_busy` patrzy na `_thread`, `cancel()` na
    `_worker.request_cancel()` - więcej stanu straż zamknięcia nie czyta."""

    def __init__(self):
        self.anulowano = False

    def request_cancel(self):
        self.anulowano = True


@pytest.mark.parametrize("ktore", ["sciezka", "naprawa"])
def test_okno_NIE_zamyka_sie_w_biegu_zapisu_tylko_przerywa(ktore, request):
    """C1: `WritebackRunner` i jego `QThread` są dziećmi okna, więc zamknięcie w biegu niszczyło
    wątek w locie. KAŻDA droga zamknięcia (`done`) w biegu = żądanie anulowania + zdanie w oknie,
    okno zostaje; po biegu zamyka się normalnie i sprząta staging. Jeden kod dla obu okien."""
    if ktore == "sciezka":
        v, con, pliki, fid = request.getfixturevalue("sciezka_karty")
        dlg = _okno_sciezki(v, con)
    else:
        v, con, files, _open = request.getfixturevalue("repair")
        dlg = _open()
    repo.stage_pending(con, run_id="r-c1", location_id=1, keyword="OBJECT", idx=None, op="add",
                       old_value=None, new_value="X", new_type="str", new_comment=None,
                       expected_header_hash="h")
    dlg._run_id = "r-c1"
    worker = _WorkerWBiegu()
    dlg._runner._thread, dlg._runner._worker = object(), worker        # „w biegu"
    for zamknij in (dlg.reject, dlg.accept, lambda: dlg.done(QDialog.Accepted)):
        zamknij()
        assert dlg.result() == 0, "okno zamknęło się nad działającym wątkiem"
    assert worker.anulowano
    assert "przerywam" in dlg.error.text()
    assert con.execute("SELECT count(*) FROM pending_changes WHERE run_id='r-c1'").fetchone()[0] == 1
    dlg._runner._thread, dlg._runner._worker = None, None              # bieg się skończył
    dlg.accept()
    assert dlg.result() == QDialog.Accepted
    assert con.execute("SELECT count(*) FROM pending_changes WHERE run_id='r-c1'").fetchone()[0] == 0


@pytest.mark.parametrize("ktore", ["sciezka", "naprawa"])
def test_wyjatek_workera_sprzata_staging_od_razu(ktore, request):
    """C1: po `_on_failed` staging runu był sierotą aż do zamknięcia okna."""
    if ktore == "sciezka":
        v, con, pliki, fid = request.getfixturevalue("sciezka_karty")
        dlg = _okno_sciezki(v, con)
    else:
        v, con, files, _open = request.getfixturevalue("repair")
        dlg = _open()
    repo.stage_pending(con, run_id="r-fail", location_id=1, keyword="OBJECT", idx=None, op="add",
                       old_value=None, new_value="X", new_type="str", new_comment=None,
                       expected_header_hash="h")
    dlg._run_id = "r-fail"
    dlg._on_failed("commit", "OSError: dysk zniknął")
    assert con.execute("SELECT count(*) FROM pending_changes").fetchone()[0] == 0
    assert "dysk zniknął" in dlg.error.text()
    dlg.reject()


@pytest.mark.parametrize("ktore", ["sciezka", "naprawa"])
def test_cofnij_dostepne_gdy_failed_z_kopia_naglowka(ktore, request):
    """C4: rdzeń nadaje `commit_id`, gdy plik został PODMIENIONY - także przy `failed` z
    `backup_text`. Dawny warunek „`applied` niepuste" zostawiał taki plik bez „Cofnij"."""
    from horreum import writeback
    if ktore == "sciezka":
        v, con, pliki, fid = request.getfixturevalue("sciezka_karty")
        dlg = _okno_sciezki(v, con)
    else:
        v, con, files, _open = request.getfixturevalue("repair")
        dlg = _open()
    res = writeback.CommitResult(
        run_id="r", commit_id=7, applied=[], blocked=[], skipped=[],
        failed=[writeback.FileResult(1, "x.fits", "failed", "weryfikacja po podmianie")])
    dlg._after_commit("commit", res)
    assert not dlg.undo_btn.isHidden() and dlg._commit_id == 7
    assert "commit 7" in dlg.status.text()
    dlg._commit_id = None                                  # nie cofamy atrapy przy zamknięciu
    dlg.reject()


def test_cofnij_karty_pokazuje_pasek_postepu(sciezka_karty, monkeypatch):
    """C4: undo w oknie ścieżki szło bez paska (wzorzec `_begin_progress` z „Napraw nagłówek…")."""
    v, con, pliki, fid = sciezka_karty
    dlg = _okno_sciezki(v, con)
    dlg._on_confirm()
    widziane = {}
    prawdziwy = dlg._runner.start

    def start(op, *a, **k):
        widziane[op] = (not dlg.bar.isHidden(), dlg.undo_btn.isEnabled())
        return prawdziwy(op, *a, **k)

    monkeypatch.setattr(dlg._runner, "start", start)
    dlg._on_undo()
    assert widziane["undo"] == (True, False)               # pasek widoczny, akcje wygaszone
    assert dlg.bar.isHidden()                              # po biegu pasek znika
    dlg.reject()


def test_CYKL_zatwierdz_cofnij_powtorz_dopisuje_karty_ponownie(sciezka_karty):
    """C2: po „Cofnij karty" klatki zostają nazwane z folderu bez karty - i do tej zmiany bez
    drogi do niej. „Zatwierdź" wraca, a powtórka dopisuje karty, choć klinga liczy klatki jako
    dryf (obiekt już mają, `assigned` = 0)."""
    v, con, pliki, fid = sciezka_karty
    dlg = _okno_sciezki(v, con)
    dlg._on_confirm()
    assert _karta_object(pliki["zapis"]) == "NGC 7635"
    assert not dlg.confirm_btn.isEnabled()
    dlg._on_undo()
    assert _karta_object(pliki["zapis"]) is None
    assert "Zatwierdź” dopisze karty ponownie" in dlg.status.text()
    assert dlg.confirm_btn.isEnabled()
    dlg._on_confirm()                                      # powtórka
    assert _karta_object(pliki["zapis"]) == "NGC 7635"
    assert dlg.assigned == 4                               # suma gestów okna, nie ostatni klik
    assert _stan_obiektu(con, fid["zapis"]) == ("NGC7635", "path", "NGC 7635")
    dlg.reject()


def test_commit_BEZ_podmiany_oddaje_Zatwierdz(sciezka_karty):
    """C2: commit z samymi `blocked` nie ma commit_id - karta nie stoi w pliku, więc „Zatwierdź"
    wraca (powtórka ma czym dopisać), a „Cofnij" się nie pokazuje."""
    from horreum import writeback
    v, con, pliki, fid = sciezka_karty
    dlg = _okno_sciezki(v, con)
    dlg._domkniety = True
    dlg._after_commit("commit", writeback.CommitResult(
        run_id="r", commit_id=None, applied=[], failed=[], skipped=[],
        blocked=[writeback.FileResult(1, "x.fits", "blocked", "header_hash zmieniony")]))
    assert dlg.confirm_btn.isEnabled() and dlg.undo_btn.isHidden()
    dlg.reject()


def test_karty_dla_pozycji_nazwanej_mimo_bledu_INNEJ_pozycji(qapp, tmp_path, monkeypatch):
    """C2: klinga padła na drugiej pozycji - pierwsza (nazwana w tym samym kliknięciu) dostaje
    kartę, a błąd drugiej zostaje widoczny w oknie."""
    from horreum import scan
    a = _stos_fits(tmp_path, "NGC7635", "NGC7635_Ha.fits", seed=11)
    b = _stos_fits(tmp_path, "Sh2-131", "Sh2-131_Ha.fits", seed=12)
    con = db.open_db(str(tmp_path / "c2.db"))
    for p in (a, b):
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW_O3,
                           summary=scan.ScanSummary())
    prawdziwa = repo.user_assign_object

    def klinga(con_, **kw):
        if kw["canon"] == "Sh2-131":
            raise ValueError("konflikt aliasu - zero zapisu")
        return prawdziwa(con_, **kw)

    monkeypatch.setattr(repo, "user_assign_object", klinga)
    v = ObjectAxisView(con, now_fn=lambda: NOW_O3)
    dlg = _okno_sciezki(v, con)
    dlg._on_confirm()
    assert _karta_object(a) == "NGC 7635" and _karta_object(b) is None
    assert "konflikt aliasu" in dlg.error.text()
    dlg.reject()
    v.close()
    con.close()


# ═══════════ D2: jedna forma karty OBJECT dla obu gestów (`forma_karty_object`)


def test_forma_karty_object_kanon_wraca_do_siebie_albo_None(repair):
    """Jeden punkt wyliczenia formy: `header_form(kanon)`, o ile drabina sprowadza ją z powrotem do
    tego kanonu. Kanon znany wyłącznie aliasem z własnego zapisu nie wraca → None."""
    from horreum.gui.app import forma_karty_object
    v, con, files, _open = repair
    assert forma_karty_object(con, "NGC7635") == "NGC 7635"
    assert forma_karty_object(con, "NGC1976") == "NGC 1976"
    assert forma_karty_object(con, "Sh2-131") == "Sh2-131"
    assert forma_karty_object(con, "LMC") == "LMC"                  # słownik własny
    assert forma_karty_object(con, "Moon") == "Moon"                # solar
    oid, _ = repo.upsert_object(con, canon="ZW77", catalog=None, kind="deep_sky", now=NOW_PD)
    repo.add_object_alias(con, alias_norm="ZUPELNIEWYMYSLONA77", object_id=oid, source="user",
                          now=NOW_PD)
    assert forma_karty_object(con, "ZW77") is None


def test_naprawa_nazwa_zwyczajowa_idzie_do_pliku_jako_oznaczenie(repair):
    """D2: podgląd „do pliku" pokazuje formę KOŃCOWĄ - `Bubble Nebula` → `'NGC 7635'`, a plik dostaje
    to samo co podgląd. Nazwa zwyczajowa zostaje w bazie aliasem, nie w nagłówku."""
    from astropy.io import fits
    v, con, files, _open = repair
    dlg = _open()
    g = dlg._groups[0]
    g["edit"].setText("Bubble Nebula")
    assert g["preview"].text() == "do pliku: OBJECT = 'NGC 7635'"
    dlg._on_save()
    assert [fits.getheader(str(p))["OBJECT"] for p in files] == ["NGC 7635", "NGC 7635"]
    dlg.reject()


def test_oba_gesty_licza_forme_TA_SAMA_funkcja(sciezka_karty, monkeypatch):
    """SPOT: „Zatwierdź ze ścieżki…" i „Napraw nagłówek…" biorą formę karty z `forma_karty_object` -
    podmiana tej jednej funkcji zmienia wartość w OBU planach."""
    from horreum.gui import app as app_mod
    v, con, pliki, fid = sciezka_karty
    # Znacznik musi być nazwą, którą drabina rozpoznaje - walidacja naprawy ma czwartą bramkę.
    monkeypatch.setattr(app_mod, "forma_karty_object", lambda con_, canon: "NGC 7000")
    value, _touched, _skipped = app_mod.plan_kart_sciezki(con, "NGC7635", [fid["zapis"]])
    assert value == "NGC 7000"
    assert app_mod._validate_object_value(con, "NGC 7635")[0] == "NGC 7000"
