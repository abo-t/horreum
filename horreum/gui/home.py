"""Dom - pierwszy ekran po otwarciu bazy: cztery czasowniki, „Co mam", teczki i ostatni gest ręki.

DLACZEGO OSOBNY EKRAN. Człowiek otwiera Horreum z jednym z czterech zamiarów (przyjąć klatki,
znaleźć je, wydać do WBPP, poprawić to, co czeka) - a start na Dostawie zaczynał od ekranu
jednego z nich i chował trzy pozostałe pod nawigacją. Dom nie ma własnego stanu domeny: każdy
kafel prowadzi do ISTNIEJĄCEJ drogi, a widok mówi gospodarzowi wyłącznie, czego człowiek chce
(sygnały). Trasy - strona stosu, metoda gridu, prezentacja Zbiorów - trzyma `MainWindow`, jak przy
każdym innym moście między ekranami; Dom nie importuje ani gridu, ani nawigacji.

TECZKI W WĄTKU TŁA. `queries.release_readiness` to ~0,5 s na żywej bazie (73 obiekty, 2026-10-09,
z surowymi flatami) - Dom jest ekranem startu, więc na wątku GUI byłoby to pół sekundy martwego okna
przy KAŻDYM uruchomieniu i po każdym przebiegu Dostawy. Worker otwiera WŁASNE połączenie po ścieżce
bazy (`con` głównego wątku nie przechodzi - `check_same_thread`); baza bez ścieżki (`:memory:`)
i testy liczą inline na żywym `con`. Wynik niesie generację: ten doręczony po zmianie bazy albo po
nowszym zamówieniu trafia do kosza.

TECZKI NA WYSOKOŚĆ OKNA. Kart jest do osiemnastu (sześć rzędów po trzy), ale rzędów tyle, ile
mieści pion Domu - niższe okno dostaje mniej rzędów, nie pasek przewijania (2026-10-10: „zamiast
9 daj 18, chyba że okno się zmniejszy w pionie"). Rachunek idzie z podpowiedzi układu (pion reszty
ekranu dla BIEŻĄCEJ szerokości, bo „Co mam", status i ogon „Ostatnio" zawijają tekst, plus wysokość
każdego rzędu), więc karta z czwartą linią „do przeliczenia" podnosi swój rząd, a ukryte rzędy mają
miarę bez pokazywania. Gdy każda teczka ma kartę, komplet bez stopki ma pierwszeństwo - stopka nie
może sama wymuszać schowania rzędu, którego potrzebuje tylko ona. Karty powstają raz, przy wyniku
teczek; zmiana rozmiaru, status i wiersz „Ostatnio" tylko je odsłaniają i chowają.

„Co mam" i zdanie z dziennika liczą się synchronicznie (dwa krótkie SELECT-y, ~0,1 s razem na
żywej bazie), bo mają mówić prawdę w chwili wejścia na Dom - gest wykonany przed sekundą na innym
ekranie ma tu już stać.

OSTATNIO: RECEPTA ALBO DZIENNIK. Droga powrotu ostatniego gestu żyje dziś wyłącznie w pamięci
widoku Zbiorów (strumień `status_recipe`); Dom pokazuje TĘ SAMĄ receptę, którą dostaje pasek stanu,
a jej życie wyznacza wyłącznie ten strumień (pusta = zdjęta). Zdanie przy recepcie opisuje gest
o jej znaczniku (`Recepta.ts`, AR-94), nie ostatni gest w ogóle. Bez recepty w sesji zostaje zdanie
z dziennika `event` - bez przycisku, bo dziennik nie zna drogi powrotu."""
from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from horreum import db
from horreum.gui import i18n, portfolio, queries, theme
from horreum.gui.grid import Recepta
# Stan teczki → rola koloru i zdanie pod kursorem: jeden właściciel z oknem teczek „Wydaj obiekt…".
# Role są nazwami ról QSS (`theme.ROLES`), więc kropka bierze kolor z motywu, nie z literału.
from horreum.gui.projection_dialog import _STATE_ROLES, _STATE_TIPS
from horreum.gui.wb_worker import EtykietaBledu, tekst_powodu, wiersz_systemu   # zdanie + szczegół (AR-198)
from horreum.item_reasons import powod_okna       # wyjątek workera jedną regułą okna (AR-264)

# Teczki Domu: trzy kolumny, do sześciu rzędów - a rzędów tyle, ile mieści wysokość okna
# (`_dopasuj_rzedy`). Reszta jest o jedno zapytanie dalej, w Znajdź (stopka to mówi).
KOLUMNY_TECZEK = 3
RZEDY_TECZEK = 6
TECZKI_NA_DOMU = KOLUMNY_TECZEK * RZEDY_TECZEK

# Pozycje menu „Więcej…" - klucze sygnału `wiecej`; trasę każdej z nich zna gospodarz.
# „Wciągnij z WBPP…” (krok cyklu po obróbce, AR-109) stoi tu, a nie na kaflu Przyjmij: kafel to JEDNA
# interakcja do raportu dostawy, a menu na kaflu zamieniłoby jego klik w rozwinięcie listy; żniwa
# robi się przy siadaniu do obróbki, rzadziej niż cztery kafle - tak jak reszta tego menu.
WIECEJ_ZNIWA = "zniwa"
WIECEJ_PLANER = "planer"
WIECEJ_STANOWISKA = "stanowiska"
WIECEJ_OS_TELESKOPU = "os_teleskopu"
WIECEJ_NAZWY = "nazwy"
WIECEJ_MAKRA = "makra"
WIECEJ_PERSPEKTYWY = "perspektywy"
WIECEJ_DOSTAWA = "dostawa"
WIECEJ_KLASYCZNE = "klasyczne"

# Gest JEDNEGO czasownika, który ma własne zdanie. Czasownik spoza tej mapy i gest kilku czasowników
# (cofnięcie uwag mieszanego zaznaczenia emituje naraz `note.set` i `note.cleared`, zapis nagłówków
# `header.refreshed` z `location.refreshed`) mówią zdaniem ogólnym z PEŁNĄ liczbą zmian - zdanie
# jednego z czasowników kłamałoby o reszcie. Klucze składane mapą, więc parytet z katalogiem pilnuje
# test, nie kolektor literałów.
_ZDANIA_GESTU = {
    "object.assigned": "home.gest.object_assigned",
    "object.cleared": "home.gest.object_cleared",
    "object.aliased": "home.gest.object_aliased",
    "object.upserted": "home.gest.object_upserted",
    "location.renamed": "home.gest.location_renamed",
    "note.set": "home.gest.note_set",
    "note.cleared": "home.gest.note_cleared",
    "camera.pixel_user_set": "home.gest.camera_pixel_user_set",
    "camera.pixel_user_cleared": "home.gest.camera_pixel_user_cleared",
    "frame.retired": "home.gest.frame_retired",
    "frame.unretired": "home.gest.frame_unretired",
    "config.assigned": "home.gest.config_assigned",
    "observatory.assigned": "home.gest.observatory_assigned",
    "observatory.named": "home.gest.observatory_named",
    "observatory.merged": "home.gest.observatory_merged",
    "telescope.merged": "home.gest.telescope_merged",
    "telescope.approved": "home.gest.telescope_approved",
    "telescope.labeled": "home.gest.telescope_labeled",
    "telescope.parked": "home.gest.telescope_parked",
    "integration.judged": "home.gest.integration_judged",
    "integration.offset_set": "home.gest.integration_offset_set",
    "target_plan.set": "home.gest.target_plan_set",
    "target_plan.cleared": "home.gest.target_plan_cleared",
    "perspective.saved": "home.gest.perspective_saved",
}

# ZDARZENIA TOWARZYSZĄCE gestowi osi obiektu: klinga zapisuje klatkę PARĄ czasowników (§5.9) -
# `object.unassigned` (co zdjęto) obok `object.cleared` albo `object.assigned` tej samej klatki - a gest
# nadania dokłada słownik (`object.upserted`, `object.aliased` na celu `object:`). Dom liczył je jak
# osobne zmiany: jedno „Cofnij przypisanie" na 2 klatkach mówiło „4 zmiany" obok paska „2 z 2
# klatek". Jednostką gestu na klatkach jest KLATKA, więc zdanie bierze czasownik główny, a pary
# i słownika nie dolicza. Para odpada wyłącznie wtedy, gdy czasownik główny ma co najmniej tyle
# zdarzeń - cofnięcie nadpisania do stanu bez obiektu odpina klatkę bez nadania (`_restore_override_tx`)
# i zdanie o samych nadaniach przemilczałoby resztę.
_GLOWNE_OSI_OBIEKTU = ("object.assigned", "object.cleared")
_SLOWNIK_OSI_OBIEKTU = ("object.upserted", "object.aliased")
_PARA_OSI_OBIEKTU = "object.unassigned"


def _bez_towarzyszacych(verbs):
    """Czasowniki gestu bez zdarzeń towarzyszących gestowi osi obiektu - kopia, bez zmian, gdy gest
    nie ma dokładnie jednego czasownika głównego tej osi."""
    glowne = [v for v in _GLOWNE_OSI_OBIEKTU if v in verbs]
    if len(glowne) != 1:
        return verbs
    glowny = glowne[0]
    zostaja = {v: n for v, n in verbs.items() if v not in _SLOWNIK_OSI_OBIEKTU}
    if zostaja.get(_PARA_OSI_OBIEKTU, 0) <= zostaja[glowny]:
        zostaja.pop(_PARA_OSI_OBIEKTU, None)
    return zostaja


# Powód relokacji pliku z gestu „Zmień obiekt…"/„Uzgodnij pliki…" (AR-17 krok 3) i z jego
# cofnięcia - ten, który klinga zapisu dokłada do ładunku `location.renamed` (`reason`). Takie
# przeniesienie to nie „przemianowanie": plik zmienił folder razem z obiektem, a zdanie Domu ma to
# powiedzieć.
POWOD_ZMIANY_OBIEKTU = "object_change"
POWOD_COFNIECIA_ZMIANY = "object_change_undo"


def zdanie_gestu(gest):
    """Co zrobił gest z dziennika (`queries.last_hand_gesture`) - bez daty. Jeden znany czasownik
    = jego zdanie; inaczej zdanie ogólne z liczbą WSZYSTKICH eventów gestu.

    GEST ZMIANY OBIEKTU MA PIERWSZEŃSTWO: zapisuje kilka czasowników naraz (obiekt w bazie,
    przeniesienie pliku, karta), więc zdanie ogólne „N zmian" ukrywałoby jedyną rzecz, której
    człowiek szuka w pamięci - że pliki pojechały do innego folderu. Rozpoznanie po powodzie
    relokacji (`reasons` read-modelu: czasownik → powód → liczba), nie po zestawie czasowników.

    LICZBA NETTO: w jednym geście zapisu plik, którego kartę odbił rdzeń, wraca tym samym
    czasownikiem z powodem cofnięcia - liczy się różnica „gest - powrót”, nie suma. „Przeniesiono do
    folderu obiektu” mówi się WYŁĄCZNIE o relokacjach ze zmianą katalogu (`relocated_dirs`
    read-modelu: powód → liczba); gest zmienia też samą nazwę w tym samym folderze (człon obiektu
    na początku nazwy, D-1011-6 `O2`), więc bez tego rozróżnienia zdanie jest ogólne (nowe miejsce
    albo nowa nazwa). Netto ujemne = cofnięcie gestu.

    JEDNOSTKA GESTU NA KLATKACH TO KLATKA (`_bez_towarzyszacych`): para `object.unassigned` i słownik
    obiektów nie są osobnymi zmianami, więc Dom mówi tą samą liczbą, co pasek po geście."""
    relokacje = (gest.get("reasons") or {}).get("location.renamed", {})
    netto = relokacje.get(POWOD_ZMIANY_OBIEKTU, 0) - relokacje.get(POWOD_COFNIECIA_ZMIANY, 0)
    katalogi = gest.get("relocated_dirs") or {}
    netto_katalogow = (katalogi.get(POWOD_ZMIANY_OBIEKTU, 0)
                       - katalogi.get(POWOD_COFNIECIA_ZMIANY, 0))
    if netto_katalogow > 0:
        return i18n.t_plural("home.gest.object_relocated", netto_katalogow)
    if netto > 0:
        return i18n.t_plural("home.gest.object_files", netto)
    if netto < 0:
        return i18n.t_plural("home.gest.object_relocated_back", -netto)
    verbs = _bez_towarzyszacych(gest["verbs"])
    odrzucone = gest.get("discarded")
    if odrzucone and set(verbs) == {"staging.discarded"}:
        # „Odrzuć” przebiegu z poprzedniej sesji (AR-304): dziennik ma JEDNO zdarzenie na odrzucenie,
        # a liczba zmian stoi w jego ładunku (`queries.odrzucenia_szuflady`) - zdanie mówi nią.
        czlony = [i18n.t_plural(klucz, odrzucone[klinga])
                  for klinga, klucz in (("karty", "home.gest.staging_discarded"),
                                        ("nazwy", "home.gest.staging_discarded_names"))
                  if odrzucone.get(klinga)]
        if czlony:
            return " · ".join(czlony)
    if len(verbs) == 1:
        (verb, n), = verbs.items()
        klucz = _ZDANIA_GESTU.get(verb)
        if klucz is not None:
            return i18n.t_plural(klucz, n)
    return i18n.t_plural("home.gest.many", gest["n"])


def dzien_gestu(ts, now):
    """Dzień gestu w czasie LOKALNYM (dziennik pisze UTC, człowiek pamięta swój wieczór), rok tylko
    wtedy, gdy nie jest bieżący - „04.10" z zeszłego roku udawałoby gest sprzed tygodnia."""
    dt = datetime.fromisoformat(ts).astimezone()
    teraz = datetime.fromisoformat(now).astimezone()
    pola = {"dd": f"{dt.day:02d}", "mm": f"{dt.month:02d}", "yyyy": f"{dt.year:04d}"}
    return i18n.t("home.last.day" if dt.year == teraz.year else "home.last.day_year", **pola)


def zdanie_dziennika(gest, now):
    """„Ostatnio (04.10): 15 plików przemianowano" - zdanie Domu bez recepty w sesji."""
    return i18n.t("home.last.journal", day=dzien_gestu(gest["ts"], now), what=zdanie_gestu(gest))


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


class TeczkiWorker(QObject):
    """Teczki Domu poza wątkiem GUI (wzorzec `DryWorker`/`PlanWorker`). Otwiera WŁASNE połączenie
    po `db_path`; tryb inline (`db_path` pusty) dostaje żywe `con` wołającego i biegnie
    synchronicznie. Wynik niesie generację startu - widok odrzuca stale."""

    done = Signal(int, object)          # (generacja, wiersze `release_readiness`)
    # (generacja, powód) - `object`: kod błędu bazy klasą (AR-198) przeżywa sygnał
    failed = Signal(int, object)
    finished = Signal()

    def __init__(self, db_path, gen, con=None):
        super().__init__()
        self._db_path = db_path
        self._con = con
        self._gen = gen

    @Slot()
    def run(self):
        try:
            self.done.emit(self._gen, self._compute())
        except Exception as exc:        # szczerze na ekran, nie cicha śmierć wątku
            # Teczki czytają WYŁĄCZNIE bazę (zmierzone: 0 wywołań systemu plików), więc realną
            # awarią jest błąd SQLite - klasą bazy w języku UI, surowy tekst w szczególe (AR-198);
            # błąd programu zdaniem `prog_error` z miejscem w kodzie w szczególe (`powod_okna`, AR-264).
            self.failed.emit(self._gen, powod_okna(exc))
        finally:
            self.finished.emit()

    def _compute(self):
        own = bool(self._db_path)
        con = db.connect(self._db_path) if own else self._con
        try:
            return queries.release_readiness(con)
        finally:
            if own:
                con.close()


class _KartaTeczki(QPushButton):
    """Przycisk z WŁASNYM układem etykiet. `QPushButton` liczy podpowiedź rozmiaru z napisu,
    którego karta nie ma, więc bez tej klasy siatka dawała karcie wysokość pustego przycisku
    (wizytator natywnie: 24 px przy układzie potrzebującym 68 px - tekst ucięty). Podpowiedzi idą
    z układu, a przycisk zostaje przyciskiem: fokus klawiatury, Enter/spacja, `clicked`."""

    def sizeHint(self):
        lay = self.layout()
        return lay.sizeHint() if lay is not None else super().sizeHint()

    def minimumSizeHint(self):
        lay = self.layout()
        return lay.minimumSize() if lay is not None else super().minimumSizeHint()


def _etykieta(tekst="", *, rola=None, pogrubiona=False):
    lbl = QLabel(tekst)
    if rola is not None:
        lbl.setProperty("role", rola)
    if pogrubiona:
        f = lbl.font()
        f.setBold(True)
        lbl.setFont(f)
    return lbl


class HomeView(QWidget):
    """Ekran Dom. Sygnały to ZAMIARY człowieka - gospodarz zamienia je na trasy:
    `przyjmij`/`znajdz`/`wydaj`/`popraw` (kafle i stopka teczek), `teczka(object_id, kanon)` (klik
    karty), `wiecej(klucz)` (menu „Więcej…", klucze `WIECEJ_*`), `recepta_klik` (pierwszy człon
    recepty). Wejścia gospodarza: `odswiez`, `odswiez_teczki`, `ustaw_popraw`, `pokaz_recepte`,
    `wstrzymaj_recepte`, `use_theme`, `zatrzymaj_pola`.

    `poza_watkiem` - seam testowy teczek (False = rachunek inline, jak `_pola_poza_watkiem`
    gospodarza, z którego go dostaje)."""

    przyjmij = Signal()
    znajdz = Signal()
    wydaj = Signal()
    popraw = Signal()
    teczka = Signal(int, str)
    wiecej = Signal(str)
    recepta_klik = Signal()

    def __init__(self, con, now_fn=None, parent=None, *, theme_name=theme.DEFAULT,
                 poza_watkiem=True):
        super().__init__(parent)
        self.con = con
        self._now = now_fn or _utc_now_iso
        self._db_path = queries.db_path_of(con)
        self._poza_watkiem = poza_watkiem
        self._gen = 0
        self._pokazana_gen = 0           # generacja, której wynik (albo błąd) stoi na ekranie
        self._worker = None
        self._thread = None
        self._zatrzymany = False
        self._recepta = None             # recepta paska z bieżącej sesji (`grid.Recepta`) albo brak
        self._wstrzymana = False         # blokada po kliknięciu członu - wspólna z paskiem (gospodarz)
        self._gest = None                # ostatni gest ręki z dziennika
        self.karty = []                  # karty teczek (QPushButton z danymi w `teczka_row`), do 18
        self._teczki = []                # wszystkie wiersze `release_readiness` - stopka liczy resztę
        self._build_ui()
        self.use_theme(theme_name)
        self.odswiez()
        self.odswiez_teczki()

    # ---------------------------------------------------------------- budowa

    def _build_ui(self):
        zewn = QVBoxLayout(self)
        zewn.setContentsMargins(0, 0, 0, 0)
        # Przewijanie, bo kanon minimalnego ekranu jest niski, a dziewięć kart teczek z ogonem
        # „do przeliczenia" potrafi go przerosnąć - bez tego dolny wiersz ucinałby się bez śladu.
        scroll = QScrollArea()
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        zewn.addWidget(scroll)
        tresc = QWidget()
        self._tresc = tresc
        scroll.setWidget(tresc)
        v = QVBoxLayout(tresc)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(10)

        naglowek = QHBoxLayout()
        tytul = _etykieta(i18n.t("home.title"), pogrubiona=True)
        f = tytul.font()
        f.setPointSizeF(f.pointSizeF() * 1.3)
        tytul.setFont(f)
        naglowek.addWidget(tytul, 1)
        self.btn_wiecej = QPushButton(i18n.t("home.more"))
        menu = QMenu(self.btn_wiecej)
        self.akcje_wiecej = {}
        self._zniwa_bieg = False    # dwa powody wygaszenia „Wciągnij z WBPP…” (`_sync_zniwa`)
        self._zniwa_zapis = False
        # Napis żniw z klucza przycisku Dostawy: nazwa gestu ma w katalogu jednego właściciela.
        # Tak samo „Oś teleskopu" - napis z tytułu podstrony Porządków, do której prowadzi.
        for klucz, tekst in ((WIECEJ_ZNIWA, i18n.t("pipeline.btn.harvest")),
                             (WIECEJ_PLANER, i18n.t("home.more.planner")),
                             (WIECEJ_STANOWISKA, i18n.t("home.more.sites")),
                             (WIECEJ_OS_TELESKOPU, i18n.t("tasks.telescope_axis")),
                             (WIECEJ_NAZWY, i18n.t("home.more.rename")),
                             (WIECEJ_MAKRA, i18n.t("home.more.macro")),
                             (WIECEJ_PERSPEKTYWY, i18n.t("home.more.perspectives")),
                             (WIECEJ_DOSTAWA, i18n.t("home.more.advanced_intake")),
                             (WIECEJ_KLASYCZNE, i18n.t("home.more.classic"))):
            akcja = menu.addAction(tekst)
            akcja.triggered.connect(lambda _c=False, k=klucz: self.wiecej.emit(k))
            self.akcje_wiecej[klucz] = akcja
        # Podpowiedź wygaszonej pozycji mówi DLACZEGO (`set_busy`); pozycje bez jawnej podpowiedzi
        # milczą (QMenu pokazuje wyłącznie ustawioną podpowiedź akcji).
        menu.setToolTipsVisible(True)
        self.btn_wiecej.setMenu(menu)
        naglowek.addWidget(self.btn_wiecej)
        v.addLayout(naglowek)

        kafle = QHBoxLayout()
        kafle.setSpacing(10)
        self.tile_przyjmij = self._kafel(i18n.t("home.tile.receive"),
                                         i18n.t("home.tile.receive_tip"), self.przyjmij)
        self.tile_znajdz = self._kafel(i18n.t("home.tile.find"),
                                       i18n.t("home.tile.find_tip"), self.znajdz)
        self.tile_wydaj = self._kafel(i18n.t("home.tile.release"),
                                      i18n.t("home.tile.release_tip"), self.wydaj)
        self.tile_popraw = self._kafel(i18n.t("home.tile.fix"),
                                       i18n.t("home.tile.fix_tip"), self.popraw)
        for kafel in (self.tile_przyjmij, self.tile_znajdz, self.tile_wydaj, self.tile_popraw):
            kafle.addWidget(kafel, 1)
        v.addLayout(kafle)

        self.co_mam = _etykieta()
        self.co_mam.setWordWrap(True)
        self.co_mam.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.co_mam)

        v.addWidget(_etykieta(i18n.t("home.folders.title"), pogrubiona=True))
        # Pole z protokołu „zdanie + szczegół” (AR-198): szczegół awarii biegu teczek pod kursorem,
        # a „Liczę gotowość…” i pusty stan (`setText`) go zdejmują.
        self.teczki_status = EtykietaBledu("")
        self.teczki_status.setProperty("role", "secondary")
        self.teczki_status.setWordWrap(True)
        v.addWidget(self.teczki_status)
        siatka = QWidget()
        self._siatka = siatka
        self.teczki_siatka = QGridLayout(siatka)
        self.teczki_siatka.setContentsMargins(0, 0, 0, 0)
        self.teczki_siatka.setSpacing(8)
        for k in range(KOLUMNY_TECZEK):
            self.teczki_siatka.setColumnStretch(k, 1)
        v.addWidget(siatka)
        # Stopka teczek jako płaski przycisk: zdanie mówi „szukaj w Znajdź", więc klik ma tam prowadzić.
        self.btn_teczki_wiecej = QPushButton()
        self.btn_teczki_wiecej.setFlat(True)
        self.btn_teczki_wiecej.setCursor(Qt.PointingHandCursor)
        self.btn_teczki_wiecej.clicked.connect(self.znajdz)
        self.btn_teczki_wiecej.setVisible(False)
        stopka = QHBoxLayout()
        stopka.addWidget(self.btn_teczki_wiecej)
        stopka.addStretch(1)
        v.addLayout(stopka)

        # Ostatnio: CO zrobił gest (zdanie z dziennika) + przycisk PIERWSZEGO członu recepty
        # + dalsze człony. Napis przycisku to tekst członu, który klik wykona - człon bywa
        # odsłonięciem celu, a dopiero następny cofa zapis, więc słowa „Cofnij" nie ma tu na sztywno.
        # Przycisk na szerokość treści: rozciągnięty na pół okna udawał pasek, nie gest.
        self.ostatnio = QWidget()
        rzad = QHBoxLayout(self.ostatnio)
        rzad.setContentsMargins(0, 6, 0, 0)
        self.last_label = _etykieta()
        rzad.addWidget(self.last_label)
        self.btn_recepta = QPushButton()
        self.btn_recepta.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.btn_recepta.clicked.connect(self.recepta_klik)
        rzad.addWidget(self.btn_recepta)
        self.last_rest = _etykieta(rola="secondary")
        self.last_rest.setWordWrap(True)
        rzad.addWidget(self.last_rest, 1)
        rzad.addStretch(1)
        v.addWidget(self.ostatnio)
        v.addStretch(1)

    def _kafel(self, tekst, podpowiedz, sygnal):
        btn = QPushButton(tekst)
        btn.setToolTip(podpowiedz)
        btn.setMinimumHeight(64)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        f = btn.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.15)
        btn.setFont(f)
        btn.clicked.connect(sygnal)
        return btn

    def use_theme(self, name):
        """Złota ramka kafla Przyjmij - ta sama waga, co złota akcja Dostawy, do której prowadzi.
        Kolor z motywu, nie literał: arkusz widżetu nie śledzi motywu aplikacji, więc gospodarz
        woła tę metodę przy przełączeniu (kropki teczek jadą rolą QSS i przemalowują się same)."""
        zloto = theme.accents(theme.normalize(name))["gold"]
        self.tile_przyjmij.setStyleSheet(
            f"QPushButton {{ border: 2px solid {zloto}; border-radius: 4px; padding: 6px; }}")

    # ---------------------------------------------------------------- odczyty

    def odswiez(self):
        """„Co mam" i zdanie z dziennika - ze stanu bazy w tej chwili (wejście na Dom, koniec
        przebiegu Dostawy). Teczki mają osobne wejście, bo liczą się w tle."""
        s = queries.home_summary(self.con)
        if not s["lights"]:
            self.co_mam.setText(i18n.t("home.have.empty"))
        else:
            czlony = [i18n.t_plural("home.have.objects", s["objects"]),
                      i18n.t_plural("home.have.lights", s["lights"]),
                      portfolio.format_hours(s["hours"] * 3600),
                      i18n.t_plural("home.have.nights", s["nights"])]
            if s["last_night"]:
                czlony.append(i18n.t("home.have.last_night", night=s["last_night"]))
            self.co_mam.setText(i18n.t("home.have.line", what=" · ".join(czlony)))
        self._gest = self._gest_ostatnio()
        self._render_ostatnio()

    def odswiez_teczki(self):
        """Zamów teczki od nowa (start, koniec przebiegu Dostawy, gest osi obiektu). Jeden worker
        naraz: zamówienie w biegu podbija generację, a stary wynik trafia do kosza i rachunek
        rusza jeszcze raz po sprzątnięciu wątku."""
        if self._zatrzymany:
            return
        self._gen += 1
        if self._worker is not None:
            return
        self._start(self._gen)

    def _start(self, gen):
        self.teczki_status.setText(i18n.t("home.folders.computing"))
        self.teczki_status.setVisible(True)
        self._dopasuj_rzedy()            # status zabiera pion starym kartom, które zostają w biegu
        inline = not (self._poza_watkiem and self._db_path)
        worker = TeczkiWorker(None if inline else self._db_path, gen,
                              con=self.con if inline else None)
        worker.done.connect(self._on_teczki)
        worker.failed.connect(self._on_teczki_failed)
        self._worker = worker
        if inline:
            try:
                worker.run()             # sygnały direct = synchronicznie
            finally:
                self._worker = None
            return
        self._thread = QThread(self)
        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _cleanup_thread(self):
        # KOLEJNOŚĆ JAK W `PlanWorker`/`DryWorker` (deadlock AB-BA GIL × ~QThread, dump 2026-07-20):
        # worker.deleteLater → wait (zwalnia GIL, wątek dokańcza destrukcję workera) → thread.deleteLater.
        if self._thread is None:
            return                       # wątek już zebrał `zatrzymaj_pola`; sygnał z kolejki
        self._worker.deleteLater()
        self._thread.wait()
        self._thread.deleteLater()
        self._worker = None
        self._thread = None
        if self._pokazana_gen != self._gen and not self._zatrzymany:
            self._start(self._gen)       # zamówienie przyszło w biegu → licz jeszcze raz

    def zatrzymaj_pola(self):
        """Widok znika (zmiana bazy, zamknięcie okna - `MainWindow._zatrzymaj_watki_widokow` woła tę
        metodę po nazwie): ZBIERZ wątek teczek, zanim rodzic go skasuje (`~QThread` w biegu to twardy
        abort). Generacja w górę, więc wynik, który zdążył wyjść z wątku, nie dotknie ekranu ani
        zamkniętego połączenia. Rachunek nie ma punktu przerwania - `wait` czeka na jego koniec
        (~0,5 s na żywej bazie). Idempotentne."""
        self._zatrzymany = True
        self._gen += 1
        if self._thread is None:
            return
        self._thread.quit()
        self._worker.deleteLater()
        self._thread.wait()
        self._thread.deleteLater()
        self._worker = None
        self._thread = None

    @Slot(int, object)
    def _on_teczki(self, gen, rows):
        if gen != self._gen:
            return                       # stale - świeży bieg rusza w sprzątaniu wątku
        self._pokazana_gen = gen
        self._render_teczki(rows)

    @Slot(int, object)
    def _on_teczki_failed(self, gen, powod):
        if gen != self._gen:
            return
        self._pokazana_gen = gen
        # Zdanie stoi do następnego biegu, a ten rusza dopiero po Dostawie albo geście - przy
        # kolejnym wejściu na Dom mówi więc o liczeniu sprzed chwil albo godzin. Mówi to wprost
        # i podaje godzinę porażki (czas lokalny), żeby nie udawało stanu z tej chwili (odbiór
        # 0.19.0 DO7).
        godzina = datetime.fromisoformat(self._now()).astimezone().strftime("%H:%M")
        self.teczki_status.ustaw(
            i18n.t("home.folders.failed", time=godzina, msg=tekst_powodu(powod)),
            wiersz_systemu(powod))
        self.teczki_status.setVisible(True)
        self._dopasuj_rzedy()            # komunikat zostaje obok starych kart do następnego biegu

    # ---------------------------------------------------------------- teczki

    def _render_teczki(self, rows):
        for karta in self.karty:
            self.teczki_siatka.removeWidget(karta)
            karta.deleteLater()
        self.karty = []
        self._teczki = list(rows)
        for i, r in enumerate(rows[:TECZKI_NA_DOMU]):
            karta = self._karta(r)
            self.teczki_siatka.addWidget(karta, i // KOLUMNY_TECZEK, i % KOLUMNY_TECZEK)
            self.karty.append(karta)
        self.teczki_status.setText("" if rows else i18n.t("home.folders.empty"))
        self.teczki_status.setVisible(not rows)
        self._dopasuj_rzedy()

    def _wysokosc_poza_teczkami(self, *, ze_stopka=True):
        """Pion Domu zajęty przez wszystko POZA siatką teczek (nagłówek, kafle, „Co mam", tytuł,
        status, stopka, „Ostatnio", marginesy i odstępy) - z podpowiedzi układu dla BIEŻĄCEJ
        szerokości (`heightForWidth`: etykiety zawijają tekst, więc węższe okno ma wyższą resztę),
        nie z geometrii, bo przy pierwszym pokazaniu geometrii jeszcze nie ma. Stopkę liczy wg
        `ze_stopka`, nie wg tego, czy akurat stoi: jej obecność jest wynikiem tego rachunku, więc
        nie może być jego wejściem."""
        uklad = self._tresc.layout()
        calosc = (uklad.heightForWidth(self.width()) if uklad.hasHeightForWidth()
                  else uklad.sizeHint().height())
        reszta = calosc - self._siatka.sizeHint().height()
        stopka = self.btn_teczki_wiecej.sizeHint().height() + uklad.spacing()
        if ze_stopka and self.btn_teczki_wiecej.isHidden():
            reszta += stopka
        elif not ze_stopka and not self.btn_teczki_wiecej.isHidden():
            reszta -= stopka
        return reszta

    def _wysokosci_rzedow(self):
        """Wysokość każdego rzędu kart = najwyższa karta w rzędzie (czwarta linia „do przeliczenia"
        podnosi cały rząd), z podpowiedzi kart - ukryty rząd ma miarę tak samo jak widoczny."""
        rzedy = []
        for i, karta in enumerate(self.karty):
            if i % KOLUMNY_TECZEK == 0:
                rzedy.append(0)
            rzedy[-1] = max(rzedy[-1], karta.sizeHint().height())
        return rzedy

    def _rzedy_mieszczace_sie(self, wysokosc):
        """Ile rzędów teczek mieści Dom o wysokości `wysokosc`: co najmniej jeden (niższe okno
        przewija ten jeden), co najwyżej tyle, ile jest rzędów kart."""
        rzedy = self._wysokosci_rzedow()
        if not rzedy:
            return 0
        odstep = self.teczki_siatka.verticalSpacing()
        # Każda teczka ma kartę i komplet mieści się BEZ stopki - pokaż komplet: stopka, która
        # sama wymusiłaby schowanie ostatniego rzędu, mówiłaby o kartach ukrytych tylko przez nią.
        if len(self._teczki) <= len(self.karty):
            komplet = sum(rzedy) + odstep * (len(rzedy) - 1)
            if komplet <= wysokosc - self._wysokosc_poza_teczkami(ze_stopka=False):
                return len(rzedy)
        dostepne = wysokosc - self._wysokosc_poza_teczkami()
        n = zajete = 0
        for wysokosc_rzedu in rzedy:
            zajete += wysokosc_rzedu + (odstep if n else 0)
            if zajete > dostepne:
                break
            n += 1
        return max(1, n)

    def _dopasuj_rzedy(self):
        """Odsłoń tyle rzędów kart, ile mieści bieżąca wysokość Domu (po zbudowaniu kart, przy każdej
        zmianie wysokości i gdy wiersz „Ostatnio" pojawia się albo znika); reszta kart jest ukryta
        i liczy się do stopki „… i N kolejnych" razem z teczkami, dla których kart nie ma."""
        if not self.karty:
            self.btn_teczki_wiecej.setVisible(False)
            return
        pokazane = min(len(self.karty),
                       self._rzedy_mieszczace_sie(self._pion_widoku()) * KOLUMNY_TECZEK)
        for i, karta in enumerate(self.karty):
            karta.setVisible(i < pokazane)
        reszta = len(self._teczki) - pokazane
        self.btn_teczki_wiecej.setVisible(reszta > 0)
        if reszta > 0:
            self.btn_teczki_wiecej.setText(i18n.t_plural("home.folders.more", reszta))

    def _pion_widoku(self):
        """Pion, jaki widok oddaje treści: wysokość Domu, pomniejszona o pasek poziomy, gdy treść
        jest szersza od okna (poniżej podłogi okna karty i kafle nie zwężają się dalej). Viewport
        w `resizeEvent` jeszcze tego nie wie, więc liczymy z minimum treści, nie z jego geometrii."""
        pion = self.height()
        if self._tresc.minimumSizeHint().width() > self.width():
            pion -= self._scroll.horizontalScrollBar().sizeHint().height()
        return pion

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._dopasuj_rzedy()            # także po samej szerokości: zawinięty tekst rośnie w pion

    def _karta(self, r):
        """Karta teczki: kropka stanu, obiekt, rozmiar materiału, kalibracja i - osobno - lighty,
        które czekają tylko na przeliczenie rodowodu (master JEST): to robota na jedno kliknięcie
        w Dostawie, nie braki do dokupienia, więc nie wolno jej schować w procencie flatu.

        Przycisk, nie ramka z obsługą myszy: karta ma fokus klawiatury i Enter/spację za darmo,
        a etykiety w środku są przezroczyste dla myszy, więc klik zawsze trafia w przycisk."""
        karta = _KartaTeczki()
        karta.setCursor(Qt.PointingHandCursor)
        karta.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        karta.setAccessibleName(r["canon"])
        karta.setToolTip(i18n.t(_STATE_TIPS[r["stan"]]) + "\n" + i18n.t("home.card.tip",
                                                                          canon=r["canon"]))
        karta.teczka_row = r
        v = QVBoxLayout(karta)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(2)
        gora = QHBoxLayout()
        kropka = _etykieta("●", rola=_STATE_ROLES[r["stan"]])
        nazwa = _etykieta(r["canon"], pogrubiona=True)
        gora.addWidget(kropka)
        gora.addWidget(nazwa, 1)
        v.addLayout(gora)
        rozmiar = " · ".join((portfolio.format_hours(r["hours"] * 3600),
                              i18n.t_plural("home.have.nights", r["nights"]),
                              i18n.t_plural("home.card.sets", r["zestawy"])))
        flat = i18n.t("home.card.flat", n=r["pct_master_flat"])
        if r["n_raw_flat"]:
            flat += i18n.t("home.card.raw", n=r["pct_raw_flat"])
        kalibracja = " · ".join((flat, i18n.t("home.card.dark", n=r["pct_master_dark"])))
        etykiety = [kropka, nazwa, _etykieta(rozmiar, rola="secondary"),
                    _etykieta(kalibracja, rola="secondary")]
        v.addWidget(etykiety[2])
        v.addWidget(etykiety[3])
        if r["n_pending"]:
            czeka = _etykieta(i18n.t_plural("home.card.pending", r["n_pending"]), rola="warn")
            v.addWidget(czeka)
            etykiety.append(czeka)
        for lbl in etykiety:
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        karta.clicked.connect(
            lambda _c=False, oid=r["object_id"], canon=r["canon"]: self.teczka.emit(oid, canon))
        return karta

    # ---------------------------------------------------------------- zajętość, Popraw i Ostatnio

    def set_busy(self, busy):
        """Przebieg Dostawy: „Wydaj do WBPP" gaśnie jak „Wydaj obiekt…" paska Zbiorów - etap
        przepisuje `calibration` i rodowód, więc plan policzony w środku wydałby mastery sprzed i po
        przeliczeniu naraz. Reszta kafli to nawigacja i zostaje czynna; Przyjmij prowadzi wtedy na
        Dostawę z widocznym postępem, a nie do drugiego biegu.

        „Wciągnij z WBPP…” z menu „Więcej…” gaśnie tak samo: „Zamknij i przyjmij” okna żniw
        uruchamia łańcuch Dostawy, który w biegu odmówi, a wtedy rodowód dokładny wciągniętych
        stosów zostaje tylko w folderze wydania. Podpowiedź to zdanie odmowy złotej akcji;
        bramkę przed oknem trzyma i tak gospodarz (`PipelineView.powod_odmowy_biegu`)."""
        self.tile_wydaj.setEnabled(not busy)
        self.tile_wydaj.setToolTip(i18n.t("home.tile.release_busy") if busy
                                   else i18n.t("home.tile.release_tip"))
        self._zniwa_bieg = bool(busy)
        self._sync_zniwa()

    def set_writeback_busy(self, busy):
        """Zapis nagłówków do plików: „Wciągnij z WBPP…” gaśnie z tego samego powodu co w biegu
        Dostawy - łańcuch po „Zamknij i przyjmij” odmówiłby (`PipelineView.powod_odmowy_biegu`).
        Osobny stan, nie `set_busy`: koniec zapisu nie może zapalić pozycji w trwającym biegu."""
        self._zniwa_zapis = bool(busy)
        self._sync_zniwa()

    def _sync_zniwa(self):
        zniwa = self.akcje_wiecej[WIECEJ_ZNIWA]
        zniwa.setEnabled(not (self._zniwa_bieg or self._zniwa_zapis))
        zniwa.setToolTip(i18n.t("pipeline.refuse.delivery_running") if self._zniwa_bieg
                         else i18n.t("pipeline.refuse.writeback") if self._zniwa_zapis else "")

    def ustaw_popraw(self, n, powod=""):
        """Licznik kafla Popraw - ta sama liczba, co plakietka Porządków (gospodarz podaje ją z tego
        samego sygnału); przy zerze goły czasownik, jak goła plakietka. `None` = rachunek liczników
        jeszcze trwa (montaż z liczeniem w tle, AR-175): „Popraw · …” i podpowiedź, że liczę - goły
        czasownik znaczy „nic do poprawy”, a tego jeszcze nie wiadomo. `"!"` = pierwszy rachunek padł
        (AR-326): „Popraw · !” z podpowiedzią `powod` (zdanie błędu z Porządków) - liczby nie ma."""
        if n is None:
            self.tile_popraw.setText(i18n.t("home.tile.fix_count", n="…"))
            self.tile_popraw.setToolTip(i18n.t("busy.counting_tasks"))
            return
        if n == "!":
            self.tile_popraw.setText(i18n.t("home.tile.fix_count", n="!"))
            self.tile_popraw.setToolTip(powod)
            return
        self.tile_popraw.setText(i18n.t("home.tile.fix") if n == 0
                                 else i18n.t("home.tile.fix_count", n=n))
        self.tile_popraw.setToolTip(i18n.t("home.tile.fix_tip"))

    def pokaz_recepte(self, recepta):
        """Recepta ostatniego gestu ze strumienia Zbiorów (`grid.Recepta`); pusta zdejmuje ją
        z Domu i oddaje miejsce zdaniu z dziennika.

        DZIENNIK CZYTANY OD NOWA, gdy recepta znika albo Dom jest na ekranie. Recepta schodzi
        zwykle DLATEGO, że ktoś ją wykonał - a wtedy ostatnim gestem jest właśnie cofnięcie: zdanie
        wczytane przy wejściu na Dom mówiłoby „zapisano uwagę" obok paska, który mówi „cofnięto"
        (wizytacja, PL i EN). Dom niewidoczny i recepta wciąż żywa - odczyt czeka na wejście."""
        znika = self._recepta is not None and not recepta
        self._recepta = recepta if recepta else None
        if znika or self.isVisible():
            self._gest = self._gest_ostatnio()
        self._render_ostatnio()

    def _gest_ostatnio(self):
        """Gest, który opisuje „Ostatnio”: przy żywej recepcie z tożsamością (`Recepta.ts`, AR-94) -
        gest O TYM znaczniku, bo przycisk obok cofa właśnie jego, a nie ostatni gest w ogóle (po
        geście w Zbiorach i drugim w Porządkach zdanie opisywało Porządki). Bez recepty albo przy
        recepcie bez znacznika - ostatni gest ręki z dziennika."""
        ts = self._recepta.ts if self._recepta is not None else None
        gest = queries.last_hand_gesture(self.con, ts=ts)
        if gest is not None and "staging.discarded" in gest["verbs"]:
            # Liczba odrzuconych zmian z ładunku zdarzeń (AR-304) - `verbs` liczy zdarzenia.
            gest["discarded"] = queries.odrzucenia_szuflady(self.con, ts=gest["ts"], actor=gest["actor"])
        return gest

    def wstrzymaj_recepte(self, wstrzymana):
        """Blokada po wykonaniu członu (dwuklik to jeden gest) - stan trzyma gospodarz, wspólny
        z przyciskiem na pasku; tu tylko go odbijamy."""
        self._wstrzymana = bool(wstrzymana)
        self._render_ostatnio()

    def _render_ostatnio(self):
        self._render_wiersz_ostatnio()
        self._dopasuj_rzedy()            # wiersz pojawia się i znika - zmienia pion dla teczek

    def _render_wiersz_ostatnio(self):
        if self._recepta is not None:
            czlony = self._recepta.czlony
            # Najpierw CO się stało (dziennik), potem droga powrotu - sam przycisk mówi, jak
            # cofnąć, a nie co cofa.
            self.last_label.setText(
                zdanie_dziennika(self._gest, self._now()) + Recepta.SEPARATOR.rstrip()
                if self._gest is not None else i18n.t("home.last.label"))
            self.btn_recepta.setText(czlony[0].tekst)
            self.btn_recepta.setEnabled(czlony[0].wykonaj is not None and not self._wstrzymana)
            self.btn_recepta.setVisible(True)
            self.last_rest.setText(Recepta.SEPARATOR.join(c.tekst for c in czlony[1:]))
            self.last_rest.setVisible(len(czlony) > 1)
            self.ostatnio.setVisible(True)
            return
        self.btn_recepta.setVisible(False)
        self.last_rest.setVisible(False)
        if self._gest is None:
            self.last_label.setText("")
            self.ostatnio.setVisible(False)
            return
        self.last_label.setText(zdanie_dziennika(self._gest, self._now()))
        self.ostatnio.setVisible(True)
