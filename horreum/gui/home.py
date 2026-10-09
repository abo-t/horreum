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

„Co mam" i zdanie z dziennika liczą się synchronicznie (dwa krótkie SELECT-y, ~0,1 s razem na
żywej bazie), bo mają mówić prawdę w chwili wejścia na Dom - gest wykonany przed sekundą na innym
ekranie ma tu już stać.

OSTATNIO: RECEPTA ALBO DZIENNIK. Droga powrotu ostatniego gestu żyje dziś wyłącznie w pamięci
widoku Zbiorów (strumień `status_recipe`); Dom pokazuje TĘ SAMĄ receptę, którą dostaje pasek stanu,
a jej życie wyznacza wyłącznie ten strumień (pusta = zdjęta). Bez recepty w sesji zostaje zdanie
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

# Ile teczek mieści Dom - reszta jest o jedno zapytanie dalej, w Znajdź (stopka to mówi).
TECZKI_NA_DOMU = 9
KOLUMNY_TECZEK = 3

# Pozycje menu „Więcej…" - klucze sygnału `wiecej`; trasę każdej z nich zna gospodarz.
WIECEJ_PLANER = "planer"
WIECEJ_STANOWISKA = "stanowiska"
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


def zdanie_gestu(gest):
    """Co zrobił gest z dziennika (`queries.last_hand_gesture`) - bez daty. Jeden znany czasownik
    = jego zdanie; inaczej zdanie ogólne z liczbą WSZYSTKICH eventów gestu."""
    if len(gest["verbs"]) == 1:
        (verb, n), = gest["verbs"].items()
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
    failed = Signal(int, str)           # (generacja, komunikat)
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
            self.failed.emit(self._gen, f"{type(exc).__name__}: {exc}")
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
        self.karty = []                  # karty teczek na ekranie (QPushButton z danymi w `teczka_row`)
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
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        zewn.addWidget(scroll)
        tresc = QWidget()
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
        for klucz, tekst in ((WIECEJ_PLANER, i18n.t("home.more.planner")),
                             (WIECEJ_STANOWISKA, i18n.t("home.more.sites")),
                             (WIECEJ_NAZWY, i18n.t("home.more.rename")),
                             (WIECEJ_MAKRA, i18n.t("home.more.macro")),
                             (WIECEJ_PERSPEKTYWY, i18n.t("home.more.perspectives")),
                             (WIECEJ_DOSTAWA, i18n.t("home.more.advanced_intake")),
                             (WIECEJ_KLASYCZNE, i18n.t("home.more.classic"))):
            akcja = menu.addAction(tekst)
            akcja.triggered.connect(lambda _c=False, k=klucz: self.wiecej.emit(k))
            self.akcje_wiecej[klucz] = akcja
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
        self.teczki_status = _etykieta(rola="secondary")
        self.teczki_status.setWordWrap(True)
        v.addWidget(self.teczki_status)
        siatka = QWidget()
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
        self._gest = queries.last_hand_gesture(self.con)
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

    @Slot(int, str)
    def _on_teczki_failed(self, gen, msg):
        if gen != self._gen:
            return
        self._pokazana_gen = gen
        self.teczki_status.setText(i18n.t("home.folders.failed", msg=msg))
        self.teczki_status.setVisible(True)

    # ---------------------------------------------------------------- teczki

    def _render_teczki(self, rows):
        for karta in self.karty:
            self.teczki_siatka.removeWidget(karta)
            karta.deleteLater()
        self.karty = []
        for i, r in enumerate(rows[:TECZKI_NA_DOMU]):
            karta = self._karta(r)
            self.teczki_siatka.addWidget(karta, i // KOLUMNY_TECZEK, i % KOLUMNY_TECZEK)
            self.karty.append(karta)
        self.teczki_status.setText("" if rows else i18n.t("home.folders.empty"))
        self.teczki_status.setVisible(not rows)
        reszta = len(rows) - TECZKI_NA_DOMU
        self.btn_teczki_wiecej.setVisible(reszta > 0)
        if reszta > 0:
            self.btn_teczki_wiecej.setText(i18n.t_plural("home.folders.more", reszta))

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
        Dostawę z widocznym postępem, a nie do drugiego biegu."""
        self.tile_wydaj.setEnabled(not busy)
        self.tile_wydaj.setToolTip(i18n.t("home.tile.release_busy") if busy
                                   else i18n.t("home.tile.release_tip"))

    def ustaw_popraw(self, n):
        """Licznik kafla Popraw - ta sama liczba, co plakietka Porządków (gospodarz podaje ją z tego
        samego sygnału); przy zerze goły czasownik, jak goła plakietka."""
        self.tile_popraw.setText(i18n.t("home.tile.fix") if n == 0
                                 else i18n.t("home.tile.fix_count", n=n))

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
            self._gest = queries.last_hand_gesture(self.con)
        self._render_ostatnio()

    def wstrzymaj_recepte(self, wstrzymana):
        """Blokada po wykonaniu członu (dwuklik to jeden gest) - stan trzyma gospodarz, wspólny
        z przyciskiem na pasku; tu tylko go odbijamy."""
        self._wstrzymana = bool(wstrzymana)
        self._render_ostatnio()

    def _render_ostatnio(self):
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
