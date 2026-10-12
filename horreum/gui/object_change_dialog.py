r"""Okno „Zmień obiekt…” i „Uzgodnij pliki…” - podgląd i wykonanie gestu zmiany obiektu RAZEM
z plikiem (AR-17 krok 3, decyzja `D-1011-5`).

JEDNO OKNO, TRZY WEJŚCIA, JEDEN SILNIK. „Zmień obiekt…” (Zbiory → Obiekt ▾) niesie cel
(`object_change.ObjectTarget`): baza dostaje nowy obiekt ręką, plik jedzie do folderu nowego
obiektu, a karta `OBJECT` dostaje jego formę. „Uzgodnij pliki…” (Porządki → perspektywa „Plik nie
zgadza się z obiektem”) idzie z `target=None`: obiekt w bazie zostaje, plik dogania ten, który
klatka już ma. Plan liczy Qt-wolny `object_change.plan_object_change` nad read-modelem
`queries.object_change_rows`; okno pokazuje DOKŁADNIE ten plan i ten sam obiekt idzie do stagingu
(`repo.stage_object_change`) - podgląd nie jest drugą regułą, tylko tym samym zdaniem
powiedzianym przed kliknięciem. Trzecie wejście (`run_id`, Porządki → „Przerwane zmiany obiektu”,
AR-121) otwiera okno na przebiegu z bazy (`queries.object_change_run_view`) bez planu: lista ze
stanem pozycji, „Dokończ (N)” i „Cofnij” - te same operacje uchwytu co po przerwaniu w oknie.

NAZWA PLIKU (D-1011-6 `O2`): zmienia się wyłącznie człon obiektu na początku nazwy, reszta zostaje
znak w znak - okno mówi tę regułę jedną linijką, bo z listy folderów jej nie widać.

PLAN POZA WĄTKIEM OKNA. Planer czyta dysk (czy cel istnieje, jaką pisownię ma istniejący katalog -
`R:` nie rozróżnia wielkości liter, baza tak), a dysk bywa udziałem SMB: kilkaset pytań o katalogi
na wątku GUI to sekundy martwego okna. `PlanWorker` otwiera własne połączenie po ścieżce bazy
(połączenie nie przechodzi między wątkami); baza bez pliku i testy liczą inline (`off_thread`).

WYKONANIE JEDNĄ OPERACJĄ UCHWYTU (`WritebackRunner`, `_OPS["object_change"]`): rdzeń idzie per
pozycja baza → przeniesienie → karta, „razem albo wcale”. Dwa starty uchwytu zwolniłyby między sobą
mutex „zapis → Dostawa”, więc okno nie składa gestu z kilku operacji. „Cofnij” żyje do zamknięcia
okna (`undo_object_change`, wzorzec okien kart); przebieg leży w bazie, więc cofnięcie przeżywa też
awarię procesu (droga dev poza oknem). Zamknięcie w biegu = żądanie anulowania (`refuse_close`), a po
przerwaniu okno oferuje „Dokończ” tego samego przebiegu obok „Cofnij”.

SZEROKOŚĆ: kanon minimalnego ekranu to 1920×1080 logicznych. Ścieżki archiwum bywają dłuższe niż
ekran, więc lista ich nie zawija ani nie rozpycha okna: ścieżka pod korzeniem archiwum, elizja
w środku (początek drzewa i nazwa pliku zostają w kadrze), pełna ścieżka w podpowiedzi.
"""
from __future__ import annotations

import ntpath
import sqlite3

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from horreum import db, object_change, repo, resolver
from horreum.gui import i18n, queries

# Kolumny listy pozycji: plik dziś, plik po zmianie, karta `OBJECT` stara → nowa i - po biegu
# zapisu albo cofnięcia - status pozycji z wyniku rdzenia (w podglądzie schowana).
_COL_STARA, _COL_NOWA, _COL_KARTA, _COL_STATUS = range(4)
# Lista pominięć: powód (dzieci: ścieżki) i liczba.
_COL_POWOD, _COL_ILE = range(2)
# Wysokość listy pominięć: kilka powodów naraz, reszta za suwakiem - pominięcia nie mogą zabrać
# liście pozycji pionu, bo to ona jest przedmiotem decyzji.
_POMINIECIA_MAX_PX = 150
# Rozmiar startowy okna. Szerokość z zapasem pod kanon 1920 logicznych; resztę dają suwaki
# i elizja, nie rozpychanie.
_START_W, _START_H = 1100, 640
# Status pozycji przebiegu z bazy (wejście z Porządków) → klucz katalogu: ta sama mowa co po biegu.
_STATUS_POZYCJI = {"pending": "objchg.st.pending", "applied": "objchg.st.done",
                   "blocked": "objchg.st.blocked", "failed": "objchg.st.failed",
                   "skipped": "objchg.st.skipped", "undone": "objchg.st.undone"}
# Rozszerzenie XISF: zapis karty w miejscu umie tam także DOPISAĆ kartę; FITS w miejscu wyłącznie
# podmienia istniejącą (`writeback._fits_inplace_plan`), więc dopisanie przepisuje cały plik.
_XISF = ".xisf"


def policz_plan(con, frame_ids, *, target):
    """Plan gestu dla `frame_ids` → `(ObjectChangePlan, korzeń archiwum | None)`. ZERO ZAPISU.

    Jeden rachunek dla wątku tła i trybu inline: read-model (`queries.object_change_rows`), korzeń
    archiwum (`resolver.library_root_from_db` - kotwica pozycji obiektu w ścieżce), indeks lokacji
    bazy (`queries.location_lookup` - kolizja celu z inną lokacją) i Qt-wolny planer. Read-model
    dostaje cel, bo forma karty i bramka karty zależą od kanonu celu (przy „Uzgodnij" - od
    bieżącego). Korzeń wraca razem z planem, bo okno skraca nim ścieżki."""
    korzen = resolver.library_root_from_db(con)
    rows = queries.object_change_rows(con, list(frame_ids), target=target)
    plan = object_change.plan_object_change(
        rows, target=target, library_root=korzen, location_at=queries.location_lookup(con))
    return plan, korzen


class PlanWorker(QObject):
    """Plan gestu poza wątkiem okna (wzorzec `DryWorker`/`TeczkiWorker`). Otwiera WŁASNE połączenie
    po `db_path`; tryb inline (`db_path` pusty) dostaje żywe `con` wołającego i biegnie
    synchronicznie. Wynik niesie generację startu - okno odrzuca stale (plan sprzed cofnięcia)."""

    done = Signal(int, object)          # (generacja, (plan, korzeń))
    failed = Signal(int, str)           # (generacja, komunikat)
    finished = Signal()

    def __init__(self, db_path, gen, *, frame_ids, target, con=None):
        super().__init__()
        self._db_path = db_path
        self._con = con
        self._gen = gen
        self._frame_ids = list(frame_ids)
        self._target = target

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
            return policz_plan(con, self._frame_ids, target=self._target)
        finally:
            if own:
                con.close()


def sciezka_pod_korzeniem(path, korzen):
    """`R:\\ASTRO_\\LIGHTS\\IC405\\…` → `LIGHTS\\IC405\\…` - ścieżka bez korzenia archiwum, gdy pod
    nim leży (porównanie bez wielkości liter: semantyka `R:`); inaczej bez zmian. Korzeń jest ten sam
    w każdym wierszu, więc niczego nie mówi, a zjada szerokość kolumny."""
    if not path or not korzen:
        return path or ""
    k = korzen.rstrip("\\/")
    if path[:len(k)].casefold() == k.casefold() and path[len(k):len(k) + 1] in ("\\", "/"):
        return path[len(k) + 1:]
    return path


def ma_robote(item):
    """Czy pozycja planu cokolwiek zmienia: plik, karta albo obiekt w bazie."""
    return bool(item.new_path or item.card_op or item.object_change)


def inny_katalog(item):
    """Czy przeniesienie zmienia KATALOG pliku (porównanie fizyczne `object_change.path_key`: bez
    wielkości liter, jak `R:`), a nie tylko jego nazwę w tym samym folderze."""
    return (item.new_path is not None
            and object_change.path_key(ntpath.dirname(item.old_path))
            != object_change.path_key(ntpath.dirname(item.new_path)))


def bez_zmian(skip):
    """Pominięcie planu, które jest pozycją BEZ ZMIAN (plik w folderze obiektu, nazwa i karta zgodne),
    a nie odmową - liczy się w „bez zmian”, nie w „pominie”. Rozpoznane po kodzie planera."""
    return skip.code == object_change.SKIP_UNCHANGED


def liczby_planu(plan):
    """Liczby podglądu z planu - te same, które padną na przycisku i w zdaniu przed zapisem.
    Przeniesienie liczy się osobno do innego folderu i jako nowa nazwa w tym samym folderze (człon
    obiektu w nazwie zmienia się także plikowi, który folderu nie zmienia - stos stoi w folderze
    obiektu pod starą nazwą). Katalogi liczone RAZ na ścieżkę (kilka plików jedzie do jednego
    nowego folderu), bez wielkości liter, bo `R:` jej nie rozróżnia."""
    items = plan.items
    bez = sum(1 for s in plan.skipped if bez_zmian(s))
    return {
        "robota": sum(1 for it in items if ma_robote(it)),
        "folder": sum(1 for it in items if inny_katalog(it)),
        "nazwa": sum(1 for it in items if it.new_path and not inny_katalog(it)),
        "karty": sum(1 for it in items if it.card_op),
        "katalogi": len({d.casefold() for it in items for d in it.mkdirs}),
        # Katalogi źródłowe, które po całym planie zostaną puste - sterownik je usunie; mówione
        # przed kliknięciem, bo znikający folder to skutek, którego lista plików nie pokazuje.
        "usunie": len({object_change.path_key(d) for d in plan.rmdirs}),
        "obiekt": sum(1 for it in items if it.object_change),
        "bez_zmian": sum(1 for it in items if not ma_robote(it)) + bez,
        "pominie": len(plan.skipped) - bez,
    }


def zdanie_wyniku_zmiany(res, *, cofniecie=False):
    """Zdanie wyniku przebiegu (`writeback.ObjectChangeResult`) - wspólna gramatyka powierzchni
    zapisu (`wb_worker.zdanie_wyniku_zapisu`: liczba, blokady, błędy, pominięcia, pierwszy powód)
    plus to, czego zwykły commit nie ma:

      * pozycje `applied` z powodem: przy zapisie karta SPADŁA na drogę atomową (cały plik
        przepisany - powód z prefiksem rdzenia), każdy inny powód to uwaga (przy cofnięciu np. nowsza
        decyzja ręki w bazie) - liczba i pierwszy powód, bo „N zmienionych” samo by to ukryło;
      * katalogi założone i usunięte, katalogi o niepewnej własności (zostają do oka);
      * blokada pliku zmienionego od ostatniego skanu - z receptą (skan w Dostawie, potem ponów);
      * numer przebiegu - po zamknięciu okna jedyny uchwyt do dokończenia albo cofnięcia
        (`horreum object-change finish|undo DB RUN_ID`), jak `commit_id` w oknach kart;
      * ostrzeżenia rdzenia."""
    from horreum import writeback          # lazy: `writeback` i `wb_worker` ciągną astropy
    from horreum.gui.wb_worker import (
        bez_prefiksu_spadku, spadek_na_droge_atomowa, zdanie_wyniku_zapisu)
    msg = (zdanie_wyniku_zapisu(res, "objchg.res.undone") if cofniecie
           else zdanie_wyniku_zapisu(res, "objchg.res.applied"))
    z_powodem = [fr for fr in res.applied if fr.reason and fr not in res.withheld]
    atomowe = ([] if cofniecie
               else [fr for fr in z_powodem if spadek_na_droge_atomowa(fr)])
    uwagi = [fr for fr in z_powodem if fr not in atomowe]
    if cofniecie and res.withheld:                       # AR-82: karta wróciła, zeznanie nie
        msg += " · " + i18n.t("grid.wb.undo_withheld", n=len(res.withheld))
    if atomowe:
        msg += i18n.t("wb.inplace_fallback", n=len(atomowe),
                      reason=bez_prefiksu_spadku(atomowe[0].reason))
    if uwagi:
        msg += i18n.t("objchg.res.notes", n=len(uwagi), note=uwagi[0].reason)
    if res.dirs_created or res.dirs_removed:
        msg += i18n.t("objchg.res.dirs", created=res.dirs_created, removed=res.dirs_removed)
    if res.dirs_uncertain:
        msg += i18n.t_plural("objchg.res.dirs_uncertain", res.dirs_uncertain)
    od_skanu = sum(1 for fr in res.blocked if fr.code == writeback.CODE_CHANGED_SINCE_SCAN)
    if od_skanu:
        msg += i18n.t_plural("objchg.res.rescan", od_skanu)
    if res.cancelled:
        msg += i18n.t("wb.cancelled_note")
    msg += i18n.t("objchg.res.run", run_id=res.run_id)
    for ostrzezenie in res.warnings:
        msg += "\n" + ostrzezenie
    return msg


def ruszyl_cokolwiek(res):
    """Czy przebieg zostawił coś do cofnięcia. `failed` liczy się także: błąd pozycji bywa
    rozjazdem po częściowym kroku (plik przeniesiony, karta nie). Katalogi - wyłącznie gdy zostały
    założone ponad te, które ten sam przebieg sprzątnął (odmowa po założeniu katalogu zostawia
    przebieg bez zmian na dysku, a „Cofnij” byłoby obietnicą bez pokrycia)."""
    return bool(res.applied or res.failed or res.withheld or res.commit_ids
                or res.dirs_created > res.dirs_removed)


class ObjectChangeDialog(QDialog):
    """Podgląd i wykonanie gestu zmiany obiektu (`target`) albo uzgodnienia plików (`target=None`)
    na klatkach `frame_ids` - albo (`run_id`) wznowienie przerwanego przebiegu z bazy: wtedy cel
    i klatki bierze z przebiegu (`queries.object_change_run_view`), a `frame_ids`/`target` nie
    przychodzą. Przebieg, którego nie ma, to błąd wołającego (EXPECT) - wiersz Porządków liczy
    z tej samej bazy.

    Enter NIE uruchamia gestu: przyciskiem domyślnym jest „Zamknij” (zapis do plików idzie wyłącznie
    świadomym kliknięciem).

    Cel z formą karty `None` (kanon znany tylko z aliasu) jest ODMOWĄ PRZED PLANEM - obietnica
    „karta i folder razem” nie ma czym się spełnić. Odmowę mówi wołający (wybór celu), tu stoi
    asercja: okno z takim celem to błąd kolejności (EXPECT).

    `changed` = zapis albo cofnięcie doszło do skutku (gospodarz odświeża zbiór i Porządki);
    `busy_changed` = okno pisze do plików (mutex drugiej powierzchni, D-PD-3). `summary` = ostatnie
    zdanie wyniku - po zamknięciu okna gospodarz kładzie je na pasek."""

    changed = Signal()
    busy_changed = Signal(bool)

    def __init__(self, con, *, frame_ids=None, target=None, run_id=None, now_fn, db_path=None,
                 off_thread=True, parent=None):
        super().__init__(parent)
        # Lazy jak w oknach kart: `wb_worker` ciągnie `writeback` → astropy.
        from horreum.gui.wb_worker import WritebackRunner

        przebieg = None
        if run_id is not None:
            assert frame_ids is None and target is None, (
                "wznowienie przebiegu bierze klatki i cel z bazy, nie od wołającego")
            przebieg = queries.object_change_run_view(con, run_id)
            assert przebieg is not None, f"brak przebiegu zmiany obiektu {run_id!r}"
            frame_ids, target = przebieg["frame_ids"], przebieg["target"]
        assert target is None or target.card_form is not None, (
            "cel bez formy karty OBJECT - gest odmawia go przed planem (wołający)")
        self.con = con
        self._frame_ids = list(frame_ids)
        self._target = target
        self._przebieg = przebieg        # wejście z Porządków: przebieg z bazy, bez planu
        self._zamknij_po_planie = None   # wynik zamknięcia odłożony do końca planu w biegu
        self._now = now_fn
        self._db_path = db_path if db_path is not None else queries.db_path_of(con)
        self._off_thread = off_thread
        self._plan = None
        self._korzen = None
        self._gen = 0
        self._plan_worker = None
        self._plan_thread = None
        self._run_id = None          # przebieg ze stagingu - cel „Cofnij” i „Dokończ”
        self._do_cofniecia = False   # przebieg coś zmienił, a cofnięcie jeszcze nie przeszło
        self._domkniety = False      # plan wykonany - drugi zapis nie ma czego robić do „Cofnij”
        self._pozostalo = 0          # pozycje nieprzetworzone po przerwaniu (droga „Dokończ”)
        # Przebieg `staged` do domknięcia - „Dokończ” także przy zerze czekających (awaria po
        # ostatniej pozycji, przed domknięciem przebiegu: `can_finish` read-modelu).
        self._dokonczenie = False
        # Stan przerwanego przebiegu, o którym mówi nagłówek i opis okna z Porządków: `staged`
        # (zapis do dokończenia), `undoing` (cofanie przerwane), `failed` (pozycja z błędem) albo
        # None (przebieg domknięty albo okno liczy nowy plan) - `_opisz_stan`.
        self._stan_przebiegu = None
        self._status_wiersza = {}    # location_id → ostatni status wiersza (z bazy albo z biegu)
        self._w_biegu = 0            # z iloma pozycjami ruszył ostatni bieg zapisu
        # LISTA PO BIEGU MÓWI O WYNIKU, NIE O PLANIE: `_wynik_na_liscie` = lista pokazuje wynik
        # zapisu albo cofnięcia (status per wiersz), a nowy plan liczy się dopiero na prośbę
        # („Policz plan ponownie”) - inaczej powody blokad znikałyby razem ze starym planem.
        # `_jest` = gdzie okno wie, że plik stoi (location_id → ścieżka), po każdym biegu z wyniku.
        self._wynik_na_liscie = False
        self._jest = {}
        self._wiersze = {}           # location_id → wiersz listy pozycji
        self._pipeline_busy = False
        self.summary = ""
        self._runner = WritebackRunner(self._db_path, now_fn=now_fn, parent=self)
        self._runner.async_ok = off_thread
        self._runner.busy_changed.connect(self.busy_changed)
        # Koniec biegu w trybie wątku dochodzi PO slocie wyniku (sprzątanie wątku), więc stan akcji
        # liczy się jeszcze raz, gdy uchwyt naprawdę jest wolny.
        self._runner.busy_changed.connect(lambda zajety: zajety or self._sync_akcji())
        self.setWindowTitle(i18n.t("objchg.title_change") if target is not None
                            else i18n.t("objchg.title_align"))
        self._build_ui()
        self.resize(_START_W, _START_H)
        if przebieg is not None:
            self._wczytaj_przebieg(przebieg)
        else:
            self._licz_plan()

    @property
    def frame_ids(self):
        """Klatki okna - z zaznaczenia albo (wejście z Porządków) z przebiegu w bazie."""
        return tuple(self._frame_ids)

    # ---------------------------------------------------------------- budowa UI
    def _build_ui(self):
        lay = QVBoxLayout(self)
        self.head = QLabel("")
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.opis = QLabel("")
        self.opis.setWordWrap(True)
        self.opis.setProperty("role", "secondary")
        lay.addWidget(self.opis)
        self._opisz_stan()
        # Reguła nazwy (D-1011-6 `O2`) - z listy folderów jej nie widać, a decyduje, czy nazwa
        # pliku się zmieni.
        self.name_rule = QLabel(i18n.t("objchg.name_rule"))
        self.name_rule.setWordWrap(True)
        self.name_rule.setProperty("role", "secondary")
        lay.addWidget(self.name_rule)

        self.items_tree = QTreeWidget()
        self.items_tree.setColumnCount(4)
        self._naglowki(po_biegu=False)
        self.items_tree.setRootIsDecorated(False)
        self.items_tree.setUniformRowHeights(True)
        self.items_tree.setSelectionMode(QAbstractItemView.NoSelection)
        # ELIZJA W ŚRODKU, NIE ZAWIJANIE: o tym, gdzie plik leży, mówi początek drzewa (folder
        # obiektu), a o tym, który to plik - koniec. Środek (konfiguracja, filtr) jest tym samym
        # po obu stronach strzałki.
        self.items_tree.setTextElideMode(Qt.ElideMiddle)
        hdr = self.items_tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(_COL_STARA, QHeaderView.Stretch)
        hdr.setSectionResizeMode(_COL_NOWA, QHeaderView.Stretch)
        hdr.setSectionResizeMode(_COL_KARTA, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_STATUS, QHeaderView.Stretch)
        self.items_tree.setColumnHidden(_COL_STATUS, True)
        lay.addWidget(self.items_tree, 1)

        self.warnings = QLabel("")
        self.warnings.setWordWrap(True)
        self.warnings.setProperty("role", "warn")
        self.warnings.setVisible(False)
        lay.addWidget(self.warnings)

        self.skipped_head = QLabel("")
        self.skipped_head.setVisible(False)
        lay.addWidget(self.skipped_head)
        self.skipped_tree = QTreeWidget()
        self.skipped_tree.setColumnCount(2)
        self.skipped_tree.setHeaderLabels([i18n.t("objchg.col.reason"), i18n.t("objchg.col.n")])
        self.skipped_tree.setUniformRowHeights(True)
        self.skipped_tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.skipped_tree.setTextElideMode(Qt.ElideMiddle)
        shdr = self.skipped_tree.header()
        shdr.setStretchLastSection(False)
        shdr.setSectionResizeMode(_COL_POWOD, QHeaderView.Stretch)
        shdr.setSectionResizeMode(_COL_ILE, QHeaderView.ResizeToContents)
        self.skipped_tree.itemExpanded.connect(lambda _it: self._dopasuj_pominiecia())
        self.skipped_tree.itemCollapsed.connect(lambda _it: self._dopasuj_pominiecia())
        self.skipped_tree.setVisible(False)
        lay.addWidget(self.skipped_tree)

        self.counts = QLabel("")
        self.counts.setWordWrap(True)
        lay.addWidget(self.counts)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.status)
        self.error = QLabel("")
        self.error.setProperty("role", "error")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)

        actions = QHBoxLayout()
        self.action_btn = QPushButton("")
        # Złota akcja okna: WAGA, nie kolor (wzorzec okien kart).
        _f = self.action_btn.font(); _f.setBold(True); self.action_btn.setFont(_f)
        self.action_btn.clicked.connect(self._on_action)
        actions.addWidget(self.action_btn)
        self.undo_btn = QPushButton(i18n.t("objchg.undo_btn"))
        self.undo_btn.setVisible(False)
        self.undo_btn.clicked.connect(self._on_undo)
        actions.addWidget(self.undo_btn)
        actions.addStretch(1)
        self.close_btn = QPushButton(i18n.t("objchg.close_btn"))
        self.close_btn.clicked.connect(self.reject)
        actions.addWidget(self.close_btn)
        lay.addLayout(actions)
        # ENTER NIE PISZE DO PLIKÓW: `QDialog` robi przycisk z fokusem domyślnym (`autoDefault`),
        # więc Enter po kliknięciu w listę uruchamiałby gest. Domyślny jest „Zamknij”.
        for btn in (self.action_btn, self.undo_btn):
            btn.setAutoDefault(False)
            btn.setDefault(False)
        self.close_btn.setDefault(True)

    def _naglowki(self, *, po_biegu):
        """Nagłówki listy: w podglądzie „Plik dziś / Po zmianie”, po biegu „Było / Jest / Status” -
        lista po biegu opisuje, co SIĘ STAŁO, a nie, co miało się stać."""
        if po_biegu:
            etykiety = [i18n.t("objchg.col.was"), i18n.t("objchg.col.is"),
                        i18n.t("objchg.col.card"), i18n.t("objchg.col.status")]
        else:
            etykiety = [i18n.t("objchg.col.old"), i18n.t("objchg.col.new"),
                        i18n.t("objchg.col.card"), i18n.t("objchg.col.status")]
        self.items_tree.setHeaderLabels(etykiety)

    def _opisz_stan(self):
        """Nagłówek i opis okna mówią o tym, co zrobią przyciski TERAZ (wizytacja W1/W2): przerwany
        przebieg z Porządków ma nagłówek „Przerwany przebieg…” i opis drogi wyjścia ze swojego
        stanu (`staged` - „Dokończ” albo „Cofnij”, `undoing` - „Cofnij” dokończy cofanie, `failed` -
        „Cofnij” cofa cały przebieg); przebieg domknięty albo nowy plan na tych klatkach - zwykły
        nagłówek gestu. Wołane z `_sync_akcji`, więc nadąża za każdym biegiem i planem."""
        n = len(self._frame_ids)
        if self._stan_przebiegu is not None:
            run_id = self._przebieg["run_id"]
            head = (i18n.t_plural("objchg.head_resume_change", n, run_id=run_id,
                                  canon=self._target.canon, card=self._target.card_form)
                    if self._target is not None
                    else i18n.t_plural("objchg.head_resume_align", n, run_id=run_id))
            opis = i18n.t({"staged": "objchg.explain_resume",
                           "undoing": "objchg.explain_resume_undoing",
                           "failed": "objchg.explain_resume_failed"}[self._stan_przebiegu])
        elif self._target is not None:
            head = i18n.t_plural("objchg.head_change", n, canon=self._target.canon,
                                 card=self._target.card_form)
            opis = i18n.t("objchg.explain_change")
        else:
            head = i18n.t_plural("objchg.head_align", n)
            opis = i18n.t("objchg.explain_align")
        self.head.setText(head)
        self.opis.setText(opis)

    # ---------------------------------------------------------------- plan (wątek tła albo inline)
    def _licz_plan(self):
        """Zamów plan na BIEŻĄCYM stanie (otwarcie okna, po cofnięciu). Nowa generacja odrzuca
        wynik planu, który mógłby jeszcze wisieć w drodze."""
        self._gen += 1
        self._plan = None
        self._wynik_na_liscie = False
        self._stan_przebiegu = None        # nowy plan na tych klatkach - nie przebieg z Porządków
        self.error.clear()
        # Faza planu w wierszu LICZB, nie w zdaniu wyniku: plan po cofnięciu liczy się, gdy zdanie
        # cofnięcia ma jeszcze stać - liczby i tak zastąpi wynik planu.
        self.counts.setText(i18n.t("objchg.planning"))
        worker = PlanWorker(self._db_path, self._gen, frame_ids=self._frame_ids,
                            target=self._target,
                            con=None if (self._off_thread and self._db_path) else self.con)
        worker.done.connect(self._on_plan_done)
        worker.failed.connect(self._on_plan_failed)
        self._plan_worker = worker
        if self._off_thread and self._db_path:
            self._plan_thread = QThread(self)
            worker.moveToThread(self._plan_thread)
            self._plan_thread.started.connect(worker.run)
            worker.finished.connect(self._plan_thread.quit)
            self._plan_thread.finished.connect(self._cleanup_plan_thread)
            self._sync_akcji()
            self._plan_thread.start()
        else:
            try:
                worker.run()                    # inline: done/failed lecą direct = synchronicznie
            finally:
                self._plan_worker = None
            self._sync_akcji()

    def _cleanup_plan_thread(self):
        # wait() PRZED thread.deleteLater() - ten sam deadlock GIL × ~QThread co w
        # `WritebackRunner._cleanup` (komentarz tam).
        if self._plan_thread is None:
            return
        self._plan_worker.deleteLater(); self._plan_thread.wait(); self._plan_thread.deleteLater()
        self._plan_worker = None; self._plan_thread = None
        if self._zamknij_po_planie is not None:
            # Zamknięcie zażądane w trakcie planu (okno już schowane) - wątek skończył, więc teraz.
            wynik, self._zamknij_po_planie = self._zamknij_po_planie, None
            self.done(wynik)
            return
        self._sync_akcji()

    @Slot(int, object)
    def _on_plan_done(self, gen, payload):
        if gen != self._gen:
            return                              # plan sprzed nowszego zamówienia
        self._plan, self._korzen = payload
        self._wypelnij()
        self._sync_akcji()

    @Slot(int, str)
    def _on_plan_failed(self, gen, msg):
        if gen != self._gen:
            return
        self.counts.setText("")
        self.error.setText(i18n.t("objchg.err.plan", msg=msg))
        self._sync_akcji()

    def _wypelnij(self):
        """Plan → lista pozycji, ostrzeżenia, pominięcia (pogrupowane po powodzie) i liczby."""
        plan = self._plan
        self.items_tree.clear()
        self._naglowki(po_biegu=False)
        self.items_tree.setColumnHidden(_COL_STATUS, True)
        self._wiersze = {}
        self._status_wiersza = {}       # nowy plan: wiersze bez historii biegu
        self._jest = {it.location_id: it.old_path for it in plan.items}
        for it in plan.items:
            stara = sciezka_pod_korzeniem(it.old_path, self._korzen)
            nowa = (sciezka_pod_korzeniem(it.new_path, self._korzen) if it.new_path
                    else i18n.t("objchg.no_move"))
            w = QTreeWidgetItem([stara, nowa, self._tekst_karty(it.card_op, it.card_old,
                                                                it.card_new, it.old_path)])
            w.setToolTip(_COL_STARA, it.old_path)
            w.setToolTip(_COL_NOWA, it.new_path or i18n.t("objchg.no_move"))
            if it.mkdirs:
                w.setToolTip(_COL_NOWA, (it.new_path or "") + "\n"
                             + i18n.t("objchg.mkdirs_tip", dirs="\n".join(it.mkdirs)))
            w.setData(_COL_STARA, Qt.UserRole, it.frame_id)
            self.items_tree.addTopLevelItem(w)
            self._wiersze[it.location_id] = w

        ostrzezenia = [o.text for o in plan.warnings]
        self.warnings.setText("\n".join(ostrzezenia))
        self.warnings.setVisible(bool(ostrzezenia))

        self.skipped_tree.clear()
        grupy = {}
        # Pozycje „bez zmian” planer oddaje jako pominięcia, ale odmową nie są - stoją w liczbach
        # („bez zmian: N”), a lista pominięć niesie wyłącznie to, czego gest NIE zrobi z powodu.
        pominiete = [s for s in plan.skipped if not bez_zmian(s)]
        for s in pominiete:
            grupy.setdefault(s.reason, []).append(s)
        # Najliczniejszy powód na górze - 300 plików z jednym powodem to jeden wiersz, nie 300.
        for powod, lista in sorted(grupy.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            g = QTreeWidgetItem([powod, str(len(lista))])
            g.setToolTip(_COL_POWOD, powod)
            for s in lista:
                d = QTreeWidgetItem([sciezka_pod_korzeniem(s.path, self._korzen), ""])
                d.setToolTip(_COL_POWOD, s.path)
                g.addChild(d)
            self.skipped_tree.addTopLevelItem(g)
        self.skipped_head.setText(i18n.t_plural("objchg.skipped_head", len(pominiete)))
        self.skipped_head.setVisible(bool(pominiete))
        self.skipped_tree.setVisible(bool(pominiete))
        self._dopasuj_pominiecia()
        self.counts.setText(i18n.t("objchg.counts", **liczby_planu(plan)))
        self.counts.setToolTip(i18n.t("objchg.rmdirs_tip", dirs="\n".join(plan.rmdirs))
                               if plan.rmdirs else "")
        self.counts.setVisible(True)

    def _wczytaj_przebieg(self, przebieg):
        """Wejście z Porządków (AR-121): lista z bazy w mowie listy po biegu - „Było” = ścieżka
        z podglądu, „Jest” = gdzie lokacja stoi teraz, status pozycji z powodem; karta = wpis
        stagingu tego przebiegu (pozycja bez wpisu kartą nie płaciła - kolumna milczy); pozycja
        czekająca mówi, DOKĄD pojedzie plik - na tym człowiek decyduje o zapisie. Stan akcji jak po
        przerwanym biegu w oknie: „Dokończ” przy przebiegu `staged` (z liczbą czekających, także
        przy zerze), „Cofnij” cofa cały przebieg. Planu nie ma - świeży liczy się dopiero po
        pełnym cofnięciu („Policz plan ponownie”, na klatkach przebiegu)."""
        self._run_id = przebieg["run_id"]
        self._pozostalo = przebieg["pending"]
        self._dokonczenie = przebieg["can_finish"]
        self._stan_przebiegu = {"staged": "staged", "undoing": "undoing"}.get(przebieg["status"],
                                                                              "failed")
        self._do_cofniecia = True
        self._domkniety = True
        self._wynik_na_liscie = True
        self._korzen = resolver.library_root_from_db(self.con)
        self._naglowki(po_biegu=True)
        self.items_tree.setColumnHidden(_COL_STATUS, False)
        for it in przebieg["items"]:
            if it["status"] == "pending" and it["new_path"]:
                status = i18n.t("objchg.st.pending_to",
                                path=sciezka_pod_korzeniem(it["new_path"], self._korzen))
            else:
                status = i18n.t(_STATUS_POZYCJI[it["status"]])
            if it["reason"]:
                status += i18n.t("objchg.st.reason", reason=it["reason"])
            self._status_wiersza[it["location_id"]] = status
            karta = (self._tekst_karty(it["card_op"], it["card_old"], it["card_new"],
                                       it["old_path"]) if it["card_op"] else "")
            w = QTreeWidgetItem([sciezka_pod_korzeniem(it["old_path"], self._korzen),
                                 sciezka_pod_korzeniem(it["path"], self._korzen), karta, status])
            w.setToolTip(_COL_STARA, it["old_path"])
            w.setToolTip(_COL_NOWA, it["path"])
            w.setToolTip(_COL_STATUS, status)
            w.setData(_COL_STARA, Qt.UserRole, it["frame_id"])
            self.items_tree.addTopLevelItem(w)
            self._wiersze[it["location_id"]] = w
            self._jest[it["location_id"]] = it["path"]
        self.counts.setVisible(False)
        self.status.setText(i18n.t("objchg.res.run", run_id=self._run_id).lstrip(" ·"))
        self._sync_akcji()

    def _pokaz_wynik(self, res, *, cofniecie):
        """Wynik biegu (`ObjectChangeResult`) na liście: „Było” = gdzie plik stał przed biegiem,
        „Jest” = gdzie stoi po nim (ścieżka z wyniku rdzenia), „Status” = co się stało z pozycją
        i dlaczego. Dopasowanie po `location_id` - jedyna tożsamość pozycji wspólna dla planu
        i wyniku. Pozycja, której wynik nie zna, zachowuje swój ostatni status: „Dokończ” niesie
        w wyniku wyłącznie pozycje, które czekały, a te zapisane przed przerwaniem (poprzedni bieg
        albo przebieg z Porządków) „nie ruszonymi” nie są (bramka, kimi). „Nie ruszona” zostaje
        dla pozycji bez historii - bieg przerwany przed nią. Liczby podglądu mówiły w czasie
        przyszłym, więc po biegu chowają się (czas przeszły niesie zdanie wyniku), a nagłówek
        pominięć przechodzi w czas przeszły."""
        if cofniecie:
            statusy = {"applied": "objchg.st.undone", "blocked": "objchg.st.blocked",
                       "failed": "objchg.st.failed", "skipped": "objchg.st.skipped"}
        else:
            statusy = {"applied": "objchg.st.done", "blocked": "objchg.st.blocked",
                       "failed": "objchg.st.failed", "skipped": "objchg.st.skipped",
                       "withheld": "objchg.st.withheld"}
        wyniki = {fr.location_id: (klucz, fr) for klucz, lista in (
            ("applied", res.applied), ("blocked", res.blocked), ("failed", res.failed),
            ("skipped", res.skipped),
            ("withheld", [] if cofniecie else res.withheld)) for fr in lista}
        self._naglowki(po_biegu=True)
        self.items_tree.setColumnHidden(_COL_STATUS, False)
        for lid, w in self._wiersze.items():
            bylo = self._jest.get(lid, "")
            klucz, fr = wyniki.get(lid, (None, None))
            jest = (fr.path or bylo) if fr is not None else bylo
            self._jest[lid] = jest
            if klucz:
                status = i18n.t(statusy[klucz])
                if fr.reason:
                    status += i18n.t("objchg.st.reason", reason=fr.reason)
            else:
                status = self._status_wiersza.get(lid) or i18n.t("objchg.st.untouched")
            self._status_wiersza[lid] = status
            w.setText(_COL_STARA, sciezka_pod_korzeniem(bylo, self._korzen))
            w.setToolTip(_COL_STARA, bylo)
            w.setText(_COL_NOWA, sciezka_pod_korzeniem(jest, self._korzen))
            w.setToolTip(_COL_NOWA, jest)
            w.setText(_COL_STATUS, status)
            w.setToolTip(_COL_STATUS, status)
        self.counts.setVisible(False)
        pominiete = sum(g.childCount() for g in (self.skipped_tree.topLevelItem(i)
                                                 for i in range(self.skipped_tree.topLevelItemCount())))
        self.skipped_head.setText(i18n.t_plural("objchg.skipped_head_done", pominiete))

    def _dopasuj_pominiecia(self):
        """Lista pominięć HUGGUJE swoje wiersze (z sufitem `_POMINIECIA_MAX_PX`): jeden powód to
        jeden wiersz, a domyślna podpowiedź drzewa (~190 px) zabierała liście pozycji pion, którego
        ta potrzebuje. Rozwinięcie powodu liczy wysokość od nowa (pliki pod nim mają być widać),
        a wiele plików dostaje suwak pod sufitem. Wiersze są równe (`setUniformRowHeights`), więc
        liczba widocznych wierszy razy wysokość jednego wystarcza."""
        t = self.skipped_tree
        wiersz = t.sizeHintForRow(0) if t.sizeHintForRow(0) > 0 else t.fontMetrics().height() + 4
        widoczne = sum(1 + (g.childCount() if g.isExpanded() else 0)
                       for g in (t.topLevelItem(i) for i in range(t.topLevelItemCount())))
        h = t.header().sizeHint().height() + widoczne * wiersz + 2 * t.frameWidth() + 4
        t.setFixedHeight(min(_POMINIECIA_MAX_PX, h))

    @staticmethod
    def _tekst_karty(card_op, card_old, card_new, path):
        """Karta `OBJECT` pozycji: stara → nowa, albo stan bez zmiany (karta już w formie albo
        format bez karty - RAW). DOPISANIE karty do FITS jest oznaczone: zapis w miejscu umie
        w FITS wyłącznie podmienić istniejącą kartę, więc ten plik rdzeń przepisze w całości (droga
        atomowa) - człowiek ma to wiedzieć przed kliknięciem, nie dopiero ze zdania wyniku."""
        if card_op is None:
            return (i18n.t("objchg.card_kept", value=repr(card_old)) if card_old
                    else i18n.t("objchg.card_none"))
        stara = repr(card_old) if card_old is not None else i18n.t("objchg.card_absent")
        tekst = i18n.t("objchg.card_change", old=stara, new=repr(card_new))
        if card_op == "add" and not path.lower().endswith(_XISF):
            tekst += i18n.t("objchg.card_rewrite")
        return tekst

    # ---------------------------------------------------------------- stan akcji
    def _wolny(self):
        return (not self._runner.is_busy and not self._pipeline_busy
                and self._plan_thread is None)

    def _sync_akcji(self):
        """Przycisk akcji mówi, ILE pozycji pójdzie do zapisu - szczery disabled przy zerze, w biegu
        planu, zapisu i etapu Dostawy. Po przerwaniu przebiegu ta sama akcja DOKAŃCZA go (pozycje
        nieprzetworzone czekają w bazie jako oczekujące; przebieg `staged` bez czekających też -
        sterownik go domknie), a po udanym zapisie milczy do „Cofnij”. Okno przebiegu z Porządków,
        w którym nie ma czego dokańczać (cofanie przerwane, pozycja z błędem, przebieg domknięty),
        chowa przycisk akcji: zostaje „Cofnij” i „Zamknij”, a martwy „Zmień obiekt” nie udaje drogi
        (wizytacja W2). Nagłówek i opis nadążają za stanem (`_opisz_stan`)."""
        wolny = self._wolny()
        self.action_btn.setVisible(not (self._przebieg is not None and self._run_id is not None
                                        and not (self._pozostalo or self._dokonczenie)))
        if self._pozostalo or self._dokonczenie:
            self.action_btn.setText(i18n.t("objchg.finish_btn", n=self._pozostalo)
                                    if self._pozostalo else i18n.t("objchg.finish_btn_bare"))
            self.action_btn.setEnabled(wolny)
            self.action_btn.setToolTip("")
        elif self._wynik_na_liscie and self._run_id is None:
            # Lista niesie wynik biegu, a przebiegu do cofnięcia nie ma (cofnięty albo nic nie
            # zmienił) - następnym krokiem jest świeży plan na dzisiejszym stanie.
            self.action_btn.setText(i18n.t("objchg.replan_btn"))
            self.action_btn.setEnabled(wolny)
            self.action_btn.setToolTip("")
        else:
            n = liczby_planu(self._plan)["robota"] if self._plan is not None else 0
            # Licznik mówi, ile ZOSTAŁO do zapisania - po wykonaniu liczba znika razem z sensem
            # drugiego kliknięcia (lekcja okna „Napraw nagłówek…”).
            licznik = bool(n) and not self._domkniety
            if self._target is not None:
                tekst = (i18n.t("objchg.action_change", n=n) if licznik
                         else i18n.t("objchg.action_change_bare"))
            else:
                tekst = (i18n.t("objchg.action_align", n=n) if licznik
                         else i18n.t("objchg.action_align_bare"))
            self.action_btn.setText(tekst)
            self.action_btn.setEnabled(wolny and licznik)
            self.action_btn.setToolTip(
                "" if n or self._plan is None or self._domkniety else i18n.t("objchg.nothing_tip"))
        self.undo_btn.setVisible(self._do_cofniecia)
        self.undo_btn.setEnabled(wolny)
        if self._przebieg is not None:
            self._opisz_stan()

    def set_pipeline_busy(self, busy):
        """Etap Dostawy w biegu → akcje zapisu gasną (okno modalne, poza `set_busy` widoku).

        PO ZBOCZU busy → wolne plan liczy się od nowa, o ile okno nie ma przebiegu (nic w biegu, nic
        do dokończenia ani cofnięcia): etap mógł przeskanować pliki z listy i podgląd sprzed niego
        obiecywałby kotwice, które zapis odbije. Przebiegu nie ruszamy - jego stan niesie baza."""
        bylo = self._pipeline_busy
        self._pipeline_busy = bool(busy)
        if (bylo and not busy and self._run_id is None and not self._runner.is_busy
                and self._plan_thread is None and not self._wynik_na_liscie):
            self._licz_plan()
            return
        self._sync_akcji()

    # ---------------------------------------------------------------- zapis
    def _on_action(self):
        """Staging planu z podglądu i JEDNA operacja uchwytu. Po przerwaniu - ten sam przebieg
        od pierwszej nieprzetworzonej pozycji, bez drugiego stagingu (rdzeń odtwarza go z bazy)."""
        if not self._wolny():
            return
        self.error.clear()
        if self._wynik_na_liscie and self._run_id is None and not self._pozostalo:
            self._licz_plan()                   # „Policz plan ponownie” - zapis dopiero z planu
            return
        if self._pozostalo or self._dokonczenie:
            total = self._pozostalo             # 0: sterownik tylko domknie przebieg `staged`
        else:
            if self._plan is None or self._domkniety or not liczby_planu(self._plan)["robota"]:
                return
            # Staging na wątku okna: jedna transakcja na wierszach planu, bez dysku. Odmowa
            # klingi (`ValueError`) i błąd bazy (`sqlite3.Error`: zajęta, drugi staging tego
            # przebiegu) zostawiają okno z powodem i zero zapisu - transakcja wycofuje się cała.
            try:
                repo.stage_object_change(self.con, plan=self._plan, now=self._now())
            except (ValueError, sqlite3.Error) as e:
                self.error.setText(i18n.t("objchg.err.stage", msg=f"{type(e).__name__}: {e}"))
                return
            self._run_id = self._plan.run_id
            total = len(self._plan.items)
        self._domkniety = True
        self._w_biegu = total
        self._begin_progress(total)
        self._runner.start("object_change", self._run_id, on_progress=self._on_progress,
                           on_done=self._after_commit, on_failed=self._on_failed)

    def _begin_progress(self, total):
        """Pasek na czas zapisu i cofnięcia; `total=0` = nieokreślony (cofnięcie nie zna liczby
        z góry). Akcje gasną do końca biegu."""
        self.bar.setRange(0, total)
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.action_btn.setEnabled(False)
        self.undo_btn.setEnabled(False)

    def _on_progress(self, done, total, path, status):
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.status.setText(f"{done}/{total} · {sciezka_pod_korzeniem(path, self._korzen)}")

    def _after_commit(self, op, res):
        """Wynik przebiegu: lista z wynikiem per wiersz, zdanie, „Cofnij”, gdy cokolwiek się
        zmieniło, i „Dokończ” po przerwaniu (pozycje nieprzetworzone)."""
        self.bar.setVisible(False)
        self.summary = zdanie_wyniku_zmiany(res)
        self.status.setText(self.summary)
        self._pokaz_wynik(res, cofniecie=False)
        self._wynik_na_liscie = True
        self._do_cofniecia = self._do_cofniecia or ruszyl_cokolwiek(res)
        przetworzone = (len(res.applied) + len(res.blocked) + len(res.failed) + len(res.skipped)
                        + len(res.withheld))
        if res.cancelled:
            # „Dokończ (N)” liczy pozycje, których przerwany bieg nie dotknął - z liczby, z którą
            # ten bieg ruszył (cały plan albo reszta po poprzednim przerwaniu).
            self._pozostalo = max(self._w_biegu - przetworzone, 0)
        else:
            self._pozostalo = 0
        # Przerwany bieg zostawia przebieg `staged` (sterownik domyka go wyłącznie na końcu listy);
        # bieg do końca - domknięty, a pozycja z błędem zostawia stan częściowy do cofnięcia.
        self._dokonczenie = res.cancelled
        self._stan_przebiegu = ("staged" if res.cancelled else "failed" if res.failed else None)
        if not self._do_cofniecia and not self._pozostalo:
            # Przebieg niczego nie zmienił (same blokady i pominięcia): nie ma czego cofać ani
            # dokańczać. Lista zostaje z powodami blokad, a akcja proponuje świeży plan na
            # dzisiejszym stanie zamiast martwego przycisku.
            self._run_id = None
            self._domkniety = False
        self.changed.emit()
        self._sync_akcji()

    def _on_failed(self, op, msg):
        """Wyjątek workera. Przebieg jest w bazie, więc okno bierze stan stamtąd, nie z pamięci:
        po wyjątku ZAPISU „Cofnij” zostaje (cofnięcie przy niczym do zrobienia mówi „0”), a „Dokończ”
        stoi, dopóki przebieg jest `staged` (liczy pozycje, które w bazie wciąż czekają - także
        zero, gdy wyjątek padł po ostatniej pozycji); po wyjątku COFNIĘCIA dokańczać nie ma czego
        (cofnięty przebieg zapisu nie wznawia), zostaje ponowienie „Cofnij”."""
        self.bar.setVisible(False)
        if self._run_id is not None:
            self._do_cofniecia = True
            if op == "object_change":
                widok = queries.object_change_run_view(self.con, self._run_id)
                self._pozostalo, self._dokonczenie = widok["pending"], widok["can_finish"]
                self._stan_przebiegu = "staged" if widok["can_finish"] else "failed"
            else:
                self._pozostalo, self._dokonczenie = 0, False
                self._stan_przebiegu = "undoing"
        self.error.setText(i18n.t("grid.wb.error", msg=msg)
                           + (i18n.t("objchg.res.run", run_id=self._run_id) if self._run_id else ""))
        self._sync_akcji()
        self.changed.emit()

    # ---------------------------------------------------------------- cofnięcie (okno do zamknięcia)
    def _on_undo(self):
        if self._run_id is None or not self._wolny():
            return
        self.error.clear()
        self._begin_progress(0)
        self._runner.start("undo_object_change", self._run_id, on_progress=self._on_progress,
                           on_done=self._after_undo, on_failed=self._on_failed)

    def _after_undo(self, op, res):
        """Wynik cofnięcia na liście (Było / Jest / Status per wiersz) i w zdaniu. Cofnięcie, które
        czegoś nie cofnęło (blokada, błąd), zostawia „Cofnij” - ponowienie wznawia pierwszą
        niedomkniętą fazę pozycji (rdzeń). Pełne cofnięcie zużywa przebieg: „ponownie” to świeży
        plan i nowy przebieg („Policz plan ponownie”), nie powtórka starego."""
        self.bar.setVisible(False)
        self.summary = zdanie_wyniku_zmiany(res, cofniecie=True)
        self.status.setText(self.summary)
        self._pokaz_wynik(res, cofniecie=True)
        self._wynik_na_liscie = True
        niedomkniete = bool(res.blocked or res.failed or res.cancelled)
        self._do_cofniecia = niedomkniete
        self._pozostalo = 0          # po cofnięciu „Dokończ” przebiegu nie ma już czego dokańczać
        self._dokonczenie = False
        self._stan_przebiegu = "undoing" if niedomkniete else None
        if not niedomkniete:
            self._run_id = None
            self._domkniety = False
        self.changed.emit()
        self._sync_akcji()

    # ---------------------------------------------------------------- zamknięcie
    def done(self, r):
        """KAŻDA droga zamknięcia przechodzi tędy. W biegu zapisu okno ZOSTAJE (`refuse_close`:
        wątek zapisu jest dzieckiem okna, a raport przerwania musi mieć dokąd trafić).

        PLAN W BIEGU: okno znika od razu, a zamyka się, gdy wątek planu skończy
        (`_cleanup_plan_thread`). Czekanie tu na wątek zamroziłoby okno na czas odczytu katalogów
        po SMB (bez limitu), a zabicie go pod kasowanym rodzicem to twardy abort. Wynik planu, który
        jeszcze przyjdzie, idzie do kosza (nowa generacja)."""
        if self._runner.refuse_close(self.error.setText):
            return
        if self._plan_thread is not None:
            self._gen += 1
            self._zamknij_po_planie = r
            self.hide()
            return
        super().done(r)
