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
    FRAME_COL_PATH, OBJ_COL_CANON, OBJ_COL_FRAMES)

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
    # Liczba mieszka w CZŁONIE DRUGIM (bramka pakietu, zarzut 2) — w pierwszym była elidowana
    # bez drogi powrotu, odkąd lista straciła poziomy scrollbar.
    assert "kopie nieczytelne" in v.review.item(r).text()
    assert v.review.item(r).data(SECONDARY).startswith("1")
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


def test_akcja_kubelka_cofnietych_gasi_nagrobek_PRZEZ_SLOT_nie_obok_niego(sciezka, monkeypatch):
    """PIN JEDYNEJ PRODUKCYJNEJ LINII NAPRAWY R-S2b-1 (`overwrite_weak=cofniete`, `gui/app.py`).

    Bramka obok woła klingę WPROST z `overwrite_weak=True`, więc dowodzi tylko tego, że klinga
    umie nadpisać nagrobek — a defekt siedział w POWIERZCHNI: to `_on_assign` nie podawał tego
    kwargu. Usunięcie go z `app.py` zostawiało tamtą bramkę zieloną. To ta sama klasa, którą
    kolejka trzyma jako lekcję STANDING: „bramka pyta klingę, defekt siedzi w powierzchni".

    Falsyfikator: skasuj `overwrite_weak=cofniete` z `gui/app.py` → komunikat spada na
    „Przypisano 0 z 2" i asercja stanu bazy czerwienieje."""
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
    assert msgs[-1] == "Przypisano 2 z 2 klatek → NGC7000."
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
