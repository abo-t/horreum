"""Widok „Klatki" — grid nad EAV `cards` z filtrem i perspektywami (PLAN_gui_grid, KROK 3 scalenia).

READ-ONLY wobec danych (edycja/writeback = KROK 4). Doktryna §5: grid jest jedynym centrum, wszystko
inne to soczewki — ZERO modali w głównym przepływie. Warstwa widżetów (na whiteliście `test_gui_isolation`);
cała logika (silnik filtra, pivot, read-model) siedzi w Qt-wolnych `horreum.filter_engine`/`horreum.pivot`/
`horreum.gui.queries`. Model port `fitsmirror/gui/grid_model.py` (3 stany komórki + sort), bez edycji/stagingu.

Kolumny BAZOWE (warstwa interpretacji nad lustrem) + dynamiczne kolumny-keywordy z `cards`. Perspektywy =
nazwane {filtr+kolumny+grupowanie+sort} w **BAZIE** (`saved_query.spec_json`, migracja 0013) + presety
zaszyte w kodzie. **D-B ODWRÓCONE 2026-08-01 (GO Zdzinia, D-P-I-3), WDROŻONE w I-1:** nazwany widok jest
własnością ARCHIWUM, nie komputera — jedzie z bazą na laptop i przeżywa reinstalację. Rejestr zostaje
własnością BIURKA (progi, ostatnie katalogi); perspektywy zapisane w nim przed tą zmianą wciąga
JEDNORAZOWY, idempotentny import przy otwarciu widoku (`_import_settings_perspectives`) — wydanie
publiczne miało tę funkcję w `QSettings`, więc ciche porzucenie cudzych widoków byłoby regresją,
nie sprzątaniem. Grupowanie minimalne: nagłówki
grup po jednej kolumnie bazowej (D-D). `present` = kolumna statusu (zniknięte tłowane); Duplikaty = n_present>1.

F3 (PLAN_ux_redesign §4): pasek ZBIORU (`SelectionBar` — licznik + kryteria słowami + akcje) nad
`_PanelStack`, w którym klingi (`MacroBar`/`RenameBar`) są PANELAMI otwieranymi z akcji — widoczny
najwyżej JEDEN; przełączenie na cudzy panel czyści podgląd dotychczasowego właściciela (R#9).

FASADA (`WO-6`): ten plik trzyma `FramesView`, a resztę widoku niosą moduły `grid_model` (kolumny,
presety, recepty, `GridTableModel`), `grid_panels` (filtr, pola, makro, rename), `grid_lineage` (panel
rodowodu), `grid_selection` (pasek zbioru, stos paneli, szuflada) i `grid_workers` (robotnicy tła).
Importerzy dalej sięgają po nazwy przez `grid`; podmiana nazwy w teście (`monkeypatch`) trafia jednak
tam, gdzie nazwę CZYTA kod - do modułu, który ją woła, nie do fasady.
"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import statistics
import uuid
from datetime import datetime, timezone
from functools import partial

from PySide6.QtCore import (
    QEvent, QItemSelection, QItemSelectionModel, QModelIndex, QPersistentModelIndex, Qt, QSettings, QThread,
    QTimer, Signal, Slot,
)
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QPushButton, QDialog, QMenu,
    QFrame, QMessageBox, QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from horreum import (
    filter_engine, lead_copy, lineage, macro as macro_mod, naming, repo, scan, stacks, supersede, writeback,
)
from horreum.gui import busy, facet_model, i18n, queries, rows
from horreum.gui.facets import FacetRail
from horreum.gui import assign_dialog
from horreum.gui.assign_dialog import AssignObjectDialog
from horreum.gui.note_dialog import NoteDialog
from horreum.gui.object_change_dialog import ObjectChangeDialog
from horreum.gui.projection_dialog import ObjectPickDialog, ProjectionDialog
from horreum.resolve.frames import LIGHT_KINDS
from horreum.gui.wb_worker import (
    WritebackRunner, ZdanieZeSzczegolem, commit_do_cofniecia, podpowiedz_kart, podpowiedz_powodow,
    zdanie_wyniku_zapisu,
)

# FASADA: `grid` re-eksportuje nazwy modułów `grid_*`, po które sięga reszta pakietu i testy
# (`tests/test_gui_grid_fasada.py` pilnuje, że każda czytana z zewnątrz nazwa tu jest).
from horreum.gui.grid_model import (
    BASE_COLS, _CEL_GEST, _CEL_WIDOK, _COLORS, CzlonRecepty, _dolacz_kopie, _dup_tip, _EdycjaKomorki,
    elizja_w_srodku, _ElizjaWSrodku, _EMPTY_DB, _EMPTY_FILTER, _EMPTY_PERSP, _EMPTY_VIEW, FIND_COLS,
    _FLAGA_NOWSZYCH, _FLAGA_OPTYKI, _FLAGA_POTWIERDZENIA, _FLAGA_WERSJI, _FLAGA_ZASTAPIONYCH,
    _FLAGA_ZGODNOSCI_PLIKU,
    _FLAGI_CZEKAJA_NA_FAKTY,
    _FLAGI_KOPII_WIODACEJ, _FLAGI_OBRAZOW,
    _FLAGI_SCIEZKI_Z_TRESCI, GridTableModel, _GRUPA_WERSJI, _half_away, _klucz_kryterium, _klucz_spec,
    kolumna_z_tresci, _kopie_wielokrotne, _lista_kanonow, _nieznane_warunki, _OBJECT_STATE_TIPS, _object_tip,
    _ODWROT_COFNIECIA, _ODWROT_PRZYWROCENIA, _ODWROT_UWAG, _ODWROT_WERDYKTU, _ODWROT_WYCOFANIA,
    _ogon_sciezki, OPERATORS,
    _podpowiedz_gestu_zapisu,
    _pole_rozjazdu, _POWROT_PERSPEKTYWA, _POWROT_ZBIOR, PRESET_COPY_CONFLICT, _PRESET_CZYSTY, PRESET_DUPS,
    PRESET_F_RATIO_MISMATCH, PRESET_FILE_OBJECT_MISMATCH,
    _PRESET_LABELS, PRESET_LINEAGE, PRESET_MISSING_COPY, PRESET_ORPHAN_TESTIMONY, PRESET_PATH_HEADER_CONFLICT,
    PRESET_PENDING_FINISH, PRESET_READY_IMAGES, PRESET_RETIRED, PRESET_RETIRED_CONFLICT,
    PRESET_STACK_VERSIONS, PRESET_SUPERSEDED,
    PRESET_KEPT_COPIES, PRESET_TORN_WRITE, PRESET_VANISHED, PRESET_WITHHELD_TESTIMONY, PRESETS,
    PREZENTACJA_KLASYCZNA,
    PREZENTACJA_ZNAJDZ, Recepta,
    _RECEPTA_ZAJETA, _RECEPTY_ZAPISU, _ROLA_ETYKIETY, _set_role, _SPEC_OBRAZY, _SPEC_SZEROKOSC_SCIEZKI,
    _SPEC_WIDOK, STRUCT_NOISE, _SUFIT_KOLUMNY_Z_TRESCI, _SZEROKOSC_UWAG, szerokosc_z_tresci, _TabelaKlatek,
    _TRIMY,
    use_theme, _UWAGI_ZAJETE, _zawezenie_facetowe, _zdanie_gestu_zapisu, _zdanie_kopii_wielokrotnych,
    _zdanie_kopii_wiodacej, zdanie_pominiec, _zlacz_recepty, _ZNANE_KLUCZE_SPECU,
)
from horreum.gui.grid_panels import FieldsPanel, FilterPanel, MacroBar, RenameBar, zdanie_kopii_bez_zeznania
from horreum.gui.grid_lineage import (
    _frame_gate_reason, _KLUCZE_POKAZ, _lineage_flags, _lineage_item_text, _lineage_raw_note,
    LineageBar, _object_gate_reason, REASON_NO_OBJECT_TOKEN, REASON_OFFSET_TOKEN,
)
from horreum.gui.grid_lineage import calibration_class_name, _nazwa_pliku   # oś kalibracji (E4-5)
from horreum.gui.grid_selection import _PanelStack, ReleaseDialog, SelectionBar, StagingDrawer
from horreum.gui.grid_workers import _liczniki_listwy, PolaWorker, _sklad_zbioru, ZbiorWorker


def _fmt_f(v):
    """f/ do zdania recepty perspektywy optyki: `8.0` → `8`, brak → `-`."""
    return "-" if v is None else f"{v:g}"


class FramesView(QWidget):
    """Widok „Klatki": panel Pól | (perspektywa + filtr + PASEK ZBIORU + panele kling + grid)
    + poczekalnia zmian (szuflada stagingu). Kontrakt montażu `MainWindow`: `__init__(con, now_fn,
    parent)`, sygnał `status_message`, `refresh()`. KROK 4: makro (druga klinga) — filtr→oblicz→
    przypisz na widocznych klatkach, staging, commit/undo. F3: klingi jako panele `_PanelStack`
    otwierane z `SelectionBar` (najwyżej jeden widoczny; R#9 w `_toggle_panel`)."""

    # Zdanie raportu: `str` albo `wb_worker.ZdanieZeSzczegolem` - zdanie ze szczegółem systemu dla
    # podpowiedzi paska gospodarza (AR-218). Typ `object`, bo `Signal(str)` zamienia podklasę na goły
    # `str` i szczegół przepada po cichu (zmierzone, PySide6 6.9.2) - jak `status_recipe` niżej.
    status_message = Signal(object)
    # RAPORT WCZYTANIA ZBIORU („Wczytuję klatki…", „Grid: N klatek…") - osobny kanał, bo pada też
    # wtedy, gdy Zbiorów nie widać: odświeżenie po przebiegu Dostawy, start okna. Na wspólnym
    # kanale przykrywał na pasku status etapu, po który user patrzy w Dostawie. Gospodarz decyduje,
    # czy go pokazać teraz, czy odłożyć do wejścia w Zbiory (`MainWindow._raport_wczytania_gridu`).
    # Wyniki GESTÓW zostają na `status_message`: gest z panelu rodowodu przełącza widok na Dostawę
    # i jego zdanie ma tam paść.
    load_report = Signal(str)
    # Gest osi obiektu z paska Zbiorów zmienia stan, który pokazuje INNE okno (kolejka przeglądu
    # osi obiektu). Sygnał, nie wołanie: grid nie zna gospodarza i nie ma go poznawać (NARROW).
    object_axis_changed = Signal()
    # Gest ruszył oś STANOWISKA (przeniesienie wskazania ręki, AR-41) - gospodarz odświeża oś
    # obserwatorium; grid jej nie zna, tak samo jak osi obiektu.
    observatory_axis_changed = Signal()
    # STAN LICZONY PRZEZ PORZĄDKI SIĘ ZMIENIŁ - jeden sygnał z końca drogi KAŻDEGO gestu gridu,
    # który rusza populację `queries.tasks_state`; gospodarz podpina go RAZ pod `refresh_counts`
    # (plakietka nawigacji). Osobno od `object_axis_changed`, bo ten mówi o INNEJ powierzchni
    # (kolejka przeglądu osi obiektu) i nie odpala przy gestach osi żywotności klatki - a właśnie
    # przez to plakietka zostawała przy liczbie sprzed „Przywróć"/„Wycofaj" do wejścia w Porządki.
    # Dopinanie odświeżenia przy każdym geście osobno to figura, która w tym repo rozjeżdżała się
    # już kilka razy („etykieta kłamie"); właściciel emisji jest jeden - ogon gestu. Emitują:
    # `_po_gescie_osi`, `_po_gescie_klatki`, gesty panelu rodowodu i ogony writebacku (makro:
    # `_after_commit`/`_after_undo`, rename: `_after_commit_rename`/`_after_undo_rename`, błąd:
    # `_on_wb_failed`), wyłącznie gdy gest coś zapisał (ogon błędu - zawsze, bo nie wie, ile zdążył
    # zapisać). Rename jest tu dla JEDNEJ reguły, nie dlatego, że dziś wiadomo, który wiersz czyta
    # `location.path`: „każdy ogon zapisu emituje" nie wymaga pamiętania, który wiersz Porządków
    # czyta które pole, a kosztuje jedno `tasks_state` po geście.
    stan_porzadkow_changed = Signal()
    # Mutex DWÓCH powierzchni writebacku (D-PD-3): gospodarz przekazuje ten fakt drugiej powierzchni
    # (dialog „Napraw nagłówek…"). Dwa równoległe commity spotkałyby się na `BEGIN IMMEDIATE`
    # z `busy_timeout` 5 s i jeden wróciłby jako 'failed' — bez powodu widocznego dla usera.
    writeback_busy = Signal(bool)
    # RECEPTA MA WŁASNY KANAŁ (FH-2), bo dostała własny nośnik na pasku. Zdanie po geście przestało
    # się mieścić w `showMessage` - zmierzone 252 znaki = 1336 px przy 1459 px dostępnych (przy
    # skalowaniu 125 % już 1695/1672), a `QStatusBar` tnie BEZ wielokropka, w środku słowa, i ucina
    # człon OSTATNI, czyli receptę. Rozdział jest tu koniecznością, nie estetyką - lustro
    # `phase_label`: raport („co się stało") i recepta („co możesz teraz zrobić") konkurowały
    # o jedno pole, więc ginęła ta druga, choć to po nią user sięga.
    #
    # RAPORT ZOSTAJE NA `status_message` I TO JEST CELOWE: wydzielenie CAŁEGO zdania na nowy sygnał
    # przepięłoby kanał, którym mówią wszystkie inne gesty widoku, a raport gestu osi niczym się od
    # nich nie różni. Osobny kanał należy się temu członowi, który ma osobny nośnik - i tylko jemu.
    # Recepta leci ZARAZ PO raporcie (nigdy przed), więc pusta gasi cudzą z poprzedniego gestu.
    # NIESIE `Recepta` (zdanie + człony z wykonawcami, FH-2e/FH-8), więc typ sygnału to `object`:
    # `Signal(str)` przepisałby wartość na gołe `str` i nośnik zgubiłby człony po drodze.
    status_recipe = Signal(object)
    # Pusty stan perspektywy kopii prowadzi do Dostawy (`_ustaw_pusty_stan`) - gospodarz przełącza
    # widok, jak przy `TasksView.open_intake`. Sygnał, nie wołanie: grid nie zna gospodarza (NARROW).
    open_intake = Signal()
    # Czasownik „Zbiory klasyczne" z paska Znajdź - przełączenie prezentacji należy do kontenera
    # strony (`ZnajdzView`), który zna też nawigację; widok o nim nie wie (NARROW).
    classic_requested = Signal()
    # Stan zbioru przyłożony (koniec `_zastosuj_zbior`) albo zmieniona prezentacja - kontener odbudowuje
    # chipy aktywnego stanu. Jeden sygnał po przyłożeniu, nie po każdym geście: chip ma mówić o zbiorze,
    # który WIDAĆ, a nie o tym, który dopiero się liczy.
    stan_zbioru_zmieniony = Signal()

    def __init__(self, con, now_fn=None, parent=None, *, pola_poza_watkiem=False):
        super().__init__(parent)
        self.con = con
        self._db_path = queries.db_path_of(con)   # worker writebacku otwiera WŁASNE połączenie (per-wątek)
        self._now = now_fn or (lambda: datetime.now(timezone.utc).isoformat())
        self._filter_tree = None
        # F4: stan listwy facetów (serializowany w perspektywie OSOBNO od `_filter_tree` — nota R2)
        # + drzewo EFEKTYWNE compose(facety, advanced), ustawiane w refresh() (źródło paska kryteriów,
        # F4R#8). Oba PRZED pierwszym refresh() (F4R2#7).
        self._facet_state = facet_model.empty_state()
        self._effective_tree = None
        # TEKST UWAG - składnik stanu zbioru obok facetów i filtra (Znajdź: `uwagi:` albo fraza bez
        # obiektu). Przecięcie z `queries.note_hits` w `_sklad_zbioru`. Zdejmuje go każde wejście,
        # które ZASTĘPUJE zbiór (perspektywa, „× Wyczyść zbiór", most obiektu, nowe zapytanie);
        # klik facetu go zostawia, bo tylko zawęża.
        self.note_query = None
        # KLATKI WSKAZANE WPROST - składnik stanu zbioru obok trimów (`show_frames`, dwuklik w panelu
        # rodowodu): `(frame_ids, etykieta chipu)` albo `None`. Tnie jak trim, ale zbiór niesie wejście,
        # nie zapytanie, więc nie ma go w żadnej perspektywie. `_powrot_wskazanych` = stan sprzed
        # wejścia - „×" chipu WRACA do niego (droga wyjścia), zamiast zostawiać całe archiwum.
        self._wskazane = None
        self._powrot_wskazanych = None
        self.prezentacja = PREZENTACJA_KLASYCZNA
        self._wersja_w_znajdz = False   # „Kolumny ▾ → Wersja" w Znajdź (AR-50 (5)), domyślnie wyłączona
        # Droga powrotu gestu uwag: `(before, after)` ostatniego gestu - `before` z klingi (stan sprzed
        # gestu per zmieniona klatka), `after` = treść, którą gest zostawił (`None` = zdjęcie).
        self._migawka_uwag = None
        # Droga powrotu werdyktu ręki: `((integration_id, stos, zmiany), …)` ostatniego gestu - jeden
        # stos z panelu rodowodu albo wszystkie obrazy gestu zbiorczego (AR-178); `zmiany` =
        # `repo.JudgedInput` z klingi (stan sprzed gestu odczytany pod jej blokadą).
        self._migawka_werdyktu = None
        self._cichy_raport_gen = None   # generacja przeładowania po geście panelu - bez raportu wczytania
        self._skladniki_przylozone = []   # składniki zawężenia OSTATNIO PRZYŁOŻONEGO zbioru (chipy)
        # Terminy ostatniego zapytania Znajdź - `(etykieta, klucze składników)`, jeden chip na termin;
        # schodzą z każdym wejściem, które zastępuje zbiór. Stan, który zapytanie postawiło, i to,
        # czy przyłożony zbiór wciąż nim jest (`zapytanie_aktualne`).
        self._terminy = []
        self._stan_zapytania = None
        self._zapytanie_aktualne = False
        self._zeruj_flagi()         # flagi perspektyw `_only_*` - skład z `_TRIMY`, jedna enumeracja
        self._cel_gestu = []        # klatki wypchnięte z widoku przez ostatni gest - wracają do
                                    # zaznaczenia przy najbliższym przeładowaniu zbioru (FC-2)
        self._recepta_gestu = None  # `(cel, _Odwrot|None)` ostatniego gestu osi - recepta paska
                                    # składa się z tego STANU przy każdym odświeżeniu (FH-2e)
        self._ts_recepty = None     # `event.ts` gestu tej recepty - tożsamość dla Domu (AR-94)
        self._kanony_recepty = ()   # kanony celu gestu tej recepty - człon odsłonięcia je nazywa
        self._gest_nr = 0           # żeton gestu: ogon starszego gestu milknie po nowszym (AR-84)
        self._reveal_facet = None   # (facet, wartość) do odsłonięcia w listwie — patrz `apply_object_facet`
        self._frame_ids = []      # frame_id widoczne w gridzie (cel makra) — aktualizowane w refresh()
        self._run_id = None       # JEDEN run_id sesji makra (R#5 lifecycle: stage→commit/reject zwalnia)
        # Edycje komórek (AR-61) jadą TYM SAMYM przebiegiem `_run_id` (jedna klinga, jeden commit,
        # jeden cel „Cofnij" łapany przy commicie w `_install_undo`) - nie trzecim trybem szuflady.
        # Pamiętamy, POD KTÓRYM przebiegiem i które karty `(location_id, keyword)` stoją z ręki:
        # ponowny staging makra czyści cały przebieg, więc bez tej pamięci zjadłby je po cichu.
        self._komorki_run = None
        self._komorki = set()
        self._n_total = 0         # liczba widocznych klatek (baza licznika; zaznaczenie dokładane, G2)
        # Stan renamu — CZTERY zmienne (R1 #1 + R2 #1): run aktywnego stagingu, flaga „skommitowany"
        # (re-stage po commicie MINTUJE nowy run, nie kasuje wierszy 'applied'=undo), OSOBNY cel „Cofnij"
        # (przechwycony przy commicie — bez niego mint przekierowałby żywy Cofnij na pusty run = złudzenie),
        # tryb dispatchu współdzielonego „Cofnij" ({None,macro,rename}).
        self._rename_run_id = None
        self._rename_run_committed = False
        self._undo_rename_run_id = None
        self._undo_mode = None
        self._preview_owner = None   # {None,'macro','rename'} — podgląd współdzielony (R1 #19)
        # Writeback OFF-THREAD (commit/undo nie zamrażają GUI): cykl worker+wątek trzyma WSPÓLNY
        # uchwyt (`wb_worker.WritebackRunner`, P-D/D-PD-3 — ten sam kod wykonuje dialog „Napraw
        # nagłówek…"), tu zostaje tylko to, co widżetowe. Uchwyt POWSTAJE W `__init__`, bo seam
        # `_writeback_async` bywa ustawiany z zewnątrz PRZED pierwszą operacją (testy).
        # `_wb_target_id` zostaje W WIDOKU: czyta go `_after_commit_rename` PO zakończeniu operacji,
        # a uchwyt jest per-powierzchnia — wspólny ślad celu nadpisywałyby sobie dwa okna.
        self._wb = WritebackRunner(self._db_path, now_fn=self._now, parent=self)
        self._wb.busy_changed.connect(self.writeback_busy)   # re-emisja: uchwyt zna oba końce operacji
        self._wb_target_id = None
        self._foreign_wb = False   # DRUGA powierzchnia pisze (mutex; ustawia gospodarz)
        self._etap_w_biegu = False  # etap Dostawy pisze do bazy (`set_busy`) - gesty izolacji czekają
        self._cel_gestu_zapisu = []  # klatki ostatniego gestu izolacji - zaznaczenie po jego końcu
        # Otwarte okno „Zmień obiekt…"/„Uzgodnij pliki…" (modalne, poza `set_busy` widoku) - etap
        # Dostawy w biegu gasi jego akcje zapisu przez to odwołanie (wzorzec `_repair_dlg` osi).
        self._okno_zmiany_obiektu = None
        # Wynik gestu izolacji w szufladzie należy do perspektywy, w której padł (AR-30 (5)):
        # `((zdanie, szczegół) sprzed gestu, zdanie wyniku)`; zmiana perspektywy przywraca pierwsze,
        # o ile szuflada wciąż pokazuje drugie (inny zapis mógł ją już przejąć).
        self._wynik_gestu_zapisu = None
        # Podgląd klingi ZAPISANY przez commit szuflady, schowany do zdjęcia ogonem (AR-207): obiekt
        # podglądu modelu - każde `set_preview` daje nowy, więc świeży podgląd nie jest schowany.
        self._podglad_po_zapisie = None
        # POKRYCIE PÓL POZA WĄTKIEM GUI (`PolaWorker`). Zapytanie trwa na żywym archiwum 5,6-5,9 s,
        # a szło przy otwarciu bazy i po KAŻDYM przebiegu Dostawy - okno stało wtedy jednym blokiem
        # dłuższym niż próg „Nie odpowiada". `pola_poza_watkiem=False` (domyślne) = ten sam rdzeń
        # inline: widok zbudowany wprost (testy, `:memory:`) dostaje pola synchronicznie, jak dotąd;
        # gospodarz (`MainWindow`) włącza wątek. Kolumny zaczynają PUSTE - domyślne wybiera pierwszy
        # wynik (`_zastosuj_pola`), bo bez pokrycia nie wiadomo, które keywordy są najczęstsze.
        self._pola_async = pola_poza_watkiem
        self._columns = []
        self._obrazy_reka = None    # wybór ręki dla kolumny „Obrazy" (None = za perspektywą)
        self._obrazy_perspektywy = None  # wybór „Obrazów" z zapisanej perspektywy (None = brak)
        self._szerokosc_sciezki = None  # szerokość ścieżki z zapisanej perspektywy (None = brak)
        self._pola = None           # ostatnie ZASTOSOWANE pokrycie (lista {"keyword", "n"})
        self._pola_odcisk = None    # odcisk kart, z którego ono pochodzi (`pola.odcisk_kart`)
        self._pola_gen = 0          # generacja prośby - wynik starszej ląduje w koszu
        self._pola_worker = None
        self._pola_thread = None
        self._pola_ponow = False    # prośba w trakcie biegu → jeszcze jeden bieg po nim
        self._pola_stop = False     # widok zamykany - żadnego nowego biegu (pól ani zbioru)
        # SKŁAD ZBIORU POZA WĄTKIEM GUI (`ZbiorWorker`, AR-27) - ten sam przełącznik co pola: gospodarz
        # włącza oba wątki tła naraz, widok zbudowany wprost (testy, `:memory:`) liczy inline.
        # Wątek dostają wyłącznie zlecenia `refresh(w_tle=True)` (nawigacja: facet, filtr, kolumny,
        # perspektywa, przebieg Dostawy); gesty zapisu czytają model zaraz po `refresh()` i liczą
        # synchronicznie. Generacja jak przy polach: każde zlecenie (także synchroniczne) ją podbija,
        # więc wynik starszego, który dotrze po nowszym, ląduje w koszu.
        self._zbior_async = pola_poza_watkiem
        self._zbior_gen = 0
        self._zbior_worker = None
        self._zbior_thread = None
        self._zbior_ponow = False   # zlecenie w trakcie biegu → bieg po nim, na stanie z TEJ chwili
        self._zbior_ogony = []      # ogony zleceń (`refresh(potem=…)`) czekające na przyłożenie zbioru
        self._zbior_bieg_gen = None  # generacja, którą liczy bieg w wątku (None: wynik już oddany)
        self._zbior_odlozony = None  # `(gen, wynik)` czekający na zamknięcie edytora komórki
        # Generacja przeładowania NIE-NAWIGACYJNEGO, które oddaje zaznaczenie po przyłożeniu
        # (`przeladuj_z_zaznaczeniem`, AR-172); każde inne zlecenie podbija generację i ją unieważnia.
        self._przeladowanie_z_zaznaczeniem = None
        self._zbudowany = False     # koniec `__init__`: od tej chwili zmiana kolumn przeładowuje zbiór
        self._build_ui()
        # PRZED pierwszym zbudowaniem listy perspektyw: rejestr sprzed I-1 dowozi swoje widoki do
        # bazy, więc combo od razu pokazuje komplet, a nie „gdzie się podziały moje perspektywy".
        self._import_settings_perspectives()
        self._load_facets()
        self.refresh(w_tle=True)    # otwarcie bazy: okno żyje, zanim zbiór dojedzie (AR-27)
        self._refresh_drawer()
        self._przywroc_panel_rodowodu()   # panel rodowodu otwarty przy zamknięciu wraca otwarty
        self._zbudowany = True

    # ---- budowa ----
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Górny pasek CHUDY (F3): tylko soczewki widoku (perspektywa + grupowanie); akcje na ZBIORZE
        # mieszkają w SelectionBar niżej.
        bar = QHBoxLayout()
        bar.addWidget(QLabel(i18n.t("grid.top.perspective")))
        self.combo_persp = QComboBox()
        self.combo_persp.currentIndexChanged.connect(self._on_perspective)
        bar.addWidget(self.combo_persp)
        bar.addSpacing(16)
        bar.addWidget(QLabel(i18n.t("grid.top.group_by")))
        self.combo_group = QComboBox()
        self.combo_group.addItem(i18n.t("grid.top.no_group"), None)
        for label, key in BASE_COLS:
            if key not in ("path",):
                # `BASE_COLS` niesie KLUCZE i18n, nie napisy (rozwiązuje je `headerData`) — bez `t()`
                # listwa pokazywała `object.col.name` zamiast „Obiekt". Znalezione sondą FC-3 na
                # żywym archiwum: SZEŚĆ z siedmiu pozycji renderowało klucz wewnętrzny.
                self.combo_group.addItem(i18n.t(label), key)
        # Grupowanie po GRUPIE WERSJI (perspektywa „Wersje stosów") - pochodna wiersza, nie kolumna.
        self.combo_group.addItem(i18n.t("grid.top.group_version"), _GRUPA_WERSJI)
        self.combo_group.currentIndexChanged.connect(self._on_group)
        bar.addWidget(self.combo_group)
        bar.addStretch(1)
        outer.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)
        # F4: lewa kolumna = pionowy splitter FacetRail (góra, dominuje) / Pola (dół) — wybór kolumn
        # to inna troska niż zawężanie zbioru (COHESION), oba zostają widoczne.
        self.facet_rail = FacetRail()
        self.facet_rail.facetsChanged.connect(self._on_facet_change)
        # Ctrl+F → szukajka obiektów (R-S3-6). `QKeySequence.Find`, nie literał: sekwencję „znajdź"
        # zna platforma i to ona ma o niej decydować. Kontekst WIDGET-Z-DZIEĆMI, nie okno — Ctrl+F
        # wciśnięty w Porządkach albo w planerze nie ma prawa przerzucać kursora do listwy Zbiorów.
        self._sc_find = QShortcut(QKeySequence.Find, self)
        self._sc_find.setContext(Qt.WidgetWithChildrenShortcut)
        self._sc_find.activated.connect(self.facet_rail.focus_search)
        self.fields = FieldsPanel()
        self.fields.columnsChanged.connect(self._on_columns)
        self.fields.imagesToggled.connect(self._on_images_toggled)
        left = QSplitter(Qt.Vertical)
        # LISTWA W PRZEWIJANYM KONTENERZE: jej minimum (grupy długie, krótkie na suficie W-6, grupa
        # „Rodowód" nad gotowymi obrazami) nie podnosi podłogi OKNA - przy niskim oknie listwa
        # dostaje suwak, a nie wypycha okno poza ekran (kanon: okno mieści się na 1920x1080 przy
        # 100 %; zmierzone natywnie: grupa „Rodowód" podnosiła podłogę 996 → 1058 px).
        self.rail_box = QScrollArea()
        self.rail_box.setWidget(self.facet_rail)
        self.rail_box.setWidgetResizable(True)
        self.rail_box.setFrameShape(QFrame.NoFrame)
        self.rail_box.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Szerokość: próg czytelności lewej kolumny (`RAIL_MIN_W`) ma KONTENER, a listwa oddaje suwakowi
        # jego szerokość - dołożony do progu poszerzałby podłogę okna (zmierzone natywnie +30 px).
        prog = self.facet_rail.minimumWidth()
        self.rail_box.setMinimumWidth(prog)
        self.facet_rail.setMinimumWidth(max(0, prog - self.rail_box.verticalScrollBar().sizeHint().width()))
        left.addWidget(self.rail_box)
        left.addWidget(self.fields)
        left.setStretchFactor(0, 3)
        left.setStretchFactor(1, 1)
        splitter.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0)
        self.filter_panel = FilterPanel([])
        self.filter_panel.filterApplied.connect(self._on_filter)
        rv.addWidget(self.filter_panel)

        # Pasek zbioru (F3): licznik + kryteria słowami + akcje; klingi jako panele w stacku niżej.
        self.sel_bar = SelectionBar()
        self.count_label = self.sel_bar.count_label      # TEN SAM QLabel (F3R#5) — `_update_count` bez zmian
        self.sel_bar.btn_proj.clicked.connect(self._open_projection)
        self.sel_bar.btn_obj.clicked.connect(self._open_object_release)
        self.sel_bar.btn_clear.clicked.connect(self._on_clear_selection)
        self.sel_bar.btn_save.clicked.connect(self._save_perspective)
        self.sel_bar.btn_macro.clicked.connect(lambda: self._toggle_panel("macro"))
        self.sel_bar.btn_rename.clicked.connect(lambda: self._toggle_panel("rename"))
        self.sel_bar.btn_lineage.clicked.connect(lambda: self._toggle_panel("lineage"))
        self.sel_bar.act_name.triggered.connect(self._on_object_name)
        self.sel_bar.act_clear.triggered.connect(self._on_object_clear)
        self.sel_bar.act_restore.triggered.connect(self._on_object_restore)
        self.sel_bar.act_change.triggered.connect(self._on_object_change)
        self.sel_bar.act_retire.triggered.connect(self._on_frame_retire)
        self.sel_bar.act_frame_restore.triggered.connect(self._on_frame_restore)
        self.sel_bar.act_notes.triggered.connect(self._on_notes)
        self.sel_bar.btn_notes.clicked.connect(self._on_notes)
        self.sel_bar.act_version_col.toggled.connect(self._on_version_col)
        self.sel_bar.btn_classic.clicked.connect(lambda: self.classic_requested.emit())
        # Skrót „ostatnio użyte" (R-S2b-12): lista jest pochodną dziennika, więc odświeża się
        # PRZY OTWARCIU menu, nie raz na budowie widoku — inaczej pokazywałaby stan sprzed gestów.
        self.sel_bar.btn_object.menu().aboutToShow.connect(self._sync_recent_objects)
        self.sel_bar.objectRecentPicked.connect(self._on_object_recent)
        rv.addWidget(self.sel_bar)

        self.macro_bar = MacroBar([])
        self.macro_bar.preview.connect(self._on_macro_preview)
        self.macro_bar.stage.connect(self._on_macro_stage)
        self.macro_bar.cleared.connect(self._on_macro_clear)

        self.rename_bar = RenameBar()                    # bliźniaczy panel obok makra (G3)
        self.rename_bar.preview.connect(self._on_rename_preview)
        self.rename_bar.stage.connect(self._on_rename_stage)
        self.rename_bar.cleared.connect(self._on_rename_clear)
        self.rename_bar.sourceChanged.connect(self._refresh_date_echo)
        self.rename_bar.template_editor.expandedChanged.connect(
            lambda on: self._settings().setValue(self._KLUCZ_WZORU_RENAMU, on))
        self.rename_bar.preview.connect(lambda _p: self._zapamietaj_uzycie_wzoru())
        self.rename_bar.stage.connect(lambda _p: self._zapamietaj_uzycie_wzoru())

        self.lineage_bar = LineageBar()                   # trzeci panel stacku (I-2d)
        self.lineage_bar.judged.connect(self._on_lineage_judged)
        self.lineage_bar.offset_asked.connect(self._on_lineage_offset)
        self.lineage_bar.frames_requested.connect(self._on_lineage_frames)
        # MOST „pokaż te klatki w Zbiorach" - wstrzykuje gospodarz
        # (`MainWindow.show_frames_in_collections`), bo tylko on zna nawigację. None = widok bez
        # gospodarza (testy samego gridu): wejście idzie wprost do `show_frames`, więc brak
        # wstrzyknięcia niczego nie psuje (wzór `run_stage_fn`).
        self.show_frames_fn = None
        self._lineage_frame_id = None       # cel gestu odniesienia (klatka stosu w panelu)
        # TAKT 3 gestu osi stosu — wstrzykuje gospodarz (`MainWindow`), bo tylko on zna Dostawę.
        # None = widok bez gospodarza (testy samego gridu): gest zapisuje, a zdanie mówi, gdzie
        # przeliczyć — dokładnie jak przed tą zmianą, więc brak wstrzyknięcia niczego nie psuje.
        # Wołane z NAZWĄ etapu Dostawy (`stack_lineage` po odniesieniu czasu, `lineage` po gestach
        # osi kalibracji) - zwraca powód odmowy albo `None`.
        self.run_stage_fn = None
        # Gesty ręki osi KALIBRACJI (E4-5) - zapis jedną klingą tutaj, panel tylko pyta.
        self.lineage_bar.calibrator_picked.connect(self._on_calibrator_picked)
        self.lineage_bar.calibrator_restored.connect(self._on_calibrator_restored)
        self.lineage_bar.calibration_count_asked.connect(self._on_calibration_count)
        # Zapis do plików TEJ powierzchni trzyma blokadę bazy jak etap w tle - panel gaśnie i wtedy.
        # Flaga z sygnału, nie `self._wb.is_busy`: uchwyt ogłasza start, ZANIM ustawi swój wątek.
        self._zapis_wlasny = False
        self._wb.busy_changed.connect(self._on_wlasny_zapis_plikow)

        self.panel_stack = _PanelStack()                 # najwyżej JEDEN panel widoczny (F3)
        self.panel_stack.addWidget(self.macro_bar)
        self.panel_stack.addWidget(self.rename_bar)
        self.panel_stack.addWidget(self.lineage_bar)
        self.panel_stack.setVisible(False)               # żaden panel nie otwarty na starcie
        # PANEL BIERZE TYLE, ILE POTRZEBUJE — NADMIAR NALEŻY DO TABELI (wiz T2 N1). Domyślna
        # polityka `QStackedWidget` jest pionowo Expanding, więc stack pochłaniał leftover i stał
        # 309 px WYSOKI także wtedy, gdy niósł jedno zdanie (`sizeHint` 36 px): panel zjadał połowę
        # okna, a tabela pokazywała 10 wierszy ze 128. Samo skrócenie treści panelu tego nie ruszyło
        # — bo o wysokości decydowała polityka, nie treść.
        self.panel_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        rv.addWidget(self.panel_stack)

        self.model = GridTableModel(self)
        # Zdarzenia dostępności zmiany zaznaczenia z zakresów, nie z listy wszystkich komórek - Ctrl+A
        # i odtworzenie dużego zaznaczenia bez sekund przy aktywnym kliencie UI Automation (AR-202).
        self.table = _TabelaKlatek()
        self.table.setModel(self.model)
        # Układ belek grup (na całą szerokość) i kolumny „Wersja" (za „Ścieżką") żyje w WIDOKU,
        # więc odnawia się po KAŻDYM resecie modelu - także po sorcie z nagłówka i po podglądzie
        # klingi, które nie przechodzą przez `_refresh` (`_uloz_belki_i_wersje`).
        self._szerokosci_przed_resetem = {}   # znaczenie kolumny → szerokość (`_zapamietaj_szerokosci`)
        self._znaczenia_kolumn = []           # znaczenie per numer kolumny w ostatnim układzie
        self.model.modelAboutToBeReset.connect(self._zapamietaj_szerokosci)
        self.model.modelReset.connect(self._uloz_belki_i_wersje)
        # Debounce panelu daty: `selectionChanged` może sypać setki eventów przy zaznaczeniu wsadu
        # → przelicz echo raz, po 150 ms ciszy (R1 #15).
        self._date_timer = QTimer(self); self._date_timer.setSingleShot(True); self._date_timer.setInterval(150)
        self._date_timer.timeout.connect(self._refresh_date_echo)
        # Panel rodowodu wisi na TYM SAMYM debouncie (I-2d): oba czytają zaznaczenie, oba tylko przy
        # własnym otwartym panelu, więc drugi timer byłby drugim właścicielem tego samego zdarzenia.
        self._date_timer.timeout.connect(self._refresh_lineage)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._on_selection_changed())
        # NAGŁÓWEK Z WŁASNYM MODELEM ZAZNACZENIA (AR-187, AR-202): malowanie sekcji pyta model zaznaczenia
        # nagłówka, czy kolumna jest zaznaczona (`isColumnSelected` idzie po wierszach z `flags()`) -
        # przy KAŻDYM malowaniu nagłówka, także z wyłączonym podświetleniem sekcji (Qt 6.9.2 liczy
        # sąsiadów sekcji do opcji stylu). Wspólny z tabelą przy pełnym zaznaczeniu, natywnie, kopia
        # pf4 (16 998 klatek × 15 kolumn): 511 875 wywołań, Ctrl+A 4,0-7,1 s także po
        # `setHighlightSections(False)`; własny, pusty - 1 933 wywołania (kadr tabeli), 149-403 ms.
        # Wiersze zaznacza się w tabeli (`SelectRows`), więc odcięcie nagłówka zabiera wyłącznie
        # podświetlenie sekcji kolumn przy zaznaczeniu.
        self._zaznaczenie_naglowka = QItemSelectionModel(self.model, self.table)
        self.table.horizontalHeader().setSelectionModel(self._zaznaczenie_naglowka)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # EDYCJA KOMÓRKI KEYWORDA (AR-61): dwuklik albo F2 na komórce, którą model uznał za
        # edytowalną (`GridTableModel._komorka_edytowalna`). Wpis idzie do szuflady tą samą klingą
        # co makro (`_on_cell_edit`); zajętość zdejmuje wyzwalacze (`_sync_edycji`).
        self._edit_triggers = QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        self.table.setEditTriggers(self._edit_triggers)
        self.table.setItemDelegate(_EdycjaKomorki(self.table))
        self.model.cell_edit_requested.connect(self._on_cell_edit)
        # Zamknięty edytor oddaje drogę wynikowi składu odłożonemu na czas pisania (AR-27). Po obrocie
        # pętli: widok najpierw kończy edycję (zatwierdzenie stage'uje, edytor znika), dopiero potem reset.
        self.table.itemDelegate().closeEditor.connect(
            lambda *_: QTimer.singleShot(0, self._przyloz_odlozony))
        # Edytor otwarty w chwili resetu modelu (odświeżenie z wątku pól, sort, podgląd) jest
        # domykany z zapisem PRZED resetem - reset niszczy edytor i unieważnia jego indeks.
        self._podglad_edycji = "teraz"      # „teraz" / „pozniej" (w resecie) / „bez" (widok znika)
        self.model.modelAboutToBeReset.connect(lambda: self._domknij_edycje("pozniej"))
        # ZAZNACZENIE PRZEŻYWA RESET BEZ NOWYCH DANYCH (AR-187): sort z nagłówka, „Grupuj wg”, podgląd
        # klingi i prezentacja przebudowują te same wiersze. Połączone PO domknięciu edytora i PO
        # układzie belek - sloty idą w kolejności połączeń, więc migawka widzi stan końcowy, a
        # odtworzenie - przebudowany model i odnowione znaczenia kolumn (`_uloz_belki_i_wersje`).
        self._migawka_resetu = None
        self.model.modelAboutToBeReset.connect(self._zaznaczenie_przed_resetem)
        self.model.modelReset.connect(self._zaznaczenie_po_resecie)
        self.table.setAlternatingRowColors(True)   # zebra: skanowalność długich list (P3-5)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        # MENU KONTEKSTOWE TABELI - dom gestu „Zostaw tę wersję" (perspektywa „Wersje stosów").
        # Nie pasek zbioru: `sel_bar` trzyma już osiem przycisków, a podłoga okna jest mierzona
        # - dziewiąty poszerzałby ją w KAŻDEJ perspektywie dla gestu, który ma sens w jednej.
        # Nie menu „Klatka": tamto jest osią żywotności z własnym słownikiem powodów wygaszenia,
        # a wspólna kontrolka kazałaby jednemu tooltipowi tłumaczyć dwie osie (argument D-OW-6).
        # Gest działa na JEDNYM wierszu („tę wersję"), więc prawy klik na wierszu jest jego
        # naturalnym miejscem. Menu powstaje RAZ (wzorzec puli `set_recent_objects`: tworzenie
        # i kasowanie menu per klik zostawiało sieroty albo odroczone usunięcia), a stan akcji
        # ustawia `_sync_menu_wersji` tuż przed pokazaniem.
        # DRUGI DOM W TYM SAMYM MENU: drogi wyjścia z izolacji zapisu w miejscu (warunek wsadu
        # AR-17 (2)) - „Dokończ zapis", „Przywróć nagłówek sprzed zapisu", „Zwolnij plik do
        # skanu…". Ten sam argument co wyżej: gesty dotyczą KOPII kilku klatek w dwóch
        # perspektywach, a dziewiąta kontrolka paska zbioru poszerzałaby podłogę okna w każdej.
        # Nie menu „Klatka": izolacja jest stanem pliku, nie żywotności klatki (D-OW-6). Sekcja
        # zapisu pokazuje się w perspektywach „Plik po przerwanym zapisie" / „Zapis czeka na
        # dokończenie" i nad każdą klatką z kopią izolowaną; poza tym prawy klik zostaje tym, czym
        # był (niczym). Jedno menu, nie dwa: stos z kopią izolowaną w „Wersjach stosów" ma
        # dostać obie sekcje naraz.
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_menu)
        self._menu_tabeli = QMenu(self.table)
        self._menu_tabeli.setToolTipsVisible(True)   # powód wygaszenia niesie tooltip POZYCJI
        self.act_keep_version = self._menu_tabeli.addAction(i18n.t("grid.version.keep"))
        self.act_keep_version.triggered.connect(self._on_keep_version)
        # WERDYKT GRUPY (AR-10, 0026) obok gestu wersji: „zostawiam wszystkie" i jego droga powrotu.
        # Widoczna zawsze jedna z dwóch - ta, która ma sens dla grupy pod kursorem.
        self.act_keep_all_versions = self._menu_tabeli.addAction(i18n.t("grid.version.keep_all"))
        self.act_keep_all_versions.triggered.connect(self._on_keep_all_versions)
        self.act_reopen_versions = self._menu_tabeli.addAction(i18n.t("grid.version.reopen"))
        self.act_reopen_versions.triggered.connect(self._on_reopen_versions)
        self._sep_zapisu = self._menu_tabeli.addSeparator()
        self.act_finish_write = self._menu_tabeli.addAction(i18n.t("grid.inplace.finish"))
        self.act_finish_write.triggered.connect(self._on_finish_write)
        self.act_restore_header = self._menu_tabeli.addAction(i18n.t("grid.inplace.restore"))
        self.act_restore_header.triggered.connect(self._on_restore_header)
        # „Zwolnij…" za własną kreską (AR-30): dwa gesty wyżej rozstrzyga rdzeń kontrolą pliku,
        # zwolnienie jest rozstrzygnięciem człowieka bez sprawdzenia - nie stoi w jednym rzędzie
        # z bezpiecznymi.
        self._sep_zwolnienia = self._menu_tabeli.addSeparator()
        self.act_release_file = self._menu_tabeli.addAction(i18n.t("grid.inplace.release"))
        self.act_release_file.triggered.connect(self._on_release_file)
        # AR-41: przeniesienie faktów ręki - wyłącznie w perspektywie „Zastąpione": klatka
        # zastąpiona niesie werdykt ręki, a plik niesie dziś następczyni.
        self._sep_przeniesienia = self._menu_tabeli.addSeparator()
        self.act_transfer_facts = self._menu_tabeli.addAction(i18n.t("supersede.transfer.action"))
        self.act_transfer_facts.triggered.connect(self._on_transfer_facts)
        # AR-4/AR-23: „Ta kopia prowadzi" - podmenu z OBECNYMI kopiami jednej klatki, które czeka na
        # wskazanie kopii wiodącej (perspektywy „Kopie niezgodne" / „Zeznanie z nieobecnej kopii"
        # albo taka klatka pod kursorem gdziekolwiek). Pozycje kopii składa `_sync_menu_kopii` przy
        # każdym pokazaniu: lista kopii jest stanem pliku i bazy z tej chwili, nie z budowy menu.
        self._sep_kopii = self._menu_tabeli.addSeparator()
        self._menu_kopii = self._menu_tabeli.addMenu(i18n.t("grid.lead.menu"))
        self._menu_kopii.setToolTipsVisible(True)
        # AR-17 krok 3: „Uzgodnij pliki…" - wyłącznie w perspektywie „Plik nie zgadza się
        # z obiektem". Gest tej jednej perspektywy, więc menu prawego kliku (ten sam argument co
        # przy izolacji zapisu: kontrolka paska poszerzałaby podłogę okna w każdej perspektywie).
        self._sep_zgodnosci = self._menu_tabeli.addSeparator()
        self.act_align_files = self._menu_tabeli.addAction(i18n.t("grid.sel.object_change_align"))
        self.act_align_files.triggered.connect(self._on_align_files)
        # AR-129: „Popraw f/ w plikach…" - wyłącznie w perspektywie „f/ niezgodna z teleskopem".
        # Na życzenie: gest stawia wpisy w szufladzie zapisu (ta sama droga co edycja komórki),
        # a zapis i cofnięcie robi szuflada - plik zmienia się dopiero po „Zapisz".
        self._sep_optyki = self._menu_tabeli.addSeparator()
        self.act_fix_optics = self._menu_tabeli.addAction(i18n.t("grid.optics.fix_action"))
        self.act_fix_optics.triggered.connect(self._on_fix_optics)
        # AR-178: „Odrzuć nowsze niż obraz we wszystkich obrazach" - wyłącznie w perspektywie
        # „Rodowód z klatkami nowszymi niż obraz". Gest jednej perspektywy na CAŁYM widoku, więc
        # menu prawego kliku, nie panel: panel „Rodowód" mówi o jednym obrazie.
        self._sep_nowszych = self._menu_tabeli.addSeparator()
        self.act_reject_newer_all = self._menu_tabeli.addAction(i18n.t("grid.lin.reject_newer_all"))
        self.act_reject_newer_all.triggered.connect(self._on_reject_newer_all)
        rv.addWidget(self.table, 1)   # stretch: nadmiar pionu należy do TABELI, nie do panelu (N1)

        # PUSTY STAN = ZDANIE + GEST (FH-4). `self.empty` zostaje etykietą z tekstem (kontrakt testów
        # i sond: `empty.text()`, `empty.isVisible()`), a przycisk stoi obok niej w jednym pojemniku,
        # który przejmuje stretch - oba jadą razem na środek pustej przestrzeni. Przycisk WYKONUJE
        # receptę, którą pusty stan podaje (`wykonaj_recepte_powrotu` z celem `_CEL_WIDOK`), zamiast
        # ją tylko opisywać. Lambda, nie sam slot: `clicked` niesie `checked: bool`, a cel jest
        # keyword-only właśnie po to, żeby ten bool nie wpadł w jego miejsce.
        self.empty_box = QWidget()
        eb = QVBoxLayout(self.empty_box); eb.setContentsMargins(0, 0, 0, 0)
        eb.addStretch(1)
        self.empty = QLabel(i18n.t(_EMPTY_FILTER))
        self.empty.setAlignment(Qt.AlignCenter); self.empty.setWordWrap(True); self.empty.setVisible(False)
        eb.addWidget(self.empty)
        self.empty_btn = QPushButton()
        # Gest przycisku ustala `_ustaw_pusty_stan`: recepta powrotu albo Dostawa (perspektywa kopii,
        # której pustka jest niewiedzą). Flaga czytana W CHWILI KLIKU, jak decyzja recepty.
        self._pusty_do_dostawy = False
        self.empty_btn.clicked.connect(
            lambda: self.open_intake.emit() if self._pusty_do_dostawy
            else self.wykonaj_recepte_powrotu(cel=_CEL_WIDOK))
        self.empty_btn.setVisible(False)
        eb.addWidget(self.empty_btn, 0, Qt.AlignHCenter)
        eb.addStretch(1)
        self.empty_box.setVisible(False)
        rv.addWidget(self.empty_box, 1)   # stretch: pusty stan zbiera leftover - SelectionBar/panel nie balonieją (wiz F3 #1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        outer.addWidget(splitter, 1)   # stretch: grid dominuje okno (doktryna §5), pasek nie zjada połowy (P2-1)

        self.drawer = StagingDrawer()  # stała szuflada dolna stagingu (doktryna §5)
        self.drawer.commit.connect(self._on_commit)
        self.drawer.reject.connect(self._on_reject)
        self.drawer.cancel.connect(self._on_wb_cancel)
        outer.addWidget(self.drawer)

    # ---- facety / perspektywy ----
    def _load_facets(self):
        """Przeładuj to, co widok wie o SCHEMACIE archiwum: pokrycie pól (zamówione - patrz
        `_zamow_pola`) i listę perspektyw (synchronicznie, bo to kilka wierszy `saved_query`).
        Woła gospodarz po przebiegu Dostawy i sam widok przy budowie."""
        self._zamow_pola()
        self._odbuduj_perspektywy()

    # ---- pokrycie pól (panel „Pola", keywordy filtra i makra) ----
    def _zamow_pola(self):
        """Poproś o pokrycie pól. W trybie wątku wraca od razu; wynik przychodzi do `_on_pola_done`.
        Prośba w trakcie biegu nie odpala drugiego wątku: bieżący wynik jest już starszy niż prośba
        (generacja), więc trafia do kosza, a po jego końcu rusza jeden bieg więcej (`_sprzataj_pola`)."""
        if self._pola_stop:
            return
        self._pola_gen += 1
        if self._pola_worker is not None:
            self._pola_ponow = True
            return
        self._start_pola()

    def _start_pola(self):
        worker = PolaWorker(self._pola_gen, self._pola_odcisk,
                            db_path=self._db_path if self._pola_async else None,
                            con=None if self._pola_async and self._db_path else self.con)
        worker.done.connect(self._on_pola_done)
        worker.failed.connect(self._on_pola_failed)
        self._pola_worker = worker
        if self._pola_async and self._db_path:
            # Listwa w trakcie liczenia mówi „liczę", a pokazuje stan POPRZEDNI - pusta lista
            # udawałaby archiwum bez ani jednego pola.
            self.fields.set_stan("liczy")
            self._pola_thread = QThread(self)
            worker.moveToThread(self._pola_thread)
            self._pola_thread.started.connect(worker.run)
            worker.finished.connect(self._pola_thread.quit)
            self._pola_thread.finished.connect(self._sprzataj_pola)
            self._pola_thread.start()
        else:
            try:
                worker.run()               # inline: done/failed lecą direct = synchronicznie
            finally:
                self._pola_worker = None

    def _sprzataj_pola(self):
        """Koniec wątku pokrycia. ŚWIĘTA KOLEJNOŚĆ jak w `planner._cleanup_thread` (deadlock AB-BA
        GIL × ~QThread): worker.deleteLater → wait → thread.deleteLater. Wątek już zebrany przez
        `zatrzymaj_pola` nie ma tu czego sprzątać - wtedy wracamy od razu."""
        if self._pola_thread is None:
            return
        self._pola_worker.deleteLater()
        self._pola_thread.wait()
        self._pola_thread.deleteLater()
        self._pola_worker = None
        self._pola_thread = None
        if self._pola_ponow and not self._pola_stop:
            self._pola_ponow = False
            self._start_pola()

    def zatrzymaj_pola(self):
        """Widok znika (zamknięcie okna, przełączenie bazy): przerwij liczenie i ZBIERZ wątek, zanim
        rodzic go skasuje - `QThread` niszczony w biegu to twardy abort aplikacji. Wynik, który
        zdążył wyjść z wątku, trafia do kosza generacją, więc nie dotknie widoku ani zamkniętego
        połączenia. Przerwanie powtarzamy co 100 ms: `interrupt` trafiony w chwilę między dwoma
        zapytaniami workera nie działa, a kolejne łapie już zapytanie w locie. Idempotentne.

        To jest też jedyny moment, w którym gospodarz mówi widokowi „znikasz" PRZED zamknięciem
        połączenia (`MainWindow._zatrzymaj_watki_widokow`) - więc otwarty edytor komórki (AR-61)
        jest domykany z zapisem do szuflady tutaj, póki połączenie żyje.

        Zbiera też wątek składu zbioru (`ZbiorWorker`, AR-27) - gospodarz pyta o tę metodę po nazwie,
        a „widok znika" dotyczy obu wątków tła naraz."""
        self._domknij_edycje("bez")
        self._pola_stop = True
        self._zatrzymaj_zbior()
        self._pola_ponow = False
        self._pola_gen += 1
        if self._pola_thread is None:
            return
        self._pola_worker.request_cancel()
        self._pola_thread.quit()           # pętla wątku kończy się zaraz po `run()` (quit z góry)
        self._pola_worker.deleteLater()
        while not self._pola_thread.wait(100):
            self._pola_worker.request_cancel()
        self._pola_thread.deleteLater()
        self._pola_worker = None
        self._pola_thread = None

    @Slot(int, object, object)
    def _on_pola_done(self, gen, odcisk, pola):
        if gen != self._pola_gen:
            return                         # starszy niż ostatnia prośba - świeży bieg już zamówiony
        self._pola_odcisk = odcisk
        self.fields.set_stan(None)
        if pola is not None:               # None = karty bez zmian, listwa zostaje, jaka jest
            self._zastosuj_pola(pola)

    @Slot(int, str)
    def _on_pola_failed(self, gen, msg):
        if gen != self._pola_gen:
            return
        # Odcisk zostaje przy ostatnim ZASTOSOWANYM wyniku, więc kolejna prośba policzy od nowa.
        # Listwa trzyma stan poprzedni i mówi, że go nie odświeżyła.
        self.fields.set_stan("blad")
        self.status_message.emit(i18n.t("grid.fields.failed_status", msg=msg))

    def _zastosuj_pola(self, facets):
        """Pokrycie → panel Pól, keywordy filtra i makra. Zaznaczenia usera PRZEŻYWAJĄ przeliczenie:
        kolumny domyślne (6 najczęstszych keywordów spoza szumu strukturalnego) wybieramy tylko przy
        PIERWSZYM wyniku, potem odpadają jedynie kolumny, których keywordu nie ma już w żadnej karcie
        (bez tego zostałaby kolumna bez pola do jej odznaczenia)."""
        pierwszy = self._pola is None
        self._pola = facets
        self._all_keywords = [f["keyword"] for f in facets]
        if pierwszy and not self._columns:     # puste kolumny PÓŹNIEJ to wybór człowieka, nie brak
            kolumny = [f["keyword"] for f in facets if f["keyword"] not in STRUCT_NOISE][:6]
        else:
            znane = set(self._all_keywords)
            kolumny = [c for c in self._columns if c in znane]
        zmiana = kolumny != self._columns
        self._columns = kolumny
        self._wypelnij_pola()
        self.filter_panel.set_keywords(self._all_keywords)
        self.macro_bar.set_keywords(self._all_keywords)
        if zmiana and self._zbudowany:
            self.przeladuj_z_zaznaczeniem()  # model tabeli niesie kolumny - bez tego zostałyby stare

    def przeladuj_z_zaznaczeniem(self):
        """Przeładowanie zbioru NIE-NAWIGACYJNE - zbiór ten sam, zmienia się jego widok albo dane:
        wynik Pól, kolumny ręką, kolumna „Wersja", grupowanie po wersji, przebieg Dostawy, gest osi
        obiektu z innego okna (AR-164, AR-172). Zaznaczenie, bieżąca komórka i wybór w panelu
        rodowodu wracają po przyłożeniu.

        RESET MODELU ZOSTAJE I TO JEST ROZSTRZYGNIĘCIE, NIE ZANIECHANIE: kolumna-keyword niesie
        komórki z `cards_pivot` liczonego po CAŁYM zbiorze (skład w tle, AR-27) oraz własny kierunek
        (liczbowa vs tekstowa), sort i belki grup - wstawienie kolumn bez resetu byłoby drugą drogą
        składu w modelu. Reset zdejmuje jednak zaznaczenie: wizytacja natywna zmierzyła pierwszy
        wynik Pól 2,5-3,3 s po wejściu w Zbiory, a zaznaczenie zrobione w tym oknie znikało razem
        z panelem rodowodu („Zaznacz w tabeli…").

        ZLECENIE NIESIE ZNACZNIK GENERACJI, MIGAWKĘ ROBI PRZYŁOŻENIE (`_zastosuj_zbior`). Migawka
        z chwili zlecenia cofała wybór zrobiony w oknie przeładowania: tabela stoi wtedy w
        `NoSelection`, ale combo nocy i lista panelu rodowodu działają. Nowsze zlecenie dowolnej INNEJ
        przyczyny (nawigacja, filtr, gest) podbija generację - znacznik przestaje pasować, a tamten
        zbiór ma własne zaznaczenie. Dwa przeładowania tej klasy z rzędu: drugie dziedziczy znacznik
        pierwszego (drugi wynik Pól w trakcie składu po pierwszym, wynik Pól po Dostawie). Zbiór
        w drodze z innej przyczyny - znacznika nie stawiamy: tamto przyłożenie i tak zdejmie
        zaznaczenie albo odłoży cel gestu.

        Znacznik stoi PRZED `refresh`: widok bez wątku (testy, `:memory:`) składa synchronicznie."""
        self._oznacz_przeladowanie_z_zaznaczeniem()
        self.refresh(w_tle=True)

    def _oznacz_przeladowanie_z_zaznaczeniem(self):
        """Znacznik generacji przeładowania nie-nawigacyjnego (reguła w `przeladuj_z_zaznaczeniem`) dla
        wołającego, który zleca przeładowanie własną drogą - ogon zapisu i cofnięcia szuflady
        (`_przeladuj_po_gescie`, AR-187). Wołany TUŻ PRZED zleceniem."""
        if (not self._zbior_w_drodze()
                or self._przeladowanie_z_zaznaczeniem == self._zbior_gen):
            # generacja TEGO przeładowania (`refresh` podbija ją pierwszą)
            self._przeladowanie_z_zaznaczeniem = self._zbior_gen + 1

    def _stan_panelu(self):
        """Wybór człowieka w panelu rodowodu jako argumenty `_refresh_lineage` - zaznaczone wiersze
        listy, relacja osi kalibracji, noc trybu propozycji (AR-172); `{}` przy zamkniętym panelu."""
        if not self._lineage_panel_open():
            return {}
        bar = self.lineage_bar
        return {"select_frame_ids": bar.selected_frame_ids() or None,
                "select_relation": bar.selected_relation(),
                "select_night": bar.selected_night()}

    def _migawka_zaznaczenia(self):
        """Zaznaczenie tabeli po TOŻSAMOŚCI, nie po numerach (reset przenumerowuje wiersze, a nowe
        kolumny przesuwają numery kolumn): `(frame_id zaznaczonych, frame_id bieżącego wiersza,
        znaczenie bieżącej kolumny, stan panelu rodowodu - `_stan_panelu`)` albo `None` bez
        zaznaczenia. Bieżący wiersz i kolumnę trzymamy OSOBNO - nie musi to być pierwszy zaznaczony
        wiersz ani kolumna 0 (kotwica Shift i komórka, na której stoi klawiatura).

        ZNACZENIE KOLUMNY Z OSTATNIEGO UKŁADU (`_znaczenia_kolumn`), nie z modelu: migawka bywa brana
        w `modelAboutToBeReset` (AR-187), a `set_base_columns` zmienia kolumny bazowe PRZED
        `beginResetModel` - model opisuje wtedy już układ następny (ta sama figura, co
        `_zapamietaj_szerokosci`). Poza resetem oba źródła mówią to samo."""
        wiersze = self._selected_data_rows()
        if not wiersze:
            return None
        biezacy = kolumna = None
        idx = self.table.currentIndex()
        if idx.isValid() and 0 <= idx.row() < len(self.model._rows):
            wiersz = self.model._rows[idx.row()]
            if isinstance(wiersz, dict) and "_group" not in wiersz:
                biezacy = wiersz.get("frame_id")
            if idx.column() < len(self._znaczenia_kolumn):
                kolumna = self._znaczenia_kolumn[idx.column()]
        return [r["frame_id"] for r in wiersze], biezacy, kolumna, self._stan_panelu()

    def _zaznaczenie_przed_resetem(self):
        """Migawka zaznaczenia przed resetem modelu BEZ NOWYCH DANYCH (AR-187): sort klikiem
        w nagłówek, „Grupuj wg”, podgląd klingi i jego zdjęcie, przełączenie prezentacji. Ta sama
        migawka, co przy przeładowaniu nie-nawigacyjnym (`_migawka_zaznaczenia`, AR-172); reset
        `set_data` jej nie dostaje - nowy zbiór ma własną regułę (`reset_tych_samych_wierszy`).

        Reset jest synchroniczny: między tą migawką a odtworzeniem (`_zaznaczenie_po_resecie`) nie ma
        obrotu pętli, więc nie nadpisze ona wyboru, który człowiek zrobiłby w trakcie. Obok migawki
        dwa fakty z tej chwili: czy bieżąca komórka była w kadrze (reguła kadru) i czy debounce
        paneli czekał na zmianę zaznaczenia, której jeszcze nie odbiły."""
        self._migawka_resetu = None
        if not self.model.reset_tych_samych_wierszy():
            return
        migawka = self._migawka_zaznaczenia()
        if migawka is None:
            return
        # Kadr z geometrii NAGŁÓWKÓW, nie `visualRect`: ten pyta model, a `set_base_columns` zmienia
        # kolumny przed `beginResetModel` - numer bieżącej kolumny wskazuje wtedy poza układ
        # (zmierzone: `IndexError` w `headerData` przy przełączeniu prezentacji).
        t, idx = self.table, self.table.currentIndex()
        vp = t.viewport().rect()
        y = t.rowViewportPosition(idx.row()) if idx.isValid() else -1
        x = t.columnViewportPosition(idx.column()) if idx.isValid() else -1
        widoczna = (idx.isValid() and y + t.rowHeight(idx.row()) > 0 and y < vp.height()
                    and x + t.columnWidth(idx.column()) > 0 and x < vp.width())
        self._migawka_resetu = (migawka, widoczna, self._date_timer.isActive())

    def _zaznaczenie_po_resecie(self):
        """Odtworzenie zaznaczenia po resecie bez nowych danych (AR-187) - zbiór klatek ten sam, więc
        wraca całe: zaznaczenie po `frame_id`, bieżąca komórka po klatce i znaczeniu kolumny.

        KADR: pion po takim resecie Qt zostawia (zmierzone: 142/284 → 142/284 po sorcie i po
        podglądzie), więc bieżąca komórka widoczna przed resetem wraca z najmniejszym przewinięciem,
        które ją pokazuje (przy podglądzie wiersze stoją - zero ruchu), a niewidoczna (człowiek
        przewinął gdzie indziej) - bez przewijania. Środek kadru jak po przeładowaniu zbioru skakałby
        przy każdym „Podglądzie” makra i każdej edycji komórki.

        PANELE: odtworzenie emituje `selectionChanged` (licznik paska mówi prawdę - sam reset jest
        cichy), a debounce paneli daty i rodowodu nie ma czego przebudować, gdy przed resetem nie
        czekał: zbiór zaznaczenia jest ten sam, a przebudowa zgubiłaby wybór w panelu. Gdy czekał
        (zmiana zaznaczenia tuż przed resetem), panele odświeżają się od razu Z WYBOREM w panelu
        z migawki - jak po przyłożeniu zbioru (`_zastosuj_zbior`).

        WRACA ZAWSZE, BEZ WZGLĘDU NA WIELKOŚĆ (AR-202): odtworzenie to jedno `select()`, a zdarzenie
        dostępności liczy się z zakresów (`_TabelaKlatek`) - natywnie, kopia pf4, 16 998 zaznaczonych,
        koszt widziany: sort 233-518 ms, „Grupuj wg” 224-540 ms, postawienie podglądu 187-448 ms (rozrzut
        to obciążenie maszyny: ten sam sort bez zaznaczenia 117-313 ms). Dawny próg kosztu
        zdejmował duże zaznaczenie i zmieniał tym cel następnego gestu („Do stagingu” nazw bez
        zaznaczenia obejmuje cały widok)."""
        stan, self._migawka_resetu = self._migawka_resetu, None
        if stan is None:
            return
        (zaznaczone, biezacy, kolumna, panel), widoczna, czekal = stan
        self._przywroc_zaznaczenie(zaznaczone, biezacy=biezacy, kolumna=kolumna,
                                   kadr=QAbstractItemView.EnsureVisible if widoczna else None)
        self._date_timer.stop()
        if czekal:
            self._refresh_date_echo()
            self._refresh_lineage(**panel)

    def _wypelnij_pola(self):
        """Lista Pól z OSTATNIEGO pokrycia i bieżących kolumn. Szum strukturalny na DÓŁ (stabilnie
        w obrębie grup - pokrycie zachowane), P3-6. Bez pokrycia (pierwszy wynik jeszcze w drodze)
        nie ma czego pokazać - zaznaczenia odda `_zastosuj_pola`, czytając `_columns`."""
        if self._pola is None:
            return
        ordered = sorted(self._pola, key=lambda f: f["keyword"] in STRUCT_NOISE)
        self.fields.load(ordered, set(self._columns))

    def _odbuduj_perspektywy(self):
        # perspektywy: presety (kod) + zapisane w BAZIE (I-1)
        # POZYCJA PRZEŻYWA ODBUDOWĘ LISTY (bliźniak BP-5 w `_load_facets`): `clear()` zostawiał indeks
        # 0, a gospodarz woła tę metodę z `refresh()` po każdym przebiegu Dostawy - combo mówiło wtedy
        # „Przegląd" nad zbiorem z trimem. Wracamy na tę samą pozycję PO DANYCH i bez sygnału, bo stan
        # się nie zmienił. Pozycji, której już nie ma, tu nie zgadujemy: rozstrzyga właściciel
        # etykiety na końcu `_refresh`.
        biezaca = self.combo_persp.currentData()
        self.combo_persp.blockSignals(True)
        self.combo_persp.clear()
        for name in PRESETS:
            self._dodaj_perspektywe(i18n.t(_PRESET_LABELS[name]), ("preset", name))
        for name, spec in self._saved_perspectives():
            # Wiersz, którego nie umiemy zastosować (`spec is None` — stary `sql_text` z 0013),
            # ZOSTAJE NA LIŚCIE i mówi to wprost. Ukrycie go byłoby zniknięciem cudzej pracy bez
            # słowa; wybór kończy się statusem, nie pustym filtrem.
            label = f"★ {name}" if spec is not None else f"★ {name} ⚠"
            self._dodaj_perspektywe(label, ("saved", name))
        for i in range(self.combo_persp.count()):
            if self.combo_persp.itemData(i) == biezaca:
                self.combo_persp.setCurrentIndex(i)
                break
        self.combo_persp.blockSignals(False)
        self._oznacz_zmiane_perspektywy()   # sufiks „(zmieniona)" przeżywa odbudowę listy (FH-12)

    def _dodaj_perspektywe(self, etykieta, data):
        """Pozycja listy perspektyw z etykietą BAZOWĄ w osobnej roli - tekst pozycji bywa etykietą
        z sufiksem „(zmieniona)" (FH-12), a sufiks liczy się zawsze od nazwy, nie od tekstu."""
        self.combo_persp.addItem(etykieta, data)
        self.combo_persp.setItemData(self.combo_persp.count() - 1, etykieta, _ROLA_ETYKIETY)

    def _settings(self):
        return QSettings("Horreum", "Horreum")

    def _saved_perspectives(self):
        """Perspektywy z BAZY — `[(nazwa, spec|None), …]`. Rejestru już nie czytamy: to, co w nim
        było, wciągnął jednorazowy import przy budowie widoku."""
        return queries.perspectives(self.con)

    def _import_settings_perspectives(self):
        """JEDNORAZOWY, IDEMPOTENTNY import perspektyw z rejestru użytkownika do bazy (I-1).

        Wydanie publiczne zapisywało je w `QSettings` (D-B), więc przeniesienie kanonu do bazy bez
        tego kroku skasowałoby użytkownikom nazwane widoki — regresja, nie sprzątanie (FORWARD).
        Rejestru NIE czyścimy: koszt jest zerowy, a zostawiona kopia ratuje kogoś, kto wróci na
        starsze wydanie. Powtórzenie importu jest darmowe, bo `repo.save_perspective` przy
        identycznej treści nie pisze i nie emituje eventu — dlatego nie ma tu flagi „już zrobione",
        która i tak nie przeżyłaby przesiadki na drugą maszynę.

        Nazwa ISTNIEJĄCA W BAZIE wygrywa z rejestrową: baza jest teraz kanonem, a import ma
        dowieźć to, czego w niej nie ma, nie cofać czyjegoś zapisu do stanu sprzed przesiadki."""
        raw = self._settings().value("grid/perspectives", "{}")
        try:
            store = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(store, dict) or not store:
            return
        znane = {name for name, _spec in queries.perspectives(self.con)}
        for name, spec in store.items():
            if name not in znane and isinstance(spec, dict):
                repo.save_perspective(self.con, name=name, spec=spec, now=self._now())

    def _on_perspective(self):
        data = self.combo_persp.currentData()
        if not data:
            return
        kind, name = data
        spec = self._spec_pozycji(data)
        if spec is None:
            # Perspektywa jest, ale nie umiemy jej zastosować (stary `sql_text` z migracji 0013).
            # MÓWIMY to wprost: zastosowanie pustego spec-a zdjęłoby filtr i wyglądałoby na
            # „perspektywa pokazuje wszystko", czyli cichy fałsz zamiast pytania.
            if kind == "saved":
                self.status_message.emit(i18n.t("grid.persp.unreadable", name=name))
            return
        for atrybut, _ in _TRIMY:
            setattr(self, atrybut, bool(spec.get(_klucz_spec(atrybut))))
        self._filter_tree = spec.get("filter")
        self.note_query = None      # perspektywa definiuje CAŁY zbiór - tekst uwag nie jest jej częścią
        self._zdejmij_wskazane()    # …klatki wskazane z panelu też nie
        self._terminy = []
        # F4R#2: stan facetów resetowany dla KAŻDEJ perspektywy (preset ORAZ zapisana) — perspektywa
        # definiuje CAŁY zbiór; stara zapisana bez klucza "facets" MUSI zerować stan, inaczej facety
        # poprzedniego wyboru wyciekają w nowy zbiór. Rail przeładuje refresh() (set_data).
        # Kopia, nie referencja: preset z facetami („Gotowe obrazy”) dzieliłby obiekt z `PRESETS`,
        # a pierwsza mutacja stanu w miejscu zepsułaby preset na całą sesję.
        self._facet_state = copy.deepcopy(spec.get("facets")) or facet_model.empty_state()
        self.filter_panel.set_tree(self._filter_tree)   # panel odbija filtr perspektywy (P3-3);
        # set_tree dostaje TYLKO advanced — facety NIGDY nie idą w płaski panel (nota R2, P3-3 wyżej)
        gb = spec.get("group_by")
        idx = self.combo_group.findData(gb)
        self.combo_group.blockSignals(True)
        self.combo_group.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_group.blockSignals(False)
        if "columns" in spec:
            # Zaznaczenia z OSTATNIEGO pokrycia, nie z nowego zapytania: przełączenie perspektywy
            # liczyło tu pokrycie całego archiwum na wątku GUI (sekundy na żywej bazie), choć
            # zmienia wyłącznie to, które pola są zaznaczone.
            self._columns = list(spec["columns"])
            self._wypelnij_pola()
        self._wyglad_z_perspektywy(spec)
        self._zdejmij_wynik_gestu_zapisu()
        # Stan JEST teraz definicją pozycji - sufiks „(zmieniona)" schodzi od razu, także z pozycji,
        # z której widok właśnie zszedł (w tle zbiór dojedzie później, a lista mówi już dziś).
        self._oznacz_zmiane_perspektywy()
        # Szerokość ścieżki i recepta czytają NOWY zbiór - ogon zlecenia, nie krok po `refresh()`:
        # w tle (AR-27) wracałby, zanim zbiór dojedzie.
        self.refresh(w_tle=True, potem=self._po_perspektywie)

    def _po_perspektywie(self):
        """Ogon `_on_perspective` po przyłożeniu zbioru perspektywy."""
        if self._szerokosc_sciezki is not None:
            self.table.setColumnWidth(self.model.base_col("path"), self._szerokosc_sciezki)
        # Perspektywa izolacji zapisu podaje gest, który ją opróżnia: gesty mieszkają w menu
        # prawego kliku (nie na pasku zbioru), a menu nie widać, dopóki się go nie otworzy.
        # Recepta PO `refresh()`, bo raport odświeżenia gasi receptę poprzedniego gestu.
        recepta = next((k for a, k in _RECEPTY_ZAPISU.items() if getattr(self, a)), None)
        if recepta is not None and self._frame_ids:
            # `Recepta` z jednym członem BEZ wykonawcy (kontrakt sygnału, Z7): gesty mieszkają
            # w menu prawego kliku, więc przycisk recepty stoi wygaszony, a zdanie zostaje.
            self.status_recipe.emit(_zlacz_recepty([i18n.t(
                recepta, finish=i18n.t("grid.inplace.finish"),
                restore=i18n.t("grid.inplace.restore"), release=i18n.t("grid.inplace.release"))]))
        # Ta sama figura dla „Plik nie zgadza się z obiektem" (AR-17 krok 3): gest mieszka w menu
        # prawego kliku, więc wejście w perspektywę mówi, gdzie go szukać.
        if getattr(self, _FLAGA_ZGODNOSCI_PLIKU) and self._frame_ids:
            self.status_recipe.emit(_zlacz_recepty([i18n.t(
                "grid.sel.object_change_recipe", align=i18n.t("grid.sel.object_change_align"))]))
        if getattr(self, _FLAGA_NOWSZYCH) and self._frame_ids:
            self._wejdz_w_nowsze()
        # „Rodowód do potwierdzenia” (AR-219): gest jednego obrazu mieszka w panelu „Rodowód”, a po
        # geście cel przechodzi na następny obraz (AR-196) - wejście stawia pierwszy, jak perspektywa
        # nowszych, bez recepty gestu zbiorczego (tu go nie ma).
        if getattr(self, _FLAGA_POTWIERDZENIA) and self._frame_ids:
            self._wejdz_w_kolejke_rodowodu()
        # „f/ niezgodna z teleskopem" (N19): kolumna FOCRATIO pliku dochodzi do pól widoku (dopisana,
        # nie podmieniona - wybór usera zostaje), a recepta mówi, co wpisze gest: f/ w pliku → f/
        # teleskopu z liczbą klatek, albo powód odmowy strażnika większości.
        if getattr(self, _FLAGA_OPTYKI) and self._frame_ids:
            if ("FOCRATIO" in (getattr(self, "_all_keywords", None) or [])
                    and "FOCRATIO" not in self._columns):
                self._columns = self._columns + ["FOCRATIO"]
                self._wypelnij_pola()
                self.refresh(w_tle=True)
            czlony = [i18n.t("grid.optics.recipe_line", telescope=tel or "-",
                             file=_fmt_f(plik), target=_fmt_f(cel), n=n)
                      for tel, plik, cel, n in queries.optics_fix_summary(self.con, self._frame_ids)]
            self.status_recipe.emit(_zlacz_recepty([i18n.t(
                "grid.optics.recipe", fix=i18n.t("grid.optics.fix_action"),
                lines="; ".join(czlony))]))

    def _wejdz_w_nowsze(self):
        """Wejście w perspektywę „Rodowód z klatkami nowszymi niż obraz" (AR-178): gest jednego
        obrazu mieszka w panelu „Rodowód", więc wejście stawia go od razu (`_wejdz_w_kolejke_rodowodu`)
        - a recepta mówi, gdzie leży gest na wszystkie naraz (menu prawego kliku, którego nie widać).
        Dawniej: wiersz Porządków → zaznacz obraz → „Rodowód" → przycisk, przy każdym z 9 stosów."""
        self._wejdz_w_kolejke_rodowodu()
        self.status_recipe.emit(_zlacz_recepty([i18n.t(
            "grid.lin.newer_recipe", reject=i18n.t("grid.lin.reject_newer"),
            panel=i18n.t("grid.sel.lineage"), all=i18n.t("grid.lin.reject_newer_all"))]))

    def _wejdz_w_kolejke_rodowodu(self):
        """Wejście w perspektywę kolejki rodowodu (`_perspektywa_kolejki_rodowodu`: nowsze niż obraz,
        AR-178, i do potwierdzenia, AR-219): pierwszy obraz tabeli w zaznaczeniu, panel „Rodowód”
        otwarty na nim - gest jednego obrazu stoi od razu.

        Niczego nie nadpisuje: obraz zaznacza się tylko w PUSTE zaznaczenie (cel gestu, który wrócił
        przy przyłożeniu, zostaje), a panel otwiera się tylko, gdy stos paneli jest pusty i żaden
        podgląd klingi nie stoi - otwarcie rodowodu zdejmuje cudzy podgląd (`_toggle_panel`)."""
        if not self._selected_data_rows():
            pierwszy = next((r["frame_id"] for r in self.model._rows if "_group" not in r), None)
            if pierwszy is not None:
                self._przywroc_zaznaczenie([pierwszy])
                self._date_timer.stop()
        if self._lineage_panel_open():
            self._refresh_lineage()
        elif self.panel_stack.isHidden() and not self.model._preview_active():
            self._toggle_panel("lineage")      # panel czyta zaznaczenie po pokazaniu

    def apply_object_facet(self, pairs):
        """Ustaw zbiór na WSKAZANE obiekty — publiczny seam dla wejść spoza widoku (T5e: „Pokaż
        klatki celu" z planera, D-0731-7). `pairs` = `[(object_id, canon), …]`; wiele par, bo jeden
        cel katalogu bywa w archiwum pod kilkoma nazwami (`IC410` ORAZ `LBN807`) i most ma pokazać
        SUMĘ klatek.

        Reużywa ISTNIEJĄCY facet Obiekt (liść `rel_object` + `facet_model.compose`) zamiast składać
        drzewo filtra po swojemu — druga ścieżka składania złamałaby SPOT i rozjechałaby się
        z cyklem facetów przy pierwszej zmianie. Perspektywa wraca do pełnej (zbiór definiuje
        wejście, nie poprzedni widok), advanced-filtr znika — jak przy każdej perspektywie.

        ETYKIETA IDZIE ZA ZBIOREM (bliźniak BP-5, potwierdzony testem): flagi i filtr były tu zerowane
        od początku, ale lista perspektyw zostawała, więc z „Duplikatów" most pokazywał klatki celu
        pod etykietą „Duplikaty". Rozstrzyga właściciel etykiety na końcu `_refresh`, jak po każdym
        przeładowaniu; facet mostu dopasowania nie blokuje, bo jest zawężeniem W RAMACH perspektywy
        (`_stan_zgodny_z`).

        ZAZNACZENIE MUSI BYĆ WIDOCZNE: listwa domyślnie odtwarza pozycję scrolla (słusznie dla kliku
        W listwie), więc wejście z zewnątrz zostawiało `✓` poza viewportem — zmierzone: pozycja 36
        z 48 przy scrollu 0. Stąd JEDNORAZOWY `_reveal_facet`, konsumowany przez najbliższe
        przeładowanie listwy."""
        self._zeruj_flagi()
        self._filter_tree = None
        self.filter_panel.set_tree(None)
        self.note_query = None      # wejście ZASTĘPUJE zbiór, więc tekst uwag też schodzi
        self._zdejmij_wskazane()
        self._terminy = []
        self._facet_state = {"object": {"in": [[oid, canon] for oid, canon in pairs]}} \
            if pairs else facet_model.empty_state()
        self._reveal_facet = ("object", pairs[0][0]) if pairs else None
        self.refresh(w_tle=True)

    def apply_find(self, *, facets, filter_tree, note_query, terms=()):
        """Zbiór z zapytania Znajdź - publiczny seam kontenera strony (`ZnajdzView`). Zapytanie
        ZASTĘPUJE cały zbiór: flagi perspektywy zerowane, facety, filtr zaawansowany i tekst uwag
        dokładnie z wyniku (`flows.znajdz.resolve`). Widok nie zna parsera ani jego typów - dostaje
        składniki własnego stanu, więc Znajdź nie ma drugiego silnika zbioru (JEDEN-STAN-EKRANU).
        `terms` = `(etykieta, klucze składników)` wpisanych terminów - jeden chip na termin.

        ZAPYTANIE STARTUJE OD „PRZEGLĄDU", nie od bieżącej perspektywy: pozycja listy, grupowanie
        i wygląd presetu bez zawężenia. Inaczej zapytanie po „Kalibracji" dziedziczyło jej
        grupowanie po rodzaju i nazwę - lighty zestawu szły pod „Kalibracja (zmieniona)" także do
        manifestu wydania. Etykietę rozstrzyga potem właściciel na końcu `_refresh` (FH-12): facety,
        zestaw i tekst uwag są zawężeniem W RAMACH „Przeglądu" (AR-95).
        Pierwszy obiekt zapytania jest odsłaniany w listwie jak przy moście teczki."""
        nieznane = [f for f in facets if f not in facet_model.FACETS]
        if nieznane:
            raise ValueError(f"nieznane facety zapytania: {nieznane!r}")
        self._zeruj_flagi()
        self._filter_tree = copy.deepcopy(filter_tree)
        self.filter_panel.set_tree(self._filter_tree)
        self._facet_state = copy.deepcopy(facets) or facet_model.empty_state()
        self.note_query = note_query or None
        self._zdejmij_wskazane()
        self._terminy = [(etykieta, tuple(klucze)) for etykieta, klucze in terms]
        self._stan_zapytania = (copy.deepcopy(self._facet_state), copy.deepcopy(self._filter_tree),
                                self.note_query)
        czysty = PRESETS[_PRESET_CZYSTY]
        self.combo_persp.blockSignals(True)
        self.combo_persp.setCurrentIndex(next(
            i for i in range(self.combo_persp.count())
            if self.combo_persp.itemData(i) == ("preset", _PRESET_CZYSTY)))
        self.combo_persp.blockSignals(False)
        grupa = self.combo_group.findData(czysty.get("group_by"))
        self.combo_group.blockSignals(True)
        self.combo_group.setCurrentIndex(grupa if grupa >= 0 else 0)
        self.combo_group.blockSignals(False)
        self._wyglad_z_perspektywy(czysty)
        self._zdejmij_wynik_gestu_zapisu()
        self._oznacz_zmiane_perspektywy()
        obiekty = (facets.get("object") or {}).get("in")
        self._reveal_facet = ("object", obiekty[0][0]) if obiekty else None
        self.refresh(w_tle=True)

    def zapytanie_aktualne(self):
        """Czy PRZYŁOŻONY zbiór jest wciąż dokładnie tym, który postawiło ostatnie zapytanie Znajdź.
        Fałsz po każdej zmianie spoza pola (chip, facet, perspektywa, „× Wyczyść zbiór") - pole
        zapytania przestaje wtedy opisywać stan i kontener je czyści."""
        return self._zapytanie_aktualne

    def set_presentation(self, prezentacja):
        """Prezentacja widoku: `PREZENTACJA_KLASYCZNA` (dzisiejszy ekran Zbiorów) albo
        `PREZENTACJA_ZNAJDZ` (prosty zestaw kolumn, pasek czasowników, bez paneli warsztatu).

        PRZEŁĄCZENIE NIE PRZEŁADOWUJE ZBIORU: zmienia się układ kolumn na tych samych wierszach
        (`GridTableModel.set_base_columns`) i widoczność kontrolek, a stan zbioru, staging, zajętość
        i mutex zostają, gdzie są (JEDEN-STAN-EKRANU). Zaznaczenie i bieżąca komórka (po znaczeniu
        kolumny) przeżywają przebudowę modelu jak każdy reset bez nowych danych
        (`_zaznaczenie_po_resecie`, AR-187) - to ono jest celem czasowników.

        Znajdź chowa filtr drzewiasty i „Pola" (ich składniki widać w chipach i na pasku kryteriów)
        oraz panel nazw plików - ten nie ma tu czasownika, więc otwarty zostałby bez kontrolki,
        która go zamyka. Makro i rodowód zostają, jak były: ich czasowniki są na pasku."""
        if prezentacja not in (PREZENTACJA_ZNAJDZ, PREZENTACJA_KLASYCZNA):
            raise ValueError(f"nieznana prezentacja: {prezentacja!r}")
        if prezentacja == self.prezentacja:
            return
        # OTWARTY EDYTOR KOMÓRKI DOMYKA SIĘ JAWNIE, ZANIM ruszy układ - z zapisem do szuflady, jak
        # klik poza komórkę. Domknięty dopiero w resecie `set_base_columns` odkładał podgląd
        # stagingu do następnego obrotu pętli (zmierzone testem: wpis w szufladzie, zaznaczenie
        # puste - zanim reset bez nowych danych zaczął nieść zaznaczenie). Tu podgląd pada od razu,
        # w tym samym obrocie co przełączenie.
        self._domknij_edycje("teraz")
        self.prezentacja = prezentacja
        znajdz = prezentacja == PREZENTACJA_ZNAJDZ
        self.filter_panel.setVisible(not znajdz)
        self.fields.setVisible(not znajdz)
        if znajdz and self._rename_panel_open():
            self.panel_stack.setVisible(False)
            self.sel_bar.set_active_panel(None)
        self.sel_bar.set_presentation(prezentacja)
        self.model.set_base_columns(FIND_COLS if znajdz else BASE_COLS,
                                    version_col=self._kolumna_wersji())
        self._uloz_kolumny()
        if znajdz:
            self._szerokosci_znajdz()
        if self.model._version_col() is not None:
            self.table.resizeColumnToContents(self.model._version_col())
        self.stan_zbioru_zmieniony.emit()

    def _szerokosci_znajdz(self):
        """Szerokości prostego zestawu kolumn przy wejściu w Znajdź: krótkie fakty (obiekt, noc,
        filtr, czas, zestaw) z treści, uwaga stałą szerokością (tooltip niesie pełną). Liczone przy
        wejściu, nie przy każdym przeładowaniu - potem szerokość ręki idzie za znaczeniem kolumny
        (`_zapamietaj_szerokosci`)."""
        for klucz in ("_object", "night", "filter_canon", "exptime", "_zestaw"):
            self.table.resizeColumnToContents(self.model.base_col(klucz))
        self.table.setColumnWidth(self.model.base_col("note"), _SZEROKOSC_UWAG)

    def skladniki_stanu(self, *, tylko_bez_kontrolki=False):
        """Składniki zawężenia zbioru jako `(klucz, etykieta)` - rząd chipów Znajdź. Każdy składnik,
        który zawęża wynik, ma tu wpis (ekran nie kłamie): flagi perspektywy, wartości facetów
        (włączone i wykluczone), filtr zaawansowany i tekst uwag. Etykiety facetów i filtra mówi
        `filter_engine.describe` - ta sama gramatyka co pasek kryteriów, więc chip i pasek nie
        nazwą jednego warunku dwoma zdaniami.

        `tylko_bez_kontrolki` - składniki, których prezentacja klasyczna nie pokazuje żadną własną
        kontrolką (dziś: tekst uwag); tam chipy stoją wyłącznie po to, żeby zbiór nie był zawężony
        niewidocznie. Klucz to krotka do `zdejmij_skladnik`.

        CHIPY MÓWIĄ O ZBIORZE, KTÓRY WIDAĆ: lista pochodzi z migawki OSTATNIO PRZYŁOŻONEGO zbioru
        (`_zastosuj_zbior`), nie ze stanu intencji. W trakcie składu w tle stan widoku jest już nowym
        zapytaniem, a tabela pokazuje jeszcze klatki poprzedniego - chip czytany ze stanu nazywałby
        kryteria wyników, których na ekranie nie ma."""
        if tylko_bez_kontrolki:
            # Klatki wskazane z panelu też nie mają kontrolki w klasycznej prezentacji - chip jest
            # ich JEDYNYM śladem na ekranie i jedyną drogą wyjścia.
            return [s for s in self._skladniki_przylozone
                    if all(k[0] in ("uwagi", "wskazane") for k in self._klucze_chipu(s[0]))]
        return list(self._skladniki_przylozone)

    @staticmethod
    def _klucze_chipu(klucz):
        """Składniki stanu za kluczem chipu: chip terminu niesie ich kilka, chip pojedynczy - jeden."""
        return list(klucz[1]) if klucz[0] == "termin" else [klucz]

    def _skladniki_z_migawki(self, migawka):
        """Chipy z migawki składu (`_migawka_zbioru`): najpierw JEDEN chip na wpisany termin
        zapytania (`("termin", klucze)` - z tych jego składników, które w stanie wciąż stoją), potem
        każdy składnik spoza terminów osobno. Bez tego „noc:2025" dawało chip na każdą noc - rząd
        szerszy niż ekran i zdjęcie miesiąca w kilkunastu kliknięciach."""
        pojedyncze = self._pojedyncze_z_migawki(migawka)
        klucze = {k for k, _ in pojedyncze}
        out, zuzyte = [], set()
        for etykieta, klucze_terminu in migawka.get("terminy") or ():
            stoja = tuple(k for k in klucze_terminu if k in klucze and k not in zuzyte)
            if stoja:
                out.append((("termin", stoja), etykieta))
                zuzyte.update(stoja)
        return out + [(k, e) for k, e in pojedyncze if k not in zuzyte]

    def _pojedyncze_z_migawki(self, migawka):
        """`(klucz, etykieta)` każdego składnika zawężenia z migawki - kolejność: tekst uwag, flagi
        perspektywy, facety, filtr zaawansowany."""
        out = []
        if migawka.get("wskazane") is not None:
            out.append((("wskazane",), migawka["wskazane_etykieta"]))
        if migawka.get("uwagi") is not None:
            out.append((("uwagi",), i18n.t("find.chip.notes", text=migawka["uwagi"])))
        trimy = set(migawka.get("trimy") or ())
        for atrybut, nazwa in _TRIMY:
            if nazwa in trimy:
                out.append((("trim", atrybut), i18n.t(_klucz_kryterium(atrybut))))
        facety = migawka.get("facety") or {}
        for facet in facet_model.FACETS:
            grupa = facety.get(facet) or {}
            for v, label in grupa.get("in") or []:
                out.append((("facet", facet, "in", v), filter_engine.describe(
                    {"facet": facet, "value": v, "label": label})))
            for v, label in grupa.get("ex") or []:
                out.append((("facet", facet, "ex", v), filter_engine.describe(
                    {"op": "NOT", "conditions": [{"facet": facet, "value": v, "label": label}]})))
        if migawka.get("filtr") is not None:
            out.append((("filtr",), filter_engine.describe(migawka["filtr"])))
        return out

    def zdejmij_skladnik(self, klucz):
        """„×" chipu: zdejmij JEDEN składnik zawężenia i przeładuj zbiór. Facet traci jedną wartość
        (reszta wyboru zostaje), flaga perspektywy znika sama - etykietę listy rozstrzyga potem
        właściciel na końcu `_refresh`, jak po każdym przeładowaniu. Klucz spoza
        `skladniki_stanu` to błąd wołającego (EXPECT). Chip terminu zdejmuje wszystkie swoje
        składniki jednym przeładowaniem."""
        for skladnik in self._klucze_chipu(klucz):
            self._zdejmij_jeden(skladnik)
        self.refresh(w_tle=True)

    def _zdejmij_jeden(self, klucz):
        rodzaj = klucz[0]
        if rodzaj == "uwagi":
            self.note_query = None
        elif rodzaj == "wskazane":
            self._wroc_ze_wskazanych()
        elif rodzaj == "filtr":
            self._filter_tree = None
            self.filter_panel.set_tree(None)
        elif rodzaj == "trim" and klucz[1] in {a for a, _ in _TRIMY}:
            setattr(self, klucz[1], False)
        elif rodzaj == "facet":
            _, facet, strona, wartosc = klucz
            stan = copy.deepcopy(self._facet_state)
            grupa = stan.get(facet) or {}
            grupa[strona] = [e for e in grupa.get(strona) or [] if e[0] != wartosc]
            for k in ("in", "ex"):
                if not grupa.get(k):
                    grupa.pop(k, None)
            if grupa:
                stan[facet] = grupa
            else:
                stan.pop(facet, None)
            self._facet_state = stan
        else:
            raise ValueError(f"nieznany składnik stanu: {klucz!r}")

    def apply_perspective(self, name):
        """Ustaw perspektywę PO NAZWIE — publiczny seam dla wejść spoza widoku (F5: klik w zadanie
        „Duplikaty" w Porządkach; R#14 — duplikatów NIE wyraża drzewo filtra, jedyna droga to
        mechanizm perspektyw). Presety iterowane pierwsze w combo, więc kolizja nazwy z zapisaną
        rozstrzyga się na preset. Pozycja już bieżąca → `_on_perspective()` wprost (klik w zadanie =
        ZAWSZE czysta perspektywa, nie no-op nad facetami usera). Nieznana nazwa → status."""
        for i in range(self.combo_persp.count()):
            data = self.combo_persp.itemData(i)
            if data and data[1] == name:
                if i == self.combo_persp.currentIndex():
                    self._on_perspective()
                else:
                    self.combo_persp.setCurrentIndex(i)   # currentIndexChanged → _on_perspective
                return
        self.status_message.emit(i18n.t("grid.persp.unknown", name=name))

    def _load_saved(self, name):
        return dict(self._saved_perspectives()).get(name)

    def _spec_pozycji(self, data):
        """Definicja pozycji listy perspektyw - `data` = `(rodzaj, nazwa)` z `itemData`. Preset czyta
        się z kodu, zapisana z BAZY; `None` = pozycja, której nie umiemy zastosować (stary `sql_text`).
        Jedno miejsce, bo pytają o to dwaj: przełączenie perspektywy i właściciel jej etykiety."""
        kind, name = data
        return PRESETS.get(name) if kind == "preset" else self._load_saved(name)

    def _stan_zgodny_z(self, spec):
        """Czy ZBIÓR widoku jest tym, który definiuje perspektywa `spec` (BP-5).

        Definicję zbioru niosą trzy rzeczy: flagi `only_*`, filtr zaawansowany i facety. Grupowanie
        i kolumny zmieniają WYGLĄD zbioru, nie jego skład, więc nie są porównywane.

        Flagi i filtr zgadzają się DOKŁADNIE (wyjątek: filtr z samych liści facetowych nad definicją
        bez filtra - warunek zestawu Znajdź, `_zawezenie_facetowe`). Facety perspektywy muszą
        w stanie STAĆ, ale stan może mieć ich więcej: facet dołożony ponad definicję (klik w listwie, most planera) jest zawężeniem
        W RAMACH perspektywy, nie jej zmianą. Ta jedna reguła rozstrzyga obu wołających bez rozróżniania
        ich: preset (bez facetów) pasuje do stanu z facetem mostu, a zapisana perspektywa z facetem
        przestaje pasować, gdy „× Wyczyść zbiór" ten facet zdjął.

        Flagi biorą skład z `_TRIMY` (BP-4), a spec niesie je bez podkreślnika (`only_dups` ↔
        `_only_dups`) - konwencja pinowana bramką `test_KAZDY_preset_ma_etykiete_i_zuzyta_flage`.

        TEKST UWAG JEST ZAWĘŻENIEM, jak facet i zestaw (AR-95): każdy składnik zapytania Znajdź zawęża
        „Przegląd" bez sufiksu „(zmieniona)". Dawniej uwagi liczyły się jako zmiana stanu (FH-12), więc
        dwa zapytania Znajdź dostawały różne etykiety („Przegląd" przy facecie, „Przegląd (zmieniona)"
        przy uwagach), a ta szła do manifestu wydania.

        ZAWĘŻENIE UWAGAMI WYŁĄCZNIE NAD WBUDOWANYM „PRZEGLĄDEM" (`_PRESET_CZYSTY`, preset, od którego
        startuje Znajdź - `apply_find`). Dla każdej innej definicji tekst uwag jest ZMIANĄ: zapis
        bieżącego widoku jako perspektywy (`_save_perspective`) uwag nie serializuje, więc zapisana
        nazwa bez sufiksu udawałaby zbiór z uwagami - ponowne otwarcie pokazałoby szerszy zbiór,
        a manifest wydania przypisałby tę nazwę zbiorowi zawężonemu. Porównanie po TOŻSAMOŚCI
        presetu (`_spec_pozycji` oddaje obiekt z `PRESETS`), nie po treści: zapisana perspektywa
        z pustą definicją ma tę samą treść, a uwag nie niesie tak samo."""
        flagi_spec = {atrybut for atrybut, _ in _TRIMY if spec.get(_klucz_spec(atrybut))}
        flagi_stanu = {atrybut for atrybut, _ in _TRIMY if getattr(self, atrybut)}
        # Filtr złożony WYŁĄCZNIE z liści facetowych (warunek zestawu z Znajdź: teleskop + kamera)
        # jest zawężeniem jak klik w listwie - nad definicją bez filtra nie zmienia perspektywy.
        filtr_zgodny = (spec.get("filter") == self._filter_tree
                        or (spec.get("filter") is None and _zawezenie_facetowe(self._filter_tree)))
        uwagi_zmieniaja = self.note_query is not None and spec is not PRESETS[_PRESET_CZYSTY]
        # KLATKI WSKAZANE Z PANELU: żadna perspektywa ich nie niesie, a 190 wejść jednego stosu nie
        # jest „Przeglądem" - to nie zawężenie zapytania, tylko inny zbiór.
        if (flagi_spec != flagi_stanu or not filtr_zgodny or uwagi_zmieniaja
                or self._wskazane is not None):
            return False
        return all(self._facet_state.get(facet) == wybor
                   for facet, wybor in (spec.get("facets") or {}).items())

    def _etykieta_perspektywy_za_stanem(self):
        """JEDEN WŁAŚCICIEL ETYKIETY STANU (BP-5): gdy zbiór przestał być tym, który definiuje bieżąca
        pozycja listy perspektyw, lista przeskakuje na PRESET, którego definicja się ze stanem zgadza.

        WOŁAJĄCY JEST JEDEN: `_refresh`, na końcu KAŻDEGO przeładowania - etykieta jest pochodną
        stanu (BP-5 domknięty w `_refresh`). Trzy jawne wywołania przy gestach („× Wyczyść zbiór",
        zmiana filtra z panelu, most planera) przegapiły czwartą drogę: klik w listwie facetów
        zostawiał „★ Lighty" nad dopełnieniem jej definicji. Gesty zdejmujące część definicji bez
        przełączania perspektywy flag nie tykają, więc z trimem trafiamy w preset Z TĄ FLAGĄ
        („Duplikaty" zostają „Duplikatami"), a bez trimu w `_PRESET_CZYSTY`. Dosłowne „zawsze
        Przegląd" kłamałoby od drugiej strony: duplikaty pod etykietą perspektywy bez zawężenia.

        Przeładowanie po `_on_perspective` kończy się wczesnym powrotem - stan jest wtedy z definicji
        tej pozycji. `_save_perspective` nie przeładowuje (stan == właśnie zapisany, pozycję wybiera
        sam). Pozycja „★ X ⚠" (spec `None`) nie ma definicji do porównania, więc najbliższe
        przeładowanie oddaje etykietę presetowi zgodnemu ze stanem.

        BEZ SYGNAŁU: stan jest już właściwy, a `_on_perspective` przepisałby grupowanie z presetu
        (i kolumny, gdy spec je niesie) i przeładował zbiór drugi raz. Kandydatami są wyłącznie
        presety - nazwa zapisana przez człowieka nie jest nasza do zgadywania. Brak dopasowania
        (dwie flagi naraz, możliwe tylko w specyfikacji spoza GUI - `_save_perspective` bierze flagi
        ze stanu, a preset niesie najwyżej jedną) zostawia nazwę pozycji, ale nie jako twierdzenie:
        dostaje sufiks „(zmieniona)" (FH-12, decyzja „q9.o1") - „Kalibracja" z filtrem zmienionym
        na `OBJECT = NGC7000` przestaje udawać kalibrację, a nazwa zostaje, bo mówi, OD CZEGO
        zbiór się zaczął. Ta sama etykieta idzie do manifestu wydania (`_open_projection`)."""
        data = self.combo_persp.currentData()
        if data:
            spec = self._spec_pozycji(data)
            if spec is not None and self._stan_zgodny_z(spec):
                self._oznacz_zmiane_perspektywy()
                return
        for i in range(self.combo_persp.count()):
            kandydat = self.combo_persp.itemData(i)
            if kandydat and kandydat[0] == "preset" and self._stan_zgodny_z(PRESETS[kandydat[1]]):
                self.combo_persp.blockSignals(True)
                self.combo_persp.setCurrentIndex(i)
                self.combo_persp.blockSignals(False)
                self._oznacz_zmiane_perspektywy()
                # Wygląd zapisanej perspektywy (AR-36) nie jedzie pod etykietę presetu: preset nie
                # niesie `view`, więc wraca wygląd domyślny i układ kolumn liczy się od nowa.
                if self._wyglad_z_perspektywy(PRESETS[kandydat[1]]):
                    self._uloz_kolumny()
                return
        self._oznacz_zmiane_perspektywy()

    def _oznacz_zmiane_perspektywy(self):
        """Tekst pozycji listy perspektyw ze STANU (FH-12): bieżąca pozycja, której definicja nie
        zgadza się ze zbiorem, mówi „<Nazwa> (zmieniona)"; każda inna wraca do etykiety bazowej
        (`_ROLA_ETYKIETY`), więc sufiks nie zostaje na pozycji, z której widok już zszedł. Pozycja
        „★ X ⚠" (spec `None`) nie ma definicji, więc po przeładowaniu, które nie trafiło w preset,
        też dostaje sufiks - do najbliższego przeładowania mówi tylko swoją nazwę.

        Sam tekst, bez sygnału i bez zmiany pozycji: wybór pozycji rozstrzyga
        `_etykieta_perspektywy_za_stanem`, a `setItemText` nie emituje `currentIndexChanged`."""
        biezaca = self.combo_persp.currentIndex()
        data = self.combo_persp.currentData()
        zmieniona = False
        if data:
            spec = self._spec_pozycji(data)
            zmieniona = spec is None or not self._stan_zgodny_z(spec)
        for i in range(self.combo_persp.count()):
            tekst = self.combo_persp.itemData(i, _ROLA_ETYKIETY)
            if tekst is None:
                continue
            if i == biezaca and zmieniona:
                tekst = i18n.t("grid.persp.changed", name=tekst)
            if self.combo_persp.itemText(i) != tekst:
                self.combo_persp.setItemText(i, tekst)

    def _wyglad_z_perspektywy(self, spec):
        """Wygląd widoku z klucza `view` spec-a (AR-36) - JEDYNE miejsce, które go czyta. Zeruje
        stan z poprzedniej perspektywy (spec bez `view`, preset) i zwraca, czy coś się zmieniło.

        Wybór „Obrazów" z perspektywy mieszka OSOBNO od wyboru ręki (`_obrazy_reka`): perspektywa
        nie przepisuje gestu sesji, a po wyjściu z niej jej wybór znika. Pierwszeństwo czyta
        `_obrazy_widoczne`. Szerokość ścieżki: dodatnia liczba całkowita albo żadna. Wartość spoza
        kontraktu (ręczna edycja bazy) = brak wartości, bez wyjątku."""
        widok = spec.get(_SPEC_WIDOK)
        widok = widok if isinstance(widok, dict) else {}
        obrazy = widok.get(_SPEC_OBRAZY)
        obrazy = obrazy if isinstance(obrazy, bool) else None
        szer = widok.get(_SPEC_SZEROKOSC_SCIEZKI)
        szer = szer if isinstance(szer, int) and not isinstance(szer, bool) and szer > 0 else None
        zmiana = (obrazy, szer) != (self._obrazy_perspektywy, self._szerokosc_sciezki)
        self._obrazy_perspektywy, self._szerokosc_sciezki = obrazy, szer
        return zmiana

    def _warunki_nowszej_wersji_do_przeniesienia(self, name):
        """Klucze spec-a, których ten build nie zna, a które zapis pod nazwą `name` ma PRZENIEŚĆ
        (D-V-9f, druga połowa) - do scalenia z nowym spec-iem, zwykle puste.

        Spec składany jest ze STANU widoku, a stan zna tylko to, co ten build umie. Bez tego członu
        ponowny zapis perspektywy przyjechanej z nowszej wersji kasował po cichu jej warunek:
        pierwsza połowa D-V-9f ostrzegała na pasku, a zapis i tak go gubił - i to w bazie, czyli
        także dla nowszego wydania, które ten warunek umiało zastosować.

        REGUŁA: przenosimy wtedy i tylko wtedy, gdy zapis NADPISUJE TĘ PERSPEKTYWĘ, KTÓRĄ WIDOK
        POKAZUJE - pozycja listy to `("saved", name)`, a zbiór widoku jest wciąż jej zbiorem
        (`_stan_zgodny_z`, ta sama reguła, którą właściciel etykiety decyduje, czy widok jest jeszcze
        tą perspektywą). Tylko wtedy wiemy, że człowiek zapisuje „to samo, może z poprawką", a nie
        coś innego pod starą nazwą. Zapis pod NOWĄ nazwą niesie wyłącznie to, co widok zna: ten
        build nie umie zastosować obcego warunku, więc nowa perspektywa odziedziczyłaby zawężenie,
        którego nikt tu nie widział ani nie wybrał. Tak samo nadpisanie INNEJ nazwy albo zapis
        z widoku, który przestał być tą perspektywą (np. po „× Wyczyść zbiór") - człowiek zastępuje
        wtedy zbiór świadomie, a doklejenie cudzego warunku zrobiłoby z niego trzeci, niczyj.

        Zwraca PARĘ `(klucze, facety)`, bo warunki nowszej wersji mieszkają w dwóch miejscach
        spec-a, a mechanizm ich cichego pominięcia jest ten sam (`_nieznane_warunki`):
          * klucze NAJWYŻSZEGO poziomu spoza `_ZNANE_KLUCZE_SPECU` - wszystkie, także puste
            (to zapis nowszego wydania, nie nasz do przycinania);
          * facety spoza `facet_model.FACETS`. Te leżą już w `self._facet_state`, bo
            `_on_perspective` przepisuje facety spec-a w całości - i właśnie dlatego wołający
            ODFILTROWUJE je ze stanu, a wraca je wyłącznie ta funkcja. Bez tego zapis pod nową
            nazwą przemycałby obcy facet ze stanu, łamiąc regułę wyżej.
        Format spec-a się nie zmienia: obie połowy wracają pod swoje dotychczasowe miejsca."""
        if self.combo_persp.currentData() != ("saved", name):
            return {}, {}
        spec = self._load_saved(name)
        if spec is None or not self._stan_zgodny_z(spec):
            return {}, {}
        facety = spec.get("facets") if isinstance(spec.get("facets"), dict) else {}
        return ({k: v for k, v in spec.items() if k not in _ZNANE_KLUCZE_SPECU},
                {f: g for f, g in facety.items() if f not in facet_model.FACETS})

    def _wyglad_do_zapisu(self):
        """Klucz `view` nowego spec-a (AR-36): widoczność „Obrazów", jaką widok POKAZUJE (nie sam
        gest ręki - perspektywa ma się otworzyć tak, jak ją zapisano), i szerokość ścieżki tylko
        wtedy, gdy różni się od tej, którą widok ustawiłby sam: z treści w perspektywach
        `_FLAGI_SCIEZKI_Z_TRESCI`, domyślnej sekcji gdzie indziej. Szerokość „taka jak zwykle"
        zapisana w spec-u zamroziłaby treść z chwili zapisu."""
        widok = {_SPEC_OBRAZY: self._obrazy_widoczne()}
        kol = self.model.base_col("path")
        biezaca = self.table.columnWidth(kol)
        if any(getattr(self, atrybut) for atrybut in _FLAGI_SCIEZKI_Z_TRESCI):
            sama = szerokosc_z_tresci(self.table, kol)
        else:
            sama = self.table.horizontalHeader().defaultSectionSize()
        if biezaca != sama:
            widok[_SPEC_SZEROKOSC_SCIEZKI] = biezaca
        return widok

    def _save_perspective(self):
        name, ok = QInputDialog.getText(self, i18n.t("grid.persp.save_title"), i18n.t("grid.persp.save_prompt"))
        if not ok or not name.strip():
            return
        name = name.strip()
        self._podbij_zeton()                # zdanie zapisu - nie ogona starszego gestu (AR-84)
        klucze_obce, facety_obce = self._warunki_nowszej_wersji_do_przeniesienia(name)
        spec = {
            "filter": self._filter_tree, "columns": self._columns,
            "group_by": self.combo_group.currentData(),
            # KAŻDA flaga, także fałszywa: jawne `False` mówi starszemu wydaniu „tu nic nie ma",
            # więc `_nieznane_warunki` po tamtej stronie go nie liczy (pusta wartość to nie warunek).
            **{_klucz_spec(atrybut): getattr(self, atrybut) for atrybut, _ in _TRIMY},
            # OSOBNO od "filter" (nota R2) - set_tree nigdy ich nie widzi. Ze stanu bierzemy tylko
            # facety, które ten build zna; obce wracają wyłącznie regułą przeniesienia (D-V-9f).
            "facets": {**{f: g for f, g in self._facet_state.items() if f in facet_model.FACETS},
                       **facety_obce},
            # Wygląd (AR-36): widoczność „Obrazów" EFEKTYWNA w chwili zapisu i szerokość ścieżki -
            # ta tylko wtedy, gdy ręka ją zmieniła (`_wyglad_do_zapisu`).
            _SPEC_WIDOK: self._wyglad_do_zapisu(),
            **klucze_obce,
        }
        # Zapis idzie do BAZY (I-1) — perspektywa jedzie z archiwum, nie z tą maszyną. Czasownik
        # z klingi rozstrzyga KOMUNIKAT: nazwa przyjechana z drugiej maszyny z inną treścią zostaje
        # NADPISANA, a „zapisano" bez słowa o tym mówiłoby o czymś, co się nie stało (F9).
        _id, verb = repo.save_perspective(self.con, name=name, spec=spec, now=self._now())
        # Widok JEST teraz tą perspektywą - jej wygląd obowiązuje od razu, inaczej najbliższe
        # przeładowanie policzyłoby ścieżkę z treści i zjadło szerokość, którą człowiek zapisał.
        # Gest ręki na „Obrazach" ZOSTAJE SKONSUMOWANY przez zapis: należy od teraz do tej
        # perspektywy (wybór efektywny trafił do `view`), a nie do sesji - inaczej przechodził na
        # preset i chował kolumnę tam, gdzie jej domyślna jest inna (firsthand: zapis z ukrytymi
        # „Obrazami" w Duplikatach → preset „Duplikaty" dalej bez kolumny).
        self._wyglad_z_perspektywy(spec)
        self._obrazy_reka = None
        # Sama lista perspektyw: zapis nie rusza kart, a pełne `_load_facets` liczyło tu dawniej
        # pokrycie całego archiwum i przy okazji zerowało kolumny do domyślnych - zaraz po tym,
        # jak człowiek zapisał je w perspektywie.
        self._odbuduj_perspektywy()
        # F4R2#6 (pre-existing, ścieżka tykana przez F4): rebuild combo pod blockSignals zostawiał
        # indeks 0 („Przegląd") przy żywym stanie świeżo zapisanej perspektywy — etykieta kłamała.
        # Re-select zapisanej, nadal bez emisji (_on_perspective nie ma czego przeładowywać:
        # stan == właśnie zapisany).
        self.combo_persp.blockSignals(True)
        for i in range(self.combo_persp.count()):
            if self.combo_persp.itemData(i) == ("saved", name):
                self.combo_persp.setCurrentIndex(i)
                break
        self.combo_persp.blockSignals(False)
        # Sufiks idzie za pozycją: poprzednia traci „(zmieniona)", a zapisana dostaje go wyłącznie
        # wtedy, gdy stan ma składnik, którego perspektywa nie niesie (tekst uwag, FH-12).
        self._oznacz_zmiane_perspektywy()
        self.status_message.emit(i18n.t(
            "grid.persp.overwritten" if verb == "perspective.overwritten" else "grid.persp.saved",
            name=name))

    def _open_projection(self):
        """Otwórz dialog projekcji dla WIDOCZNEJ perspektywy (`self._frame_ids` — po filtrach dups/review,
        to co user widzi; doktryna §5). Modal TYLKO na potwierdzenie eksportu; cała mutacja plików w
        Qt-wolnej klindze `projection` przez dialog. Pusty grid → szczery status, bez pustego dialogu.
        Zbiór w drodze → odmowa: manifest dostałby nazwę NOWEJ perspektywy przy klatkach starej."""
        if self._odmowa_w_drodze():
            return
        if not self._frame_ids:
            self.status_message.emit(i18n.t("grid.proj.no_frames"))
            return
        dlg = ProjectionDialog(self.con, self._frame_ids, now_fn=self._now,
                               perspektywa=self.combo_persp.currentText(), parent=self)
        dlg.exec()
        # Wydanie zostawia ślad W APLIKACJI (wiz P-C #4): przed tym jedynym zapisem był
        # `_PROJEKCJA.json` w celu, więc po zamknięciu dialogu okno nie wiedziało nic o tym,
        # co przed chwilą wyjechało na stół. Zdanie składa dialog (tam liczby są świeże).
        if dlg.summary:
            self.status_message.emit(dlg.summary)

    def _open_object_release(self):
        """„Wydaj obiekt…": okno teczek → `ProjectionDialog` w trybie obiektu → zdanie na statusbar.
        Droga: klik w pasku, dwuklik teczki, „Utwórz N linków" - trzy interakcje przy celu
        z pamięci. Zbiór gridu nie jest tu celem, tylko PODPOWIEDZIĄ: gdy niesie lighty dokładnie
        jednego obiektu, jego teczka jest zaznaczona na starcie.

        ZBIÓR W DRODZE NIE ODMAWIA, TYLKO GASI PODPOWIEDŹ: podpowiedź liczona ze zbioru, który zaraz
        zostanie zastąpiony, wskazałaby teczkę poprzedniego widoku, więc okno otwiera się bez
        preselekcji. Odmowa (jak przy „Wydaj na stół…", gdzie zbiór JEST celem) blokowała kafel
        Domu przez ~1 s po każdym przeładowaniu zdaniem o tabeli, której na Domu nie widać."""
        jedyny = (None if self._zbior_w_drodze()
                  else queries.sole_light_object(self.con, self._frame_ids))
        pick = ObjectPickDialog(self.con, preselect=jedyny, parent=self)
        if pick.exec() != QDialog.Accepted or pick.object_id is None:
            return
        dlg = ProjectionDialog(self.con, object_id=pick.object_id, now_fn=self._now, parent=self)
        dlg.exec()
        if dlg.summary:
            self.status_message.emit(dlg.summary)

    # ---- oś OBIEKTU na zaznaczeniu (S2b, D-OW-6) ----

    def _object_gesture_ids(self):
        """Cel OBU gestów: WYŁĄCZNIE zaznaczenie (§4/14c-a). Fallback „to, co widoczne" jest dla
        zapisu osi ZAKAZANY — przy 800 widocznych klatkach chybione kliknięcie i zamierzony gest
        wyglądają identycznie. Pusty ⇒ status i zero zapisu; to druga linia obrony za wygaszeniem,
        bo bramka woła SLOT, nie przycisk (klik w wyszarzony przycisk przeszedłby trywialnie)."""
        ids = [r["frame_id"] for r in self._selected_data_rows()]
        if not ids:
            self.status_message.emit(i18n.t("grid.sel.object_empty"))
        return ids

    def _po_gescie_osi(self, klucz, gest, *, odwrot=None,
                       canons_key="grid.sel.object_canons",
                       nothing_key="grid.sel.object_skip_nothing", **kw):
        """Wspólny ogon WSZYSTKICH gestów osi: zdanie z ROZBICIEM per fakt + odświeżenie CZTERECH
        powierzchni + ZACHOWANIE ZAZNACZENIA.

        Liczniki idą osobno, bo znaczą co innego: „kalibracja" to ochrona, która zadziałała,
        a „zmieniły się w międzyczasie" to ostrzeżenie, że stan uciekł. Jedno „pominięto N" kazałoby
        człowiekowi zgadywać, którą z tych dwóch rzeczy właśnie zobaczył.

        ZAZNACZENIE PRZEŻYWA GEST (R-S2b-3, człon pierwszy). `refresh()` przebudowuje model
        (`beginResetModel`), więc zaznaczenie 120 klatek szło do zera — a razem z nim JEDYNY tani
        cel gestu naprawczego. Zmierzone przez wizytację: odtworzenie stanu sprzed pomyłki
        kosztowało 6-8 interakcji plus pamięć człowieka o tym, co tam stało.

        `odwrot` (`_Odwrot` albo `None`) deklaruje, że gest ma drogę powrotu - recepta paska podaje
        ją wtedy jako wykonalny człon (FH-2e). Klucze i etykiety niesie deklaracja, a kod składający
        jest jeden dla wszystkich trzech odwracalnych gestów obu osi zaznaczenia."""
        zaznaczone = [r["frame_id"] for r in self._selected_data_rows()]
        # Recepta poprzedniego gestu przestaje obowiązywać w chwili nowego - `refresh()` niżej
        # nie ma jej już składać (FH-2e: składa ją ze stanu, którego za moment nie będzie).
        self._zacznij_gest()
        # Odmiana po WSZYSTKICH klatkach gestu (dopełniacz po „z”: „z 1 klatki”, „z 5 klatek”).
        msg = i18n.t_plural(klucz, gest.assigned + gest.skipped, assigned=gest.assigned, **kw)
        # Rozbicie pominięć i gotowe obrazy składa JEDEN dom (`zdanie_pominiec`), wspólny z dwiema
        # powierzchniami osi w `gui.app` - `nothing_key` idzie za gestem (FC-6), jak `canons_key`.
        msg += zdanie_pominiec(gest, nothing_key=nothing_key)
        # KANONY OSOBNYM CZŁONEM, nie placeholderem w zdaniu bazowym (R-S2b-3, człon drugi).
        # Zdanie bazowe ma dwóch wołających o RÓŻNYCH kwargach, więc `{canons}` w nim byłoby
        # `KeyError`-em u tego, który go nie poda — a bramka i18n pyta o komplet PL/EN i istnienie
        # klucza, nie o parytet placeholderów z wołającym. Osobny człon milczy przy zerze;
        # placeholder zostawiłby wiszący dwukropek nad pustką. Nadanie go nie dokłada: tam kanon
        # jest w zdaniu bazowym, bo user sam go przed chwilą wybrał.
        if gest.canons and "canon" not in kw:
            msg += i18n.t(canons_key, canons=_lista_kanonow(gest.canons))
        # RECEPTA ODWRACALNOŚCI SKŁADA SIĘ ZE STANU, NIE U WOŁAJĄCEGO (bramka pakietu, zarzut
        # blokujący) - bo jej treść zależy od tego, czy cel został na ekranie. Gest, który niczego
        # nie zapisał, recepty nie dostaje: mówiłaby, jak cofnąć coś, co się nie stało - a pusta
        # gasi receptę poprzedniego gestu.
        # CEL RECEPTY TO KLATKI REALNIE ZMIENIONE (`gest.frame_ids`), nie całe zaznaczenie: klinga
        # pomija część celu (nagrobek sprzed tygodnia, źródło z nagłówka), a odwrót na pominiętych
        # ruszyłby cudzą, starszą decyzję, której ten gest nie podjął (bramka pakietu, Z1).
        if gest.assigned:
            # CZTERY POWIERZCHNIE: wiersze gridu, facety (Obiekt zmienił zawartość), licznik/pasek
            # oraz kolejka przeglądu w oknie osi - ta ostatnia przez sygnał, bo nie jest nasza.
            # Zbiór składa się w tle, a zaznaczenie, człon „poza widokiem", zdanie i receptę
            # odkłada ogon po przyłożeniu (`_ogon_gestu`, AR-84). Sygnały PRZED zleceniem składu
            # (patrz `_ogon_gestu`).
            self.object_axis_changed.emit()
            self.stan_porzadkow_changed.emit()     # plakietka Porządków (patrz definicja sygnału)
            self._przeladuj_po_gescie(msg, zaznaczone, recepta=gest.frame_ids, odwrot=odwrot,
                                      ts=queries.last_hand_ts(self.con), kanony=gest.canons)
            return
        self.status_message.emit(msg)
        self._ustaw_recepte_gestu(gest.frame_ids, odwrot, kanony=gest.canons)

    def _zacznij_gest(self):
        """Nowy gest z receptą: recepta poprzedniego przestaje obowiązywać i schodzi z paska i Domu
        OD RAZU - ogon tego gestu poda nową dopiero po przyłożeniu zbioru, a do tego czasu Dom
        pokazywałby wykonaną receptę jako czynną. Żeton w górę (`_podbij_zeton`)."""
        self._podbij_zeton()
        self._recepta_gestu = None
        self._emituj_recepte_gestu()

    def _podbij_zeton(self):
        """ŻETON GESTU (AR-84): ogon gestu niesie numer z chwili zlecenia, a gest, który padł po nim,
        numer podbija - ogon starszego gestu nie nadpisze wtedy zdania, recepty ani zaznaczenia
        nowszego. Podbijają gesty stawiające albo zdejmujące receptę (`_zacznij_gest`,
        `_ustaw_recepte_gestu`) i gesty mówiące własnym zdaniem, które ruszają, gdy zbiór jest
        w drodze (panel Rodowód, edycja komórki, zapis perspektywy, „Odrzuć" obu szuflad)."""
        self._gest_nr += 1

    def _przeladuj_po_gescie(self, msg, cel=(), **kw):
        """Zbiór od nowa W TLE z ogonem gestu (`_ogon_gestu`) i żetonem z TEJ chwili. `cel=()` -
        gest bez zaznaczenia do odłożenia (zapis szuflady, cofnięcie)."""
        self.refresh(w_tle=True, potem=partial(self._ogon_gestu, msg, cel, nr=self._gest_nr, **kw))

    def _ogon_gestu(self, msg, cel, *, nr, poza=True, recepta=None, odwrot=None, ts=None,
                    kanony=(), szczegol=""):
        """Ogon gestu zapisu PO PRZYŁOŻENIU zbioru (`refresh(w_tle=True, potem=…)`, AR-84): cel
        w zaznaczeniu, człon „poza widokiem", JEDNO zdanie i recepta - wspólny dla gestów obu osi
        zaznaczenia, uwag, izolacji zapisu, werdyktu wersji i przeniesienia faktów.

        W OGONIE, NIE ZARAZ PO ZLECENIU. Te kroki czytają model po odświeżeniu, więc do AR-84 skład
        szedł synchronicznie i okno stało po każdym geście (1,1-1,3 s na kopii pf4 w fali 3).
        Skład idzie teraz w tle, a ogon leci po przyłożeniu - także po przyłożeniu nowszego zlecenia,
        które wyprzedziło gest (ogony przechodzą na nowsze, `refresh`), więc pomiar mówi o zbiorze,
        który widać. Na czas składu zbiór jest „w drodze" (`_zbior_w_drodze`): gesty zaznaczenia
        odmawiają, a zaznaczenie stoi (`_sync_zbioru_w_drodze`) - ogon nie nadpisze wyboru, którego
        człowiek nie zobaczyłby na ekranie.

        SYGNAŁY DO CUDZYCH POWIERZCHNI (osie, plakietka Porządków) LECĄ PRZED ZLECENIEM SKŁADU, nie
        w ogonie: mówią o stanie bazy, nie zbioru, a ich odbiorcy liczą na wątku GUI. Obok składu
        w tle dzieliłyby z nim GIL - zmierzone na kopii pf4: kolejka osi obiektu 1036 ms w trakcie
        składu wobec 435 ms przed nim.

        ZAZNACZENIE PRZEŻYWA GEST (R-S2b-3): `cel` to zaznaczenie z chwili gestu.
        CEL GESTU BYWA WYPCHNIĘTY Z WIDOKU PRZEZ SAM GEST (FC-2) - i to nie jest przypadek
        brzegowy: przy facecie `Obiekt=NGC3623` cofnięcie zostawia widok 43 → 0 klatek
        (zmierzone na kopii żywej bazy), bo `facet_objects` JOIN-uje po `f.object_id`,
        a nagrobek z niego wypada. Ta sama figura od drugiej strony jest przy przywracaniu
        TYPOWA: klatka z obiektem nie należy już do perspektywy „Do przeglądu". Liczba jest
        POMIAREM (ile z celu wróciło na przebudowany model), nie domysłem z liczników klingi.
        `poza=False` - gest bez tego członu (werdykt wersji, przeniesienie faktów).

        ZDANIE IDZIE PO PRZYŁOŻENIU, nie przed (adjudykacja recenzji S2b): przeładowanie kończy się
        własnym raportem („Grid: N klatek…"), a odbiornikiem jest jedna etykieta paska stanu -
        zdanie wyemitowane wcześniej ginęło pod nim. KAŻDY FAKT GESTU JEDZIE W TYM JEDNYM ZDANIU,
        nie drugą emisją: dwa `emit` w jednym obrocie pętli trafiają w jedną etykietę, więc drugie
        wymazuje pierwsze (bramka pakietu 0810).

        `recepta` = cel recepty (`None` - gest jej nie rusza), `odwrot` jak w `_po_gescie_osi`,
        `ts` = znacznik gestu w dzienniku z CHWILI ZAPISU (AR-94): ogon leci później, a recepta
        ma nieść tożsamość tego gestu, nie zdarzenia ręki, które mogło dojść w międzyczasie.
        `nr` = żeton z chwili zlecenia (`_podbij_zeton`): inny znaczy, że po zleceniu padł nowszy
        gest i to jego zdanie, recepta i zaznaczenie zostają. Pusty `msg` - ogon bez zdania.
        `kanony` = obiekty celu gestu (`ObjectGesture.canons`) dla członu odsłonięcia recepty.
        `szczegol` = szczegół zdania (wiersze szczegółu systemu, różne powody, spadek - jak w szufladzie):
        zdanie idzie na pasek jako `ZdanieZeSzczegolem` PO doklejeniu członów (AR-218) - podpowiedź
        paska gospodarza niesie wtedy plik, który padł. Nośnik `ZdanieZeSzczegolem` jako SAM `msg`
        wolno podać wyłącznie bez członów doklejanych tutaj (`poza=False`, pusty `cel`) - doklejenie
        zwraca goły `str` i szczegół przepada; inaczej szczegół idzie przez `szczegol=`."""
        if nr != self._gest_nr:
            return
        wrocilo = self._przywroc_zaznaczenie(cel)
        if poza:
            msg += self._czlon_poza_widokiem(len(cel) - wrocilo, cel)
        if msg:
            self.status_message.emit(ZdanieZeSzczegolem(msg, szczegol) if szczegol else msg)
        if recepta is not None:
            self._ustaw_recepte_gestu(recepta, odwrot, ts=ts, kanony=kanony)

    def _ustaw_recepte_gestu(self, cel, odwrot=None, *, ts=None, kanony=()):
        """Zapamiętaj STAN recepty ostatniego gestu i podaj ją na pasek (FH-2e).

        RECEPTA ŻYJE TYLE, CO JEJ PRAWDA, NIE TYLE, CO KOMUNIKAT. Do FH-2e żyła 5 s razem
        z raportem, a przy dwóch członach umierała po wykonaniu PIERWSZEGO: `refresh()` emitował
        własny raport i gasił ją dokładnie wtedy, gdy człon drugi stawał się wykonalny. Teraz
        widok pamięta CEL i DROGĘ POWROTU, a `refresh()` składa z nich receptę od nowa - człon
        odsłonięcia znika, gdy cel jest na ekranie, a człon powrotu, gdy nie ma już czego odwracać.
        `cel=None` zdejmuje receptę (pusta gasi tę z poprzedniego gestu).

        TOŻSAMOŚĆ GESTU (AR-94) - znacznik ostatniego zdarzenia ręki w dzienniku, czytany zaraz po
        zapisie gestu, więc to jest `ts` właśnie zapisanego gestu (klinga pisze gest jednym `now`).
        Ogon po składzie w tle (`_ogon_gestu`) leci później i podaje `ts` złapany w chwili zapisu;
        bez niego czytamy TERAZ. Recepta niesie go dalej, a Dom opisuje nim „Ostatnio”.

        `kanony` = obiekty, których gest dotknął (`ObjectGesture.canons`); człon odsłonięcia nazywa
        nimi cel („odsłonisz 43 klatki NGC3623: …"), gdy obiekt jest jeden. Gest bez obiektu
        (wycofanie, uwagi) podaje sam licznik."""
        self._podbij_zeton()
        self._recepta_gestu = (tuple(cel), odwrot) if cel else None
        self._ts_recepty = (ts or queries.last_hand_ts(self.con)) if cel else None
        self._kanony_recepty = tuple(kanony) if cel else ()
        self._emituj_recepte_gestu()

    def ponow_recepte(self):
        """Podaj receptę ostatniego gestu jeszcze raz, o ile wciąż jest prawdą - publiczne wejście
        gospodarza przy powrocie do Zbiorów (FH-2e): poza nimi recepta schodzi z paska, ale stan,
        z którego się składa, trwa. Milczy, gdy żaden gest recepty nie zostawił."""
        if self._recepta_gestu is not None:
            self._emituj_recepte_gestu()

    def _emituj_recepte_gestu(self):
        """Złóż receptę z bieżącego stanu i wyślij ją na pasek. Pusta - gdy przestała być prawdą."""
        czlony = self._czlony_recepty_gestu()
        if not czlony:
            self._recepta_gestu = None
        self.status_recipe.emit(_zlacz_recepty(czlony, self._ts_recepty if czlony else None))

    def _czlony_recepty_gestu(self):
        """Człony recepty ostatniego gestu, w KOLEJNOŚCI W CZASIE, policzone ze stanu w chwili pytania.

        Odsłonięcie, gdy choć jedna klatka celu jest poza widokiem i istnieje gest, który ją
        odsłoni (`_recepta_powrotu_do_widoku`, cel „gest"); wykonawca pyta o wybór gestu PONOWNIE
        w chwili kliknięcia. Droga powrotu, dopóki jest co odwracać (`_Odwrot.zostalo`) - wykonalna
        od razu, gdy cały cel jest na ekranie, a w wariancie „potem" bez wykonawcy (przycisk
        wygaszony, zdanie zostaje).

        CZŁON ODSŁONIĘCIA NAZYWA SWÓJ CEL (`grid.sel.reveal_target`): liczbę klatek celu, których nie
        ma na ekranie, i obiekt gestu, gdy jest jeden. Recepta żyje dłużej niż zdanie raportu, do
        którego dawne „odsłoni je …" się odwoływało - w innym zbiorze (Znajdź „M64" po geście na
        NGC3623) „je" nie miało odniesienia, a klik działa na bieżący widok.

        ODWRÓT BEZ WIDOKU (`_Odwrot.bez_widoku`, AR-178) jest wykonalny także, gdy celu nie widać,
        a odsłonięcia recepta wtedy nie dostaje: cel wraca na ekran razem z cofnięciem."""
        if self._recepta_gestu is None:
            return []
        cel, odwrot = self._recepta_gestu
        widoczne = set(self._frame_ids)
        ukryte = sum(1 for f in cel if f not in widoczne)
        bez_widoku = odwrot is not None and odwrot.bez_widoku
        poza = ukryte > 0 and not bez_widoku
        czlony = []
        if poza:
            recepta = self._recepta_powrotu_do_widoku()
            if recepta is not None:
                klucz, kwargi = recepta
                obiekt = (i18n.t("grid.sel.reveal_object", canon=self._kanony_recepty[0])
                          if len(self._kanony_recepty) == 1 else "")
                # Odsłonięcie to sama NAWIGACJA (perspektywa, zbiór) - bez zapisu, więc bez bramki
                # zajętości: w trakcie etapu ma działać jak każde przełączenie widoku.
                czlony.append(CzlonRecepty(
                    i18n.t_plural("grid.sel.reveal_target", ukryte, obj=obiekt,
                                  how=i18n.t(klucz, **kwargi)),
                    partial(self.wykonaj_recepte_powrotu, cel=_CEL_GEST)))
        if odwrot is not None and getattr(self, odwrot.zostalo)(cel):
            tekst = i18n.t(odwrot.klucz_potem if poza else odwrot.klucz,
                           menu=i18n.t(odwrot.menu), action=i18n.t(odwrot.akcja))
            czlony.append(CzlonRecepty(tekst, None if poza else partial(
                self._wykonaj_czlon, partial(self._wykonaj_odwrot, cel, odwrot))))
        return czlony

    def _wykonaj_czlon(self, wykonaj):
        """Bramka ZAJĘTOŚCI przed wykonaniem członu ODWROTU (Z4) - ta sama, co przed gestami
        izolacji (`_powod_zajetosci`). Członu odsłonięcia nie obejmuje: to sama nawigacja, bez
        zapisu. Recepta jest nowym klikalnym wejściem do zapisu osi, a etap
        Dostawy albo zapis nagłówków pisze w tym czasie do tej samej bazy z innego połączenia:
        klik dostałby blokadę do `busy_timeout` albo `database is locked`. Odmowa mówi na pasku
        DLACZEGO; recepta zostaje, bo po końcu zajętości jest dalej prawdziwa."""
        if self._odmowa_zajetosci():
            return
        wykonaj()

    def _odmowa_zajetosci(self):
        """Bramka zajętości gestów zapisu osi zaznaczenia, które recepta nazywa - wspólna dla
        recepty (`_wykonaj_czlon`) i pozycji menu („Cofnij przypisanie”, „Przywróć cofnięte
        przypisanie”, „Przywróć klatkę”, AR-70). `True` = odmowa wypowiedziana, gest nie rusza.

        Pozycje menu omijały ją do AR-70: zapis osi szedł połączeniem GUI obok workera etapu albo
        zapisu do plików (blokada do `busy_timeout`). Pozycje NIE gasną na czas zajętości: menu tego
        repo nie pokazuje podpowiedzi pozycji, a wygaszona pozycja odebrałaby jedyną drogę do
        powodu - klik dostaje zdanie z `_RECEPTA_ZAJETA`. Odmowa nie zmienia stanu, więc recepta
        poprzedniego gestu dalej obowiązuje: raport zdjął ją z paska, więc podajemy ją ponownie.

        ZBIÓR W DRODZE ODMAWIA PIERWSZY (AR-84): zaznaczenie wskazuje wiersze zbioru, który zaraz
        zostanie zastąpiony, a ogon poprzedniego gestu dopiero odłoży cel i receptę. Recepty nie
        podajemy wtedy ponownie - przyłożenie zbioru złoży ją ze stanu sam (`_przyloz`)."""
        if self._odmowa_w_drodze():
            return True
        powod = self._powod_zajetosci()
        if powod is None:
            return False
        self.status_message.emit(i18n.t(_RECEPTA_ZAJETA[powod]))
        self.ponow_recepte()
        return True

    def _wykonaj_odwrot(self, cel, odwrot):
        """Wykonaj drogę powrotu z recepty: zaznacz CEL gestu i wywołaj slot pozycji menu, którą
        recepta nazywa - ten sam kod, co klik w menu, bez kopii. Zaznaczenie stawiamy od nowa, bo
        user mógł je zmienić od chwili gestu, a recepta mówi o klatkach GESTU, nie o bieżącym wyborze.
        Po odwrocie zaznaczenie ZOSTAJE zawężone do klatek realnie zmienionych przez gest (`cel` to
        `gest.frame_ids`) - zaznaczone jest dokładnie to, co odwrócono."""
        self._przywroc_zaznaczenie(cel)
        getattr(self, odwrot.slot)()

    def _ile_do_przywrocenia(self, cel):
        """Ile klatek celu niesie nagrobek z pamięcią (droga powrotu cofnięcia przypisania)."""
        return queries.selection_object_state(self.con, list(cel))["restorable"]

    def _ile_do_cofniecia(self, cel):
        """Ile klatek celu ma przypisanie, które ręka może cofnąć (droga powrotu przywrócenia)."""
        return queries.selection_object_state(self.con, list(cel))["clearable"]

    def _ile_wycofanych(self, cel):
        """Ile klatek celu jest dziś wycofanych (droga powrotu wycofania)."""
        return len(set(cel) & queries.retired_frame_ids(self.con))

    def _czlon_poza_widokiem(self, poza, cel=None):
        """Człon „poza widokiem: N" - WSPÓLNY DLA OBU OSI zaznaczenia (FC-2).

        Obie osie mają ten sam problem i to nie jest analogia: na osi obiektu gest wypycha cel przy
        aktywnym facecie „Obiekt", a na osi żywotności klatki wypchnięcie jest wręcz REGUŁĄ, bo
        wycofanie zdejmuje klatkę z kubełków roboczych. Dwie kopie tej frazy rozjechałyby się przy
        pierwszej poprawce, a trzecia oś dołożyłaby trzecią (bramka pakietu, soczewka repo).

        ZWRACA SAM FAKT. „poza widokiem: N" jest POMIAREM i należy do raportu, a „odsłonisz N klatek …"
        jest INSTRUKCJĄ z własnym nośnikiem (FH-2) - i od FH-2e składa się ze STANU gestu
        (`_czlony_recepty_gestu`), nie z tej chwili, bo ma przeżyć odświeżenie, po którym cel
        wraca na ekran.

        Pusty łańcuch przy zerze, żeby wołający nie musiał pytać - milczenie jest tu poprawną
        odpowiedzią: zdanie o zerze klatek poza widokiem mówiłoby o czymś, co się nie stało."""
        if not poza:
            return ""
        # …i zapamiętaj CEL, żeby recepta odsłaniająca oddała go w zaznaczeniu (`refresh`).
        # Bez tego odsłonięcie jest tylko połową drogi: zbiór wraca, a klatki gestu toną w nim
        # bez śladu - zmierzone firsthandem na 43 klatkach w widoku 16 901 wierszy.
        self._cel_gestu = list(cel or [])
        return i18n.t("grid.sel.out_of_view", n=poza)

    def _rodzaj_recepty_powrotu(self, *, cel):
        """Którym JEDNYM gestem odsłonić to, czego nie widać - ze STANU zawężenia, liczone w chwili
        pytania, nie zapamiętane w `refresh()` (FC-2, BP-4). Zwraca RODZAJ recepty (`_POWROT_*`)
        albo `None`, gdy nie ma czego doradzić.

        JEDYNY WŁAŚCICIEL WYBORU GESTU, Z JAWNYM CELEM, bo „co odsłonić" to dwa pytania (FH-4,
        poprawka po firsthandzie). `_CEL_GEST` pyta o klatki wypchnięte gestem osi (recepta paska),
        `_CEL_WIDOK` o klatki bieżącego widoku (pusty stan). Każda powierzchnia mapuje rodzaj na
        WŁASNE brzmienie, ale żadna nie wybiera gestu sama - do FH-4 pusty stan miał własny, ogólny
        tekst i po geście przy facecie przeczył zdaniu, które pasek podał pięć sekund wcześniej.

        RECEPTA MUSI BYĆ WYKONALNA, i to jest tu jedyne kryterium. „× Wyczyść zbiór" zdejmuje
        facety i filtr, ale flag perspektywy NIE tyka (`_on_clear_selection` - są własnością
        perspektywy), więc przy aktywnym trimie odsłania WYŁĄCZNIE klatki tej perspektywy. Repo
        dostało już tę klasę raz, przy komunikacie o konflikcie („zawęź do dwóch", gdy zawężenie
        nic nie zmieniało). Stąd różne odpowiedzi przy trimie:
        - cel „gest": pierwszeństwo ma PERSPEKTYWA, bo klatka, której gest zmienił stan, wypadła
          z SAMEJ perspektywy (przypisany obiekt wyrzuca z „Do przeglądu") - odsłoni ją tylko inna;
        - cel „widok": gdy perspektywa MA klatki, a zbiór je zasłania, recepta to „× Wyczyść
          zbiór" i perspektywa zostaje. Pierwsza wersja FH-4 pytała tu o klatki gestu i wyrzucała
          z kolejki (firsthand: „Do przeglądu" z 8 czekającymi klatkami prowadziło na „Przegląd"
          z 16 901). Gdy populacja trimu jest pusta, zbioru czyścić nie ma po co.

        GDY WYGRYWA PERSPEKTYWA, JEDEN GEST ODSŁANIA WSZYSTKO: przełączenie zeruje TAKŻE facety
        i filtr (`_on_perspective`), a „Przegląd" nie niesie ani trimu, ani filtra; wariant „zdejmij
        oba" kazałby zrobić dwa gesty tam, gdzie wystarcza jeden (bramka pakietu, zarzut
        o nadmiarową receptę). Bez trimu wygrywa gest WĘŻSZY: przycisk zbioru.

        `cel` JEST KEYWORD-ONLY z tego samego powodu co w `_on_object_name`: wykonawca wisi na
        `clicked`, które niesie `checked: bool`. Cel spoza dwóch znanych to błąd wołającego (EXPECT),
        nie trzecia, cicha gałąź."""
        if cel not in (_CEL_GEST, _CEL_WIDOK):
            raise ValueError(f"nieznany cel recepty powrotu: {cel!r}")
        trim, zbior = self._trim_aktywny(), self._zbior_zawezony()
        if cel == _CEL_WIDOK and trim and zbior and self._populacja_trimu():
            return _POWROT_ZBIOR
        if trim:
            return _POWROT_PERSPEKTYWA
        if zbior:
            return _POWROT_ZBIOR
        return None

    def _populacja_trimu(self):
        """Klatki, które perspektywa wpuszcza BEZ zawężenia zbioru - przecięcie aktywnych trimów,
        składane z `_TRIMY` (BP-4: skład rodziny ma jedno miejsce) i liczone w chwili pytania.
        `set.intersection` oddaje NOWY set, więc zbiory zapytań nie są przycinane w miejscu.

        Pytanie ma sens wyłącznie przy aktywnym trimie - bez niego populacją jest całe uniwersum,
        a tego ta metoda nie liczy. Wołanie bez trimu to błąd wołającego (EXPECT)."""
        trimy = [getattr(queries, nazwa)(self.con) for atrybut, nazwa in _TRIMY
                 if getattr(self, atrybut)]
        if not trimy:
            raise ValueError("populacja trimu bez aktywnego trimu")
        return set.intersection(*trimy)

    def _recepta_powrotu_do_widoku(self):
        """GEST odsłonięcia w recepcie PASKA STANU - `(klucz, kwargi)` albo `None`, gdy nie ma czego
        doradzić; zdanie z celem („odsłonisz N klatek …: {how}") składa `_czlony_recepty_gestu`.
        Pasek mówi o klatkach wypchniętych gestem, więc pyta decyzję o `_CEL_GEST`;
        pusty stan pyta tę samą metodę o `_CEL_WIDOK` i w trimie, który ma klatki, dostaje inną,
        też prawdziwą odpowiedź (FH-4, poprawka po firsthandzie). Brzmienie paska się przez to nie
        zmieniło. Recepta cytuje etykietę gestu z katalogu (nazwa presetu, napis przycisku zbioru),
        żeby zmiana napisu przenosiła się tu sama."""
        rodzaj = self._rodzaj_recepty_powrotu(cel=_CEL_GEST)
        if rodzaj == _POWROT_PERSPEKTYWA:
            return "grid.sel.out_of_view_persp", {"perspective": i18n.t(_PRESET_LABELS[_PRESET_CZYSTY])}
        if rodzaj == _POWROT_ZBIOR:
            return "grid.sel.out_of_view_set", {"action": i18n.t("grid.sel.clear_set")}
        return None

    def wykonaj_recepte_powrotu(self, *, cel):
        """WYKONAJ receptę powrotu dla podanego CELU - gest, który `_rodzaj_recepty_powrotu` wybiera
        w chwili kliknięcia, nie zapamiętany z chwili podania recepty (stan mógł się zmienić).

        JEDEN WYKONAWCA, CEL PODAJE WOŁAJĄCY (FH-4, poprawka po firsthandzie): przycisk pustego
        stanu pyta o `_CEL_WIDOK`, a przycisk recepty paska stanu pyta o `_CEL_GEST` (FH-2e: człon
        odsłonięcia w `_czlony_recepty_gestu` niesie ten wykonawca) - bez kopii wyboru. `cel`
        jest keyword-only, więc `checked: bool` z `clicked` nie wpadnie w jego miejsce. Mechanizmy
        są dwa i różne: lista perspektyw (przez `apply_perspective`, więc pozycja listy idzie za
        stanem) i przycisk zbioru.

        CEL RECEPTY WRACA W ZAZNACZENIU, Z KADREM (FC-2): oba gesty kończą się przeładowaniem
        zbioru, a jego przyłożenie (`_zastosuj_zbior`, także w tle - zbiór bywa w drodze) odkłada
        `_cel_gestu` w zaznaczeniu i przewija do pierwszej klatki. Cel stawiamy TU, z recepty paska,
        a nie z chwili gestu: `_czlon_poza_widokiem` odkłada go jednorazowo, więc każde przeładowanie
        między gestem a klikiem (inne zapytanie Znajdź, zmiana kolumn - ta oddaje zaznaczenie z chwili
        przyłożenia, AR-172, ale celu gestu nie przechowuje) go konsumowało - recepta
        „odsłonisz 43 klatki NGC3623" pokazywała wtedy cały zbiór bez zaznaczenia, a następny człon
        („Obiekt → Przywróć…") stał wygaszony. Pusty stan (`_CEL_WIDOK`) celu nie ma - odsłania widok."""
        rodzaj = self._rodzaj_recepty_powrotu(cel=cel)
        if rodzaj in (_POWROT_PERSPEKTYWA, _POWROT_ZBIOR) and cel == _CEL_GEST \
                and self._recepta_gestu is not None:
            self._cel_gestu = list(self._recepta_gestu[0])
        if rodzaj == _POWROT_PERSPEKTYWA:
            self.apply_perspective(_PRESET_CZYSTY)
        elif rodzaj == _POWROT_ZBIOR:
            self._on_clear_selection()
        else:
            # Między podaniem recepty a kliknięciem zniknęło i zawężenie zbioru, i trim - nie ma
            # czego odsłaniać. Klik bez skutku i bez zdania wyglądałby na zawieszenie (Z9).
            self.status_message.emit(i18n.t("grid.recipe.nothing_to_reveal"))
            self.ponow_recepte()

    def _ustaw_pusty_stan(self, baza_ma_klatki):
        """Zdanie i gest PUSTEGO GRIDU (FH-4) - wołane z `_refresh`, gdy zbiór jest pusty.

        Pusta baza nie ma czego odsłaniać: zdanie kieruje po dostawę, przycisku nie ma (wiz F5 #8).
        Niepusta baza bierze wariant z PRZYCZYNY pustki - z decyzji recepty pytanej o `_CEL_WIDOK`
        (FH-4, poprawka po firsthandzie): zbiór zasłania klatki perspektywy → zdanie o zbiorze
        i „× Wyczyść zbiór" (perspektywa zostaje); perspektywa nie ma ani jednej klatki → zdanie
        o perspektywie i przejście na „Przegląd". Pasek pyta tę samą metodę o klatki GESTU, więc
        w trimie, który ma klatki, obie powierzchnie mówią co innego - i obie prawdę. Przycisk nosi
        nazwę gestu: przy zbiorze dosłownie napis przycisku paska zbioru, żeby gest miał jedną nazwę
        na całym ekranie. Brak recepty przy niepustej bazie jest dziś nieosiągalny (bez zawężenia
        widać wszystkie klatki), więc zostaje zdanie bez przycisku: przycisk bez gestu obiecywałby
        coś, czego nie ma.

        NIE woła `_czlon_poza_widokiem`: tamten zapamiętuje klatki gestu (`_cel_gestu`), a pusty
        stan powstaje także bez gestu - wybór brzmienia nie ma prawa ruszać stanu zaznaczenia.

        PERSPEKTYWA KOPII, KTÓRA NIE WIE (`_FLAGI_CZEKAJA_NA_FAKTY`): pusta „Kopie niezgodne"
        mówiła „Brak klatek" i prowadziła na „Przegląd", a Porządki w tym samym stanie mówiły „?".
        Gdy perspektywa sama jest pusta (recepta: perspektywa, nie zbiór) i czekają kopie, których
        fakty mogą ją zmienić (`scan.copy_facts_candidates(porownywalne=True)` - ten sam predykat,
        co liczba Porządków), zdanie bierzemy z podpowiedzi Porządków, a przycisk prowadzi do
        Dostawy, bo tam mieszkają oba gesty, które dadzą odpowiedź."""
        self._pusty_do_dostawy = False
        if not baza_ma_klatki:
            zdanie, gest = i18n.t(_EMPTY_DB), ""
        else:
            rodzaj = self._rodzaj_recepty_powrotu(cel=_CEL_WIDOK)
            czeka = (scan.copy_facts_candidates(self.con, porownywalne=True)
                     if rodzaj == _POWROT_PERSPEKTYWA
                     and any(getattr(self, atrybut) for atrybut in _FLAGI_CZEKAJA_NA_FAKTY) else [])
            if czeka:
                self._pusty_do_dostawy = True
                zdanie = zdanie_kopii_bez_zeznania(czeka, dest=i18n.t("nav.dostawa"))
                gest = i18n.t("grid.empty_go_intake")
            elif rodzaj == _POWROT_PERSPEKTYWA:
                zdanie = i18n.t(_EMPTY_PERSP)
                gest = i18n.t("grid.empty_persp_action", perspective=i18n.t(_PRESET_LABELS[_PRESET_CZYSTY]))
            elif rodzaj == _POWROT_ZBIOR:
                zdanie, gest = i18n.t(_EMPTY_FILTER), i18n.t("grid.sel.clear_set")
            else:
                zdanie, gest = i18n.t(_EMPTY_VIEW), ""
        self.empty.setText(zdanie)
        self.empty_btn.setText(gest)
        self.empty_btn.setVisible(bool(gest))

    def _przywroc_zaznaczenie(self, frame_ids, *, biezacy=None, kolumna=None,
                              kadr=QAbstractItemView.PositionAtCenter):
        """Odłóż zaznaczenie po `frame_id` na PRZEBUDOWANYM modelu (R-S2b-3, człon pierwszy).

        `biezacy` (frame_id) i `kolumna` (znaczenie kolumny, `model._sort_id_for`) stawiają bieżącą
        komórkę tam, gdzie stała przed przeładowaniem (AR-164) - domyślnie pierwszy odłożony wiersz
        i kolumna 0. Wiersz albo kolumna, których po przeładowaniu nie ma, wracają do domyślnych.

        PO `frame_id`, NIE PO NUMERZE WIERSZA — i to nie jest ostrożność: gest osi zmienia klucz
        sortu tej kolumny (`_object` bierze się z kanonu), a filtr perspektywy potrafi klatkę ze
        zbioru wyrzucić. Numer wiersza po `refresh()` wskazuje więc zupełnie inną klatkę.

        JEDNO WYWOŁANIE `select()`, NIGDY PĘTLA. Każde wywołanie emituje `selectionChanged`, a ten
        ciągnie `_update_count` → read-model osi (zmierzone 31 ms przy 16 648 klatkach). Pętla po
        zakresach wracałaby dokładnie do kwadratu, który zdjęło P-K (2 071 ms → 2 ms).

        ZAKRESY ŁAMIĄ SIĘ NA MARKERACH GRUP i to jest zmierzone falsyfikatorem, nie założone:
        `select()` na zakresie obejmującym wiersz NIESELEKTOWALNY wciąga go do `sm.selection()`
        (`selectedRows()` go odsiewa, ZAKRESY nie), a `_selected_data_rows` czyta właśnie zakresy.
        Bez łamania po geście podświetlałby się nagłówek grupy — wiersz, którego gest nie tknął.

        KADR IDZIE ZA ZAZNACZENIEM. Po przyłożeniu zbioru zaznaczenie odłożone poprawnie bywa
        NIEWIDOCZNE: user patrzy na pierwszy wiersz, a jego 120 klatek siedzi w połowie szesnastu
        tysięcy. `NoUpdate` przy `setCurrentIndex`, bo bieżąca komórka jest tu kotwicą dla Shift,
        a nie drugim, konkurencyjnym zaznaczeniem. `kadr` = tryb `scrollTo` (domyślnie środek);
        `None` - bez przewijania, także tego, które `setCurrentIndex` robi sam (`autoScroll`):
        reset bez nowych danych zostawia pion tam, gdzie był (AR-187, `_zaznaczenie_po_resecie`).

        Klatka, która po geście wypadła ze zbioru (perspektywa „Do przeglądu" pyta o `object_id
        IS NULL`, więc PRZYWRÓCONA klatka do niej nie należy), po prostu nie wraca — to uczciwe,
        bo jej na ekranie nie ma. Dla gestu przywracania jest to przypadek TYPOWY, nie brzegowy,
        i dlatego zdanie po geście musi być pełne: bywa jedynym potwierdzeniem.

        ZWRACA, ILE WIERSZY REALNIE ODŁOŻONO - bo dopiero różnica wobec celu mówi, ile klatek gest
        wypchnął z widoku (FC-2). Liczba jest tu darmowa (lista i tak powstaje), a policzona
        u wołającego wymagałaby drugiego przebiegu po modelu."""
        sm = self.table.selectionModel()
        if sm is None or not frame_ids:
            return 0
        chciane = set(frame_ids)
        numery = [i for i, row in enumerate(self.model._rows)
                  if isinstance(row, dict) and row.get("frame_id") in chciane
                  and "_group" not in row]
        if not numery:
            return 0
        ostatnia = self.model.columnCount() - 1
        sel = QItemSelection()
        start = prev = numery[0]
        for i in numery[1:] + [None]:
            if i != prev + 1:                       # koniec ciągu — także gdy przerwał go marker
                sel.select(self.model.index(start, 0), self.model.index(prev, ostatnia))
                start = i
            prev = i
        # Bez `Rows`: zakresy już obejmują wszystkie kolumny (0..ostatnia, także ukryte), a `Rows` kazał
        # Qt przepisać każdy zakres od nowa (`expandSelection`) - przy zaznaczeniu poszatkowanym przez sort
        # tysiące zakresów (AR-202).
        sm.select(sel, QItemSelectionModel.ClearAndSelect)
        wiersz = next((i for i in numery if self.model._rows[i].get("frame_id") == biezacy),
                      numery[0]) if biezacy is not None else numery[0]
        kol = next((c for c in range(self.model.columnCount())
                    if self.model._sort_id_for(c) == kolumna), 0) if kolumna is not None else 0
        pierwszy = self.model.index(wiersz, kol)
        if kadr is None:
            auto = self.table.hasAutoScroll()
            self.table.setAutoScroll(False)
            try:
                sm.setCurrentIndex(pierwszy, QItemSelectionModel.NoUpdate)
            finally:
                self.table.setAutoScroll(auto)
            return len(numery)
        sm.setCurrentIndex(pierwszy, QItemSelectionModel.NoUpdate)
        self.table.scrollTo(pierwszy, kadr)
        # …I DRUGI RAZ PO USTALENIU UKŁADU (FH-11). Tabela pokazana w tym samym obrocie pętli
        # (pusty widok → recepta → zbiór wraca) ma jeszcze geometrię sprzed pokazania, więc
        # środek liczony teraz jest środkiem cudzego kadru - klatki lądowały na dolnej krawędzi.
        # Indeks TRWAŁY: kolejne przeładowanie przed obrotem pętli unieważnia go, zamiast wskazać
        # inną klatkę pod tym samym numerem wiersza.
        trwaly = QPersistentModelIndex(pierwszy)
        QTimer.singleShot(0, self, lambda: trwaly.isValid() and self.table.scrollTo(
            self.model.index(trwaly.row(), trwaly.column()), kadr))
        return len(numery)

    def _on_object_name(self, *, preselect_canon=None):
        """„Przypisz obiekt…" ze Zbiorów: nadpisuje WYŁĄCZNIE źródła słabe, przy zamrożonym stanie
        okna. (Do R-S2b-11 pozycja nazywała się „Nazwij zaznaczenie…" — jeden z czterech czasowników
        na tę samą robotę.)

        `preselect_canon` niesie WYBÓR, KTÓRY JUŻ PADŁ w skrócie „ostatnio użyte" — okno otwiera
        się wtedy nie po to, żeby zapytać o nazwę, tylko żeby pokazać dysklozurę. Domyślne `None`
        zostawia drogę pozycji menu nietkniętą (tam wyboru jeszcze nie było).

        PARAMETR JEST KEYWORD-ONLY I TO NIE JEST GUST: ta metoda wisi na `QAction.triggered`,
        które emituje `checked: bool`, więc parametr pozycyjny łapałby `False` jako nazwę obiektu
        — cicho, bo pętla po bibliotece po prostu by go nie znalazła. Gwiazdka zamienia tę klasę
        pomyłki w błąd wywołania (EXPECT), a testem pinujemy, że sam sygnał wchodzi bez argumentu."""
        if self._odmowa_zajetosci():
            return
        ids = self._object_gesture_ids()
        if not ids:
            return
        stan = queries.selection_object_state(self.con, ids)
        if stan["conflict"]:
            # Dwa różne obiekty wśród klatek podlegających nadpisaniu ⇒ gest nie ma JEDNEGO
            # przedmiotu. Odmowa BEZ zapisu — częściowe wykonanie byłoby gorsze niż żadne, bo
            # user zobaczyłby „nazwano 30 z 80" i nie wiedział, które 30.
            # Liczba z READ-MODELU, nie literał: „2" było zaszyte, więc zaznaczenie z siedmioma
            # obiektami kazało zawęzić do dwóch, a po zawężeniu odmawiało tak samo — komunikat
            # o fałszywej liczbie jest receptą, której nie da się wykonać.
            self.status_message.emit(i18n.t("grid.sel.object_conflict", n=stan["conflict_n"]))
            return
        # LICZBA W OKNIE = ile gest realnie ruszy (`namable`), a nie ile zaznaczono: przycisk mówił
        # „Przypisz 8 klatek" i zapisywał 4, a przy realnym archiwum (większość lightów ma źródło
        # mocne) rozjazd jest regułą, nie wyjątkiem. Kontekst zaznaczenia idzie dalej, bo to okno
        # pyta wtedy o NADPISANIE cudzej nazwy i musi to powiedzieć zamiast zdania o kubełku RAW.
        # Zaznaczenie też bywa nagrobkiem — „Nazwij" jedzie `overwrite_weak=True`, więc gasi
        # werdykt tak samo, jak zapis z kubełka cofniętych. Liczba z read-modelu (`by_source`),
        # nie z osobnego zapytania: ten sam dict już wygasza kontrolkę.
        dlg = AssignObjectDialog(self.con, object_raw=None, frame_count=stan["namable"],
                                 selection=stan,
                                 cleared_n=stan["by_source"].get("user_cleared", 0),
                                 preselect_canon=preselect_canon, parent=self)
        if dlg.exec() != QDialog.Accepted or dlg.selected is None:
            return
        canon, catalog, kind, alias_norm = dlg.selected
        try:
            gest = repo.user_assign_object(
                self.con, alias_norm=alias_norm, canon=canon, catalog=catalog, kind=kind,
                frame_ids=ids, now=self._now(), overwrite_weak=True,
                expected_object_id=stan["expected_object_id"])
        except ValueError as e:                # konflikt aliasu / dryf do nieistniejącej klatki
            QMessageBox.warning(self, i18n.t("grid.sel.object_name"), str(e))
            return
        self._po_gescie_osi("grid.sel.object_named", gest, canon=canon)

    def _sync_recent_objects(self):
        """Zasil skrót „ostatnio użyte" przed pokazaniem menu (R-S2b-12)."""
        self.sel_bar.set_recent_objects(queries.recent_hand_objects(self.con))

    def _on_object_recent(self, canon, catalog, kind):
        """Skrót „ostatnio użyte": ten sam zapis co „Przypisz obiekt…", z pominiętym WYBOREM.

        Wszystkie guardy zostają i to jest cała różnica między skrótem a obejściem: pusty cel,
        konflikt dwóch obiektów w zaznaczeniu, zamrożony `expected_object_id` i klucz aliasu liczony
        JEDNYM właścicielem (`assign_dialog.alias_key`). Pomijamy okno, nie bramki — inaczej skrót
        byłby drugą, słabszą ścieżką zapisu tej samej osi.

        `object_raw=None`, bo cel bierze się z ZAZNACZENIA, a nie z grupy o wspólnym zeznaniu —
        dokładnie jak w `_on_object_name`, którego to jest skrót.

        SKRÓT ODDAJE STER OKNU, GDY MA COŚ ZGASIĆ (bramka pakietu, zarzut 4). Bramki techniczne
        skrót miał komplet, ale gubił jedyną DYSKLOZURĘ: okno mówi, ile nagrobków ręki zgaśnie
        (`assign.cleared_warning`) i ile cudzych nazw nadpisze (`assign.selection_overwrite`).
        Kontrakt `AssignObjectDialog` stawia to zdanie na DRODZE KLIKNIĘCIA, nie w tooltipie —
        więc dwa kliknięcia nie mogą po cichu skasować werdyktu człowieka. Gdy nie ma czego gasić
        (zwykły przypadek: świeże klatki), skrót pisze wprost i zostaje przy obiecanych 2 gestach."""
        if self._odmowa_zajetosci():
            return
        ids = self._object_gesture_ids()
        if not ids:
            return
        stan = queries.selection_object_state(self.con, ids)
        if stan["conflict"]:
            self.status_message.emit(i18n.t("grid.sel.object_conflict", n=stan["conflict_n"]))
            return
        if stan["overwrite"] or stan["by_source"].get("user_cleared"):
            # …z WYBOREM, KTÓRY JUŻ PADŁ (firsthand 0810, znalezisko 3): okno pyta o zgodę na
            # zgaszenie werdyktu, a nie o nazwę — więc wybrany kanon jedzie z nim jako preselekcja.
            # Bez tego skrót kosztował 5 interakcji zamiast obiecanych 2, i to dokładnie tam, gdzie
            # naprawa z kolejki jest regułą (nagrobek albo źródło `path`). Dysklozura zostaje.
            return self._on_object_name(preselect_canon=canon)
        try:
            gest = repo.user_assign_object(
                self.con, alias_norm=assign_dialog.alias_key(None, canon), canon=canon,
                catalog=catalog, kind=kind, frame_ids=ids, now=self._now(), overwrite_weak=True,
                expected_object_id=stan["expected_object_id"])
        except ValueError as e:                # konflikt aliasu / dryf do nieistniejącej klatki
            QMessageBox.warning(self, i18n.t("grid.sel.object_name"), str(e))
            return
        self._po_gescie_osi("grid.sel.object_named", gest, canon=canon)

    def _on_object_clear(self):
        """„Cofnij przypisanie": zdejmuje wyłącznie to, co postawiła ręka albo ścieżka.

        ZDANIE NIESIE DROGĘ POWROTU (FC-9). Odwracalność tego gestu jest w aplikacji od R-S2b-3,
        ale widać ją wyłącznie w tooltipie kontrolki („do przywrócenia: 46") i w pozycji menu za
        kliknięciem - czyli nigdzie w chwili, w której się przydaje. Człon idzie TYLKO po udanym
        zapisie: przy zerze mówiłby, jak cofnąć coś, co się nie stało. Etykiety cytujemy z KLUCZY
        i18n, nie literałem - recepta wskazująca napis, którego na ekranie nie ma, jest gorsza
        niż jej brak (klasa pilnowana bramką „surowego klucza").

        SAMĄ RECEPTĘ SKŁADA `_po_gescie_osi`, a ten gest tylko deklaruje, że jest odwracalny -
        bo jej treść zależy od tego, czy cel gestu został na ekranie (tam jest ten pomiar)."""
        if self._odmowa_zajetosci():
            return
        ids = self._object_gesture_ids()
        if not ids:
            return
        gest = repo.clear_object_assignment(self.con, frame_ids=ids, now=self._now())
        self._po_gescie_osi("grid.sel.object_cleared", gest, odwrot=_ODWROT_COFNIECIA)

    def _on_object_restore(self):
        """„Przywróć cofnięte przypisanie" — DROGA POWROTU z masowego cofnięcia (R-S2b-3).

        Dług nazywał trzy człony i to jest ten trzeci: po pomyłkowym geście na 120 klatkach
        odtworzenie stanu sprzed niej kosztowało 6-8 interakcji PLUS pamięć człowieka o tym, co
        tam stało. Od 0017 pamięta to baza, więc naprawa kosztuje JEDEN gest — i składa się
        z członem pierwszym: zaznaczenie po cofnięciu ZOSTAJE, więc cel jest już wskazany.

        CEL = ZAZNACZENIE, jak obie sąsiednie pozycje menu. Wariant „cofnij OSTATNIĄ partię"
        (z dziennika) odpadł nie z powodu ceny: menu „Obiekt ▾" ma JEDNĄ regułę celu („ta akcja
        pisze wyłącznie po zaznaczeniu") i pozycja z własną regułą pisałaby po klatkach, których
        na ekranie nie widać. Cel z zaznaczenia jest przy tym OGÓLNIEJSZY — sięga też nagrobka
        sprzed tygodnia, nie tylko tego z ostatniej minuty.

        PISZE JEDNA KLINGA OSI (`repo.user_assign_object`, D-OW-2/B), transakcja per GRUPA, bo
        klinga przyjmuje jeden kanon na wywołanie, a masowe cofnięcie obejmuje bywa kilka obiektów.
        Wzorzec: `ConfirmPathObjectsDialog._on_confirm` (pętla klingi per nazwa, faza zajętości).

        `expected_source='user_cleared'` to GUARD DRYFU WEWNĄTRZ TRANSAKCJI: klatka, która między
        odczytem a zapisem przestała być nagrobkiem, liczy się jako pominięta, a nie zostaje
        przemalowana. Bez niego jedyną obroną byłby filtr w read-modelu, czyli POZA transakcją —
        obrona słabsza niż u obu sąsiadów (`expected_object_id` jest tu martwy z definicji, bo
        nagrobek ma `object_id IS NULL`).

        `alias_norm=None`: alias zapisało pierwotne nadanie, a przywrócenie niczego nie nazywa.
        `object_source='user'` (domyślne): przywrócenie JEST wskazaniem palcem — drugim świadomym
        gestem tej samej ręki.

        TRZY GESTY JEDNEJ OSI, JEDNA GRAMATYKA (FC-6, R-S2b-13): `assigned + skipped == len(ids)`.
        Sąsiednie gesty dostają całe zaznaczenie i odsiewają je licznikami klingi, a ten podawał
        klindze wyłącznie grupy - więc „z M" liczyło same nagrobki z pamięcią (firsthand: „30 z 30"
        przy 120 zaznaczonych), a reszta zaznaczenia nie liczyła się nigdzie. Gest startuje więc od
        rozbicia z read-modelu i mówi ZAWSZE przez `_po_gescie_osi`, także przy zerze grup: osobne
        zdanie „nie ma czego przywrócić" było drugą gramatyką tej samej osi, podczas gdy sąsiad
        w tej samej sytuacji mówi „Cofnięto … 0 z N · nie było czego cofać: N"."""
        if self._odmowa_zajetosci():
            return
        ids = self._object_gesture_ids()
        if not ids:
            return
        grupy, pominiete = queries.restore_targets(self.con, ids)
        gest = repo.ObjectGesture(**pominiete)
        # JEDEN GEST = JEDEN `now` dla wszystkich grup: tożsamością gestu w dzienniku jest `ts`
        # (recepta i „Ostatnio” Domu, AR-94) - `now` per grupa rozbijał gest na kilka znaczników,
        # a Dom opisywał wtedy tylko ostatnią grupę.
        now = self._now()
        if grupy:                            # faza „0 z 0" zapowiadałaby robotę, której nie ma
            with busy.busy(self.status_message.emit,
                           i18n.t("busy.restoring", done=0, total=len(grupy))) as faza:
                for i, g in enumerate(grupy):
                    try:
                        gest += repo.user_assign_object(
                            self.con, alias_norm=None, canon=g["canon"], catalog=g["catalog"],
                            kind=g["kind"], frame_ids=g["frame_ids"], now=now,
                            overwrite_weak=True, expected_source="user_cleared",
                            expected_cleared_id=g["object_id"])
                    except ValueError as e:  # dryf do nieistniejącej klatki / konflikt aliasu
                        QMessageBox.warning(self, i18n.t("grid.sel.object_restore"), str(e))
                        # Grupa, która padła, wycofała się w całości (`_immediate`), a grupy po
                        # niej do klingi nie doszły - ich klatki liczą się jako ODMOWA KLINGI
                        # (`skipped_failed`), bo inaczej nie liczyłyby się nigdzie i „z M" znów
                        # kłamałoby o zaznaczeniu. Nie jako dryf: konflikt aliasu nie znaczy, że
                        # stan się zmienił, a „zmieniły się w międzyczasie" mówiłoby właśnie to.
                        gest += repo.ObjectGesture(
                            skipped_failed=sum(len(r["frame_ids"]) for r in grupy[i:]))
                        break
                    faza.say(i18n.t("busy.restoring", done=i + 1, total=len(grupy)))
        # PRZYWRÓCENIE TEŻ JEST ODWRACALNE (FH-9): jego odwrotem jest „Cofnij przypisanie" na tych
        # samych klatkach. Bez deklaracji widżet recepty zostawał po tym geście pusty, choć para
        # gest↔odwrót jest symetryczna - a drugą stroną tej pary user właśnie się posłużył.
        self._po_gescie_osi(
            "grid.sel.object_restored", gest, odwrot=_ODWROT_PRZYWROCENIA,
            canons_key="grid.sel.object_canons_restored",
            nothing_key="grid.sel.object_restore_skip_nothing")

    # ---- zmiana obiektu RAZEM z plikiem (AR-17 krok 3, D-1011-5) ----

    def _on_object_change(self):
        """„Zmień obiekt…": wybór celu oknem przypisania (BEZ zapisu - okno zwraca wybór) → okno
        podglądu i wykonania (`ObjectChangeDialog`). Cel = zaznaczenie, jak każdy gest tej osi.

        Okno przypisania jest tu wyłącznie WYBIERAKIEM: ta sama lista, szukajka i drabina nazwy, ta
        sama walidacja i klucz aliasu (`assign_dialog.alias_key`) - druga lista obiektów rozjechałaby
        się z pierwszą przy pierwszej zmianie. Nagłówek, tytuł i przycisk mówią o tym geście, bo zdanie
        okna („N klatek bez nazwy…") opisuje inny przypadek.

        CEL BEZ FORMY KARTY TO ODMOWA PRZED PLANEM (D-1011-5): kanon znany tylko z aliasu nie wraca
        z karty do siebie, więc obietnica „karta i folder razem" nie ma czym się spełnić - lepiej
        powiedzieć to teraz niż po przeniesieniu plików."""
        if self._odmowa_w_drodze():                      # zaznaczenie zbioru, który zaraz zniknie
            return
        ids = self._object_gesture_ids()
        if not ids:
            return
        zajety = self._powod_zajetosci()
        if zajety is not None:
            self.status_message.emit(i18n.t(zajety))
            return
        wybor = AssignObjectDialog(self.con, object_raw=None, frame_count=len(ids), parent=self)
        wybor.setWindowTitle(i18n.t("grid.sel.object_change_pick_title"))
        wybor.head.setText(i18n.t_plural("grid.sel.object_change_pick_head", len(ids)))
        wybor.accept_btn.setText(i18n.t("grid.sel.object_change_pick_ok"))
        if wybor.exec() != QDialog.Accepted or wybor.selected is None:
            return
        canon, _catalog, _kind, alias_norm = wybor.selected
        target = queries.object_target(self.con, canon, alias_norm=alias_norm)
        if target is None:
            # Okno przypisania przepuściło nazwę tą samą drabiną, więc `None` znaczy, że dwa
            # wołania odpowiadają różnie na jedno pytanie - odmowa z nazwą, zero zapisu.
            QMessageBox.warning(self, i18n.t("grid.sel.object_change"),
                                i18n.t("grid.sel.object_change_unknown", canon=canon))
            return
        if target.card_form is None:
            QMessageBox.warning(self, i18n.t("grid.sel.object_change"),
                                i18n.t("grid.sel.object_change_no_card", canon=target.canon))
            return
        self._otworz_zmiane_obiektu(ids, target)

    def _on_align_files(self):
        """„Uzgodnij pliki…" (perspektywa „Plik nie zgadza się z obiektem", menu prawego kliku): to
        samo okno z `target=None` - obiekt w bazie zostaje, plik dogania ten, który klatka ma."""
        if self._odmowa_w_drodze():                      # zaznaczenie zbioru, który zaraz zniknie
            return
        zajety = self._powod_zajetosci()
        if zajety is not None:
            self.status_message.emit(i18n.t(zajety))
            return
        ids = self._object_gesture_ids()
        if ids:
            self._otworz_zmiane_obiektu(ids, None)

    def _sync_menu_zgodnosci(self):
        """Uczciwy disabled „Uzgodnij pliki…" w chwili pokazania menu: zajętość (etap, inny zapis)
        albo puste zaznaczenie - powód w tooltipie pozycji; inaczej liczba klatek celu."""
        n = len(self._selected_data_rows())
        powod = self._powod_zajetosci() or (None if n else "grid.sel.object_empty")
        self.act_align_files.setEnabled(powod is None)
        self.act_align_files.setToolTip(
            i18n.t(powod) if powod is not None
            else i18n.t_plural("grid.sel.object_change_align_tip", n))

    def _otworz_zmiane_obiektu(self, ids, target):
        """Wspólny ogon obu wejść z zaznaczenia („Zmień obiekt…”, „Uzgodnij pliki…”): okno
        podglądu i wykonania. Nazwa pliku nie zależy od paska „Nazwy” - gest wymienia wyłącznie
        człon obiektu (D-1011-6 `O2`)."""
        self._pokaz_okno_zmiany_obiektu(ObjectChangeDialog(
            self.con, frame_ids=ids, target=target, now_fn=self._now, db_path=self._db_path,
            off_thread=self._wb.async_ok, parent=self), list(ids))

    def otworz_przebieg_zmiany_obiektu(self, run_id):
        """Wejście z Porządków (AR-121): okno na przerwanym przebiegu `run_id` - „Dokończ (N)”
        albo „Cofnij” bez CLI. Zaznaczenie po zmianie = klatki przebiegu.

        Ta sama straż zajętości co wejścia z zaznaczenia (bramka, kimi): okno otwarte w biegu
        etapu Dostawy albo innego zapisu miałoby czynne „Dokończ”/„Cofnij” - zajętość dochodzi do
        okna dopiero ze zbocza (`set_busy`), a nie przy jego otwarciu."""
        zajety = self._powod_zajetosci()
        if zajety is not None:
            self.status_message.emit(i18n.t(zajety))
            return
        dlg = ObjectChangeDialog(self.con, run_id=run_id, now_fn=self._now, db_path=self._db_path,
                                 off_thread=self._wb.async_ok, parent=self)
        self._pokaz_okno_zmiany_obiektu(dlg, list(dlg.frame_ids))

    def _pokaz_okno_zmiany_obiektu(self, dlg, zaznaczone):
        """Okno pisze do plików, więc jego zajętość idzie do mutexu gospodarza (`writeback_busy`),
        a każdy zapis i cofnięcie odświeża zbiór z zachowaniem zaznaczenia (`changed`) - okno jest
        modalne, ale lista pod nim ma mówić prawdę, gdy człowiek je zamknie albo cofnie gest."""
        dlg.changed.connect(lambda: self._po_zmianie_obiektu(zaznaczone))
        dlg.busy_changed.connect(self.writeback_busy)
        self._okno_zmiany_obiektu = dlg
        try:
            dlg.exec()
        finally:
            self._okno_zmiany_obiektu = None
        if not dlg.summary:
            return
        if self._zbior_w_drodze():
            # Zbiór po zapisie okna składa się jeszcze w tle - zdanie po przyłożeniu, inaczej raport
            # wczytania by je przykrył (AR-84). Ogon czeka w kolejce zlecenia, które jest w drodze.
            self._zbior_ogony.append(partial(self._ogon_gestu, dlg.summary, (), nr=self._gest_nr,
                                             poza=False))
        else:
            self.status_message.emit(dlg.summary)

    def _po_zmianie_obiektu(self, zaznaczone):
        """Ogon zapisu i cofnięcia w oknie zmiany obiektu: ścieżki, obiekt i karta klatek się
        zmieniły - zbiór od nowa, zaznaczenie zostaje (cel „Cofnij" i kolejnego gestu), a dwie
        cudze powierzchnie dostają sygnał (kolejka osi obiektu, plakietka Porządków). Zaznaczenie
        wraca ogonem po składzie w tle (AR-84), sygnały przed zleceniem składu (`_ogon_gestu`)."""
        self.object_axis_changed.emit()
        self.stan_porzadkow_changed.emit()
        self._przeladuj_po_gescie("", zaznaczone, poza=False)

    # ---- panele kling (F3, PLAN_ux_redesign §4) ----
    def _toggle_panel(self, which):
        """Panel klingi z paska zbioru: najwyżej JEDEN widoczny. Zamknięcie zostawia podgląd
        (kolumna podglądu w gridzie to wartość sama w sobie; staging żyje w poczekalni niezależnie).
        Otwarcie/przełączenie na panel X przy podglądzie CUDZEGO właściciela czyści go WPROST
        handlerem `cleared` (R#9 — bez emitowania sygnału cudzego widżetu). SEKWENCJA otwarcia =
        kontrakt (F3R#4): strona stacku → pokaż → echo daty (guard echa musi już widzieć rename)."""
        target = {"macro": self.macro_bar, "rename": self.rename_bar,
                  "lineage": self.lineage_bar}[which]
        # „otwarty" = JAWNIE pokazany (isHidden odwrócone), NIE isVisible() — to drugie jest False,
        # gdy przodek niepokazany (offscreen testy przed show()), i kłamałoby o stanie stacku.
        if not self.panel_stack.isHidden() and self.panel_stack.currentWidget() is target:
            self.panel_stack.setVisible(False)           # zamknięcie: podgląd ZOSTAJE
            self.sel_bar.set_active_panel(None)
            self._zapamietaj_panel_rodowodu()
            self._wroc_do_stagingu()
            return
        if (self._preview_owner and self._preview_owner != which
                and self.model._preview_active()):
            if self._preview_owner == "macro":
                self._on_macro_clear()
            else:
                self._on_rename_clear(oddaj_staging=(which == "macro"))
        if which == "rename":                            # wzór zwinięty albo nie - pamięć (AR-78)
            self.rename_bar.template_editor.set_expanded(
                self._settings().value(self._KLUCZ_WZORU_RENAMU, True, type=bool))
        self.panel_stack.setCurrentWidget(target)
        self.panel_stack.setVisible(True)
        self.sel_bar.set_active_panel(which)
        self._zapamietaj_panel_rodowodu()
        if which == "macro":
            self._wroc_do_stagingu()
        if which == "rename":
            self._refresh_date_echo()                    # PO pokazaniu strony (F3R#4)
        elif which == "lineage":
            self._refresh_lineage()                      # jw. — panel czyta zaznaczenie po pokazaniu

    def _wroc_do_stagingu(self):
        """Kolumna podglądu wraca do stagingu, gdy NIC jej nie trzyma, a w szufladzie czekają karty
        (AR-72, druga droga): samo otwarcie panelu nazw zdejmuje podgląd makra (R#9), a bez podglądu
        nazw nic go potem nie oddawało - 176 kart czekało do commitu bez kolumny. Zamknięcie panelu
        i powrót do panelu makra oddają kolumnę temu, co zapisze commit. Cudzy żywy podgląd zostaje."""
        if self.model._preview_active() or self._pending_count() <= 0:
            return
        self._preview_owner = "macro"
        self.model.set_preview(self._podglad_ze_stagingu())
        self._pokaz_kolumne_podgladu()

    # OTWARTY PANEL RODOWODU PRZEŻYWA ZAMKNIĘCIE PROGRAMU (wizytacja 0802). Pytanie „czym skalibrowano / z czego
    # powstał” zadaje się seriami, a każda seria zaczynała od kliknięcia „Rodowód…” (pierwsza
    # odpowiedź 3 → 2 interakcje, precedens: perspektywy). Pamiętamy WYŁĄCZNIE ten panel - makro
    # i rename niosą staging, a otwarcie ich samo z siebie po starcie byłoby niespodzianką.
    _KLUCZ_PANELU_RODOWODU = "grid/lineage_panel_open"

    def _zapamietaj_panel_rodowodu(self):
        self._settings().setValue(self._KLUCZ_PANELU_RODOWODU, self._lineage_panel_open())

    def _przywroc_panel_rodowodu(self):
        if (self._settings().value(self._KLUCZ_PANELU_RODOWODU, False, type=bool)
                and not self._lineage_panel_open()):
            self._toggle_panel("lineage")

    # WZÓR NAZWY ZWINIĘTY PO PIERWSZYM UŻYCIU (AR-78). Pierwsze otwarcie panelu pokazuje wzór
    # rozwinięty - tam człowiek dowiaduje się, że nazwę składa się z tokenów. Pierwszy podgląd albo
    # staging zapisuje „zwinięty", więc każde następne otwarcie zostawia tabeli wiersze, a wzór mówi
    # streszczeniem. Gest ręki (zwiń/rozwiń) nadpisuje pamięć i od tej pory ona decyduje.
    _KLUCZ_WZORU_RENAMU = "grid/rename_pattern_open"

    def _zapamietaj_uzycie_wzoru(self):
        ustawienia = self._settings()
        if not ustawienia.contains(self._KLUCZ_WZORU_RENAMU):
            ustawienia.setValue(self._KLUCZ_WZORU_RENAMU, False)

    def _rename_panel_open(self):
        return (not self.panel_stack.isHidden()
                and self.panel_stack.currentWidget() is self.rename_bar)

    def changeEvent(self, e):
        """Zmiana skórki PRZEBUDOWUJE panel rodowodu — wygaszenie wiersza jest w nim WYPALONE
        w itemie (`setForeground`), a nie czytane w `paint` jak w delegacie gridu, więc samo
        odmalowanie zostawiłoby kolor ze starego motywu. Lekcja jest w repo spisana od dawna
        (`app.py` przebudowuje z tego powodu inne listy) — panel rodowodu był drugim jej złamaniem,
        raz w osi stosów, raz w dołożonej osi kalibracji."""
        super().changeEvent(e)
        if e.type() == QEvent.PaletteChange:
            # Warunkowe: przy zamkniętym panelu nie czyta bazy. Wybór w panelu (wiersze, noc,
            # relacja) przeżywa przebudowę - zmiana skórki nie jest nawigacją (AR-172).
            self._refresh_lineage(**self._stan_panelu())

    # ---- panel RODOWODU (I-2d) ----
    def _lineage_panel_open(self):
        return (not self.panel_stack.isHidden()
                and self.panel_stack.currentWidget() is self.lineage_bar)

    def _refresh_lineage(self, *, select_frame_ids=None, select_relation=None, select_night=None):
        """Wypełnij panel rodowodu z zaznaczenia. Warunek: DOKŁADNIE JEDNA zaznaczona klatka
        `master_light` — rodowód jest faktem o JEDNYM obrazie, a „rodowód zbioru" nie znaczy nic.
        Każdy inny stan dostaje ZDANIE, nie pustkę: user ma wiedzieć, czego brakuje do odpowiedzi
        (wzorzec „uczciwy disabled", tylko że tłumaczy się panel, nie przycisk).

        `select_frame_ids` przywraca zaznaczenie PO odświeżeniu (werdykt ręki) — po klatkach,
        nie po indeksach, bo kolejność wierszy należy do zapytania, a nie do panelu.
        `select_relation` robi to samo na osi kalibracji (po geście ręki - relacja, nie indeks).
        `select_night` przywraca noc trybu propozycji (AR-172) - PRZED wierszami, bo lista
        pokazuje klatki wybranej nocy.

        Świadomie WARUNKOWE (jak `_refresh_date_echo`): przy zamkniętym panelu nie czytamy bazy."""
        if not self._lineage_panel_open():
            return
        wiersze = self._selected_data_rows()
        # LICZYMY KLATKI, NIE WIERSZE (AR-187): odtworzenie zaznaczenia po `frame_id` stawia każdy
        # wiersz klatki, więc dwa wiersze jednego obrazu to dalej jeden obraz - panel jednego stosu.
        stosy = list({r["frame_id"]: r for r in wiersze if r.get("kind") == "master_light"}.values())
        if len(stosy) != 1:
            # OŚ KALIBRACJI (C3, Issue #6) — druga odpowiedź tego samego panelu. Warunek jest
            # DOPEŁNIENIEM osi stosów, nie jej konkurentem: pytamy dopiero, gdy w zaznaczeniu nie
            # ma gotowego obrazu, więc droga stosu zachowuje się dokładnie jak przedtem.
            lighty = list({r["frame_id"]: r for r in wiersze if r.get("kind") == "light"}.values())
            # DOKŁADNIE JEDEN LIGHT W ZAZNACZENIU (klatki kalibracyjne obok nie przeszkadzają):
            # nagłówek panelu NAZYWA klatkę, o której mówi, więc cel gestu ręki jest jawny także
            # przy zaznaczeniu light + jego flat - dawne „dokładnie jeden wiersz” było ceremonią
            # z czasów, gdy nagłówek nazwy nie miał. Dwa wiersze tej samej klatki (dwie kopie) to
            # nadal jeden light.
            if len(lighty) == 1:
                relacje = lineage.explain_light(self.con, lighty[0]["frame_id"])
                if relacje:
                    self.lineage_bar.set_calibration(
                        relacje, frame_name=_nazwa_pliku(lighty[0].get("path")),
                        light_frame_id=lighty[0]["frame_id"], select_relation=select_relation)
                    return
            # DWIE POMYŁKI, DWA ZDANIA (plus pustka). Kilka klatek nieba albo kilka obrazów - panel
            # nie wie, o którym mówić; same klatki kalibracyjne - narzędzie nie ma rodowodu.
            klucz = ("grid.lin.hint.none" if not wiersze else
                     "grid.lin.hint.many" if len(stosy) > 1 or len(lighty) > 1 else
                     "grid.lin.hint.not_stack")
            self.lineage_bar.set_lineage(None, [], hint=i18n.t(klucz))
            return
        fid = stosy[0]["frame_id"]
        head = queries.stack_lineage_head(self.con, fid)
        if head is None:
            self.lineage_bar.set_lineage(None, [], hint=i18n.t("grid.lin.hint.not_computed"))
            return
        # PROPOZYCJA MATERIAŁU liczona TYLKO tam, gdzie jest pytaniem: obraz z rodowodem ma fakt,
        # a obraz z powodem ZWIETRZAŁYM czeka na przeliczenie etapem, nie na rękę. Poza tymi dwoma
        # stanami zapytanie chodziłoby po całym materiale obiektu przy każdym zaznaczeniu, nie
        # mając komu oddać wyniku.
        # Fakt „gest ma tu jeszcze co zrobić" jest JEDEN dla panelu, kolumny i perspektywy
        # (`queries.lineage_hand_state`): stos z odrzuconym ostatnim kandydatem nie wraca do trybu
        # propozycji z pustymi nocami, tylko pokazuje własne werdykty do ewentualnego cofnięcia.
        kandydaci, raw_bez_zegara, po_zintegrowaniu = (), 0, 0
        czeka, propozycja = queries.lineage_hand_state(self.con, fid)
        if czeka:
            kandydaci, raw_bez_zegara, po_zintegrowaniu = (
                propozycja if propozycja is not None
                else stacks.propose_lineage_candidates(self.con, fid))
        elif propozycja is not None:
            # STOS, KTÓRY WYPADŁ Z KUBEŁKA, BO PROPOZYCJA NIE MA CZEGO DAĆ (AR-154): trybu propozycji
            # nie otwieramy, ale licznik klatek nowszych niż obraz idzie do panelu - to on mówi,
            # dlaczego lista jest pusta. Bez niego zdanie znikało razem z trybem.
            po_zintegrowaniu = propozycja[2]
        # TRZECI ŚWIADEK ZEGARA (G2-1d): uwaga przebiegu o RAW-ach bez zegara przy obrazie, którego
        # werdykt mówi co innego - także przy GOTOWYM rodowodzie z puli mieszanej, gdzie propozycji
        # nie liczymy wcale. Bez tego członu flaga mówiłaby „nie umiem umieścić N klatek", a gest,
        # który je umieszcza, zostałby schowany (bramka niżej i `_sync_offset_visible`).
        raw_bez_zegara = raw_bez_zegara or _lineage_raw_note(head)
        # PROPOZYCJA ODNIESIENIA LICZONA TYLKO TAM, GDZIE JEST PYTANIEM (R2): dla 121 masterów
        # FITS/ASI zegar nie jest problemem, a zapytanie chodzi po całym materiale obiektu, więc
        # liczenie go przy każdym zaznaczeniu byłoby kosztem bez odbiorcy.
        #
        # DRUGI WYZWALACZ DOSZEDŁ Z BRAMKI 3a i stoi PO policzeniu kandydatów, bo dopiero one
        # mówią, że pytanie o zegar w ogóle padło. Powód `offset_unknown` sam nie wystarcza:
        # stos o zdegenerowanym oknie go nie dostanie (`stacks._plan` kończy wcześniej), a to
        # właśnie takie stosy stoją w kubełku z materiałem RAW nie do umieszczenia w czasie.
        self.lineage_bar.set_offset_hint(
            stacks.propose_offset_minutes(self.con, fid)
            if head["unresolved_reason"] == REASON_OFFSET_TOKEN or raw_bez_zegara else None)
        # Nazwy plików kandydatów - jednym zapytaniem dla wszystkich nocy (combo przerysowuje z pamięci).
        sciezki = (queries.frame_present_paths(self.con, [f["frame_id"] for n in kandydaci
                                                          for f in n.frames])
                   if kandydaci else {})
        self.lineage_bar.set_lineage(head, queries.stack_lineage_inputs(self.con, fid),
                                     candidates=kandydaci, raw_unreferenced=raw_bez_zegara,
                                     after_integration=po_zintegrowaniu, candidate_paths=sciezki)
        self._lineage_frame_id = fid
        if select_night is not None:
            self.lineage_bar.select_night(select_night)
        if select_frame_ids:
            self.lineage_bar.select_frame_ids(select_frame_ids)

    def refresh_lineage_panel(self):
        """Przerysuj panel rodowodu ze STANU — publiczne wejście dla gospodarza (NARROW).

        Wołane po zakończeniu KAŻDEGO etapu Dostawy, bo etap przepisuje `unresolved_reason`,
        a panel trzyma jego poprzednią wartość. Bez tego takt 3 zostawiał na ekranie zdanie
        „zapis nieaktualny" dokładnie po tym, jak sam ten zapis odświeżył (bramka pakietu, zarzut 7).

        WYBÓR CZŁOWIEKA W PANELU ZOSTAJE (AR-172): wiersze listy, noc trybu propozycji, relacja osi
        kalibracji. Gospodarz woła to zaraz po zleceniu przeładowania po przebiegu, jeszcze przed
        przyłożeniem zbioru - panel przebudowany bez stanu wracał na noc mastera i domyślną relację,
        a przyłożenie brało migawkę już z tego stanu.

        Cicho, gdy panel nie jest otwarty albo nic nie zaznaczono — `_refresh_lineage` sam
        rozstrzyga, czy ma co pokazać."""
        self._refresh_lineage(**self._stan_panelu())

    def _on_lineage_offset(self, minutes):
        """Wskazane odniesienie czasu → jedna klinga (`repo.set_integration_offset`), potem
        odświeżenie panelu ze STANU — lustro `_on_lineage_judged`.

        RODOWODU TU NIE PRZELICZAMY i to jest granica, nie brak: dobór wejść jedzie po CAŁYM
        archiwum stosów (`run_stack_lineage`), więc jest robotą etapu w Dostawie, nie skutkiem
        ubocznym kliknięcia w panelu. Zamiast tego zdanie mówi WPROST, gdzie to policzyć — ta sama
        umowa, co przy geście zestawu w R1."""
        iid = self.lineage_bar.integration_id()
        if iid is None:
            return
        self._podbij_zeton()                # zdanie tego gestu - nie ogona starszego (AR-84)
        # ILE KLATEK CZEKAŁO NA TEN ZEGAR (G2-3d) - CZYTANE PRZED ZAPISEM, nie po. Zakres offsetu
        # jest bramką na NONSENS, nie na pomyłkę: wskazanie o dobę obok przechodzi walidację,
        # a jedynym śladem był potem powód `no_candidates` bez słowa o przyczynie. Człon stoi
        # ZAWSZE, także przy zerze - to właśnie zero mówi „ten zegar nie miał czego odblokować".
        #
        # ⚠ KOLEJNOŚĆ JEST TU CAŁYM MECHANIZMEM (bramka pakietu, zarzut blokujący). Zapis czyni
        # powód ZWIETRZAŁYM (`queries.lineage_reason_stale`), więc `_refresh_lineage()` po nim nie
        # liczy już propozycji: liczba wzięta stamtąd byłaby strukturalnym zerem, czyli członem
        # martwym w chwili narodzin - i to nad stosem, pod którym stoi 36 klatek.
        czekalo = i18n.t("grid.lin.offset_waiting",
                         n=self.lineage_bar.klatki_bez_odniesienia())
        repo.set_integration_offset(self.con, master_frame_id=self._lineage_frame_id,
                                    utc_offset_min=minutes, now=self._now())
        self._refresh_lineage()
        # Zapis czyni powód `offset_unknown` zwietrzałym, a ten liczy się do plakietki Porządków
        # (`stacks_lineage_pending`) - odświeżenie nie może czekać na etap, który przy odmowie
        # albo bez `run_stage_fn` w ogóle nie ruszy.
        self.stan_porzadkow_changed.emit()
        godziny = f"{minutes / 60.0:+.1f}"
        # TAKT 3: gest sam się domyka. Bez tego user musiał przejść na inny ekran i znaleźć tam
        # przycisk stojący obok wyboru katalogu — akcja domykająca gest mieszkała w sekcji
        # o wciąganiu plików z dysku. Odmowa (etap już biegnie / brak bazy) NIE jest błędem gestu:
        # zapis się udał, więc mówimy prawdę o obu połówkach i zostawiamy zdanie z receptą.
        if self.run_stage_fn is None:
            self.status_message.emit(i18n.t("grid.lin.offset_saved", hours=godziny) + czekalo)
            return
        powod = self.run_stage_fn("stack_lineage")
        self.status_message.emit(
            (i18n.t("grid.lin.offset_saved_counting", hours=godziny) if powod is None
             else i18n.t("grid.lin.offset_saved_busy", hours=godziny, reason=powod)) + czekalo)

    # ---- gesty ręki osi KALIBRACJI (E4-5) i „Policz teraz” ----
    def _on_calibrator_picked(self, light_frame_id, relation, master_frame_id, widziany):
        """„Wskaż kalibrator…” → jedna klinga (`repo.link_calibration`, gałąź ręki z `confidence=
        'user'`), potem odświeżenie panelu ze STANU. Klinga waliduje pod blokadą to, co panel
        pokazał (`widziany`): dryf albo kandydat, który przestał się nadawać, to ODMOWA z tokenem,
        a panel po niej pokazuje stan bieżący - człowiek wybiera jeszcze raz na prawdzie, nie na
        zdjęciu sprzed chwili.

        PRZELICZENIA TU NIE MA i nie jest potrzebne: wskazanie ręki jest stanem samo w sobie,
        a przebieg rodowodu go omija (`run_lineage`)."""
        self._podbij_zeton()                # zdanie tego gestu - nie ogona starszego (AR-84)
        klasa = calibration_class_name(relation)
        try:
            zmiana = repo.link_calibration(
                self.con, light_frame_id=light_frame_id, master_frame_id=master_frame_id,
                relation=relation, now=self._now(), actor="user:local", asserted_by="user",
                confidence="user", expected=widziany)
        except repo.KalibratorOdrzucony as odmowa:
            self._refresh_lineage(select_relation=relation)
            self.status_message.emit(i18n.t(f"grid.lin.cal.refused.{odmowa.token}"))
            return
        except sqlite3.OperationalError:
            # Blokada zapisu trzymana dłużej niż `busy_timeout` (etap w tle na własnym połączeniu,
            # zapis do plików): zapis się nie odbył, a gest ma to powiedzieć zdaniem, nie traceback.
            self.status_message.emit(i18n.t("grid.lin.cal.db_busy"))
            return
        # Zaznaczenie wraca na relację gestu - następny krok (np. „Przywróć automat”) jest o klik bliżej.
        self._refresh_lineage(select_relation=relation)
        self.status_message.emit(i18n.t("grid.lin.cal.picked", rel=klasa) if zmiana
                                 else i18n.t("grid.lin.cal.picked_none", rel=klasa))

    def _on_calibrator_restored(self, light_frame_id, relation, master_frame_id):
        """„Przywróć automat” → `repo.unlink_calibration` wiersza RĘKI (CAS na masterze, który panel
        pokazał), potem takt 3: etap „Rodowód” odtwarza ogniwo z przepisu. Bez przeliczenia panel
        pokazałby „nie policzono” w miejscu, z którego człowiek właśnie zdjął swoją decyzję.

        PRZEPIS BEZ KANDYDATA: odpowiedź bierzemy ze STANU po zdjęciu (`explain_light`) - relacja
        nieliczona (`pending`) dostaje przeliczenie, luka zdanie „klatka została bez kalibratora”;
        uruchamianie etapu, który niczego nie odtworzy, obiecywałoby powrót, którego nie będzie."""
        self._podbij_zeton()                # zdanie tego gestu - nie ogona starszego (AR-84)
        klasa = calibration_class_name(relation)
        try:
            zdjete = repo.unlink_calibration(
                self.con, light_frame_id=light_frame_id, relation=relation, allowed=("user",),
                reason="user_restore", now=self._now(), actor="user:local",
                expected_master_frame_id=master_frame_id)
        except sqlite3.OperationalError:
            self.status_message.emit(i18n.t("grid.lin.cal.db_busy"))
            return
        self._refresh_lineage(select_relation=relation)
        if not zdjete:
            self.status_message.emit(i18n.t("grid.lin.cal.restored_none"))
            return
        stan = {r["relation"]: r for r in lineage.explain_light(self.con, light_frame_id) or ()}
        if not (stan.get(relation) or {}).get("pending"):
            self.status_message.emit(i18n.t("grid.lin.cal.restored_no_auto", rel=klasa))
            return
        self._policz_rodowod_kalibracji(light_frame_id, i18n.t("grid.lin.cal.restored", rel=klasa))

    def _sync_lineage_busy(self):
        """Bramka gestów panelu Rodowód (werdykt stosu, odniesienie, gesty osi kalibracji): etap
        Dostawy w tle ALBO zapis do plików z tej lub drugiej powierzchni (`_powod_zajetosci`) -
        każdy z nich trzyma blokadę zapisu bazy, a gest w tym czasie czekałby `busy_timeout`
        i wracał błędem zamiast zdaniem. Zbiór w drodze też gasi panel (AR-84): panel pokazuje stos
        zaznaczenia, które przyłożenie zaraz zastąpi, a ogon gestu odłoży w nim cel."""
        self.lineage_bar.set_busy(bool(self._etap_w_biegu or self._foreign_wb
                                       or getattr(self, "_zapis_wlasny", False)
                                       or self._zbior_w_drodze()))

    def _on_wlasny_zapis_plikow(self, busy):
        self._zapis_wlasny = bool(busy)
        self._sync_lineage_busy()

    def _on_calibration_count(self, light_frame_id):
        """„Policz teraz” przy ⚠: etap „Rodowód” jednym kliknięciem, bez wycieczki do Dostawy."""
        self._policz_rodowod_kalibracji(light_frame_id)

    def _policz_rodowod_kalibracji(self, light_frame_id, zdanie=""):
        """Takt 3 osi kalibracji: istniejący etap Dostawy `lineage` przez wstrzykniętą drogę
        gospodarza (`run_stage_fn`). Klatka panelu wraca do zaznaczenia przy przeładowaniu zbioru po
        przebiegu (`_cel_gestu`) - dawny koszt tej drogi to właśnie powrót, który czyścił zaznaczenie.
        Odmowa (etap biegnie, brak bazy) mówi prawdę o obu połówkach; bez gospodarza zdanie
        odsyła do Dostawy."""
        if self.run_stage_fn is None:
            reszta = i18n.t("grid.lin.cal.count_no_host")
        else:
            powod = self.run_stage_fn("lineage")
            if powod is None:
                self._cel_gestu = [light_frame_id]
                reszta = i18n.t("grid.lin.cal.counting")
            else:
                reszta = i18n.t("grid.lin.cal.count_busy", reason=powod)
        self.status_message.emit(" - ".join(x for x in (zdanie, reszta) if x))

    def _on_lineage_judged(self, frame_ids, excluded):
        """Werdykt ręki → jedna klinga (`repo.judge_integration_input`), potem odświeżenie panelu
        ze STANU. Zapis jest natychmiastowy i BEZ poczekalni: to decyzja o RELACJI w bazie, nie
        mutacja pliku - staging chroni bajty na dysku, a tu żaden bajt nie jest ruszany.

        „COFNIJ" W KOMUNIKACIE (D-1011-4): recepta paska niesie drogę powrotu do stanu SPRZED
        gestu - nie werdykt przeciwny, który zostawiłby `user` tam, gdzie decydował automat.
        Materiałem jest lista zmian z klingi zbiorczej (`judge_integration_inputs`): cały gest to
        JEDNA transakcja, więc nie ma gestu zapisanego w połowie i bez „Cofnij".

        W PERSPEKTYWACH KOLEJKI RODOWODU („Rodowód z klatkami nowszymi niż obraz”, AR-178; „Rodowód
        do potwierdzenia”, AR-196) cel przechodzi na następny obraz, gdy ten wypadł z niej po geście
        (`_nastepne_obrazy`)."""
        iid = self.lineage_bar.integration_id()
        if iid is None:
            return
        stos = self._lineage_frame_id
        zmiany = repo.judge_integration_inputs(
            self.con, integration_id=iid, input_frame_ids=list(frame_ids), excluded=excluded,
            now=self._now())
        n = len(zmiany)
        self._zacznij_gest()                # recepta poprzedniego gestu przestaje obowiązywać
        self._migawka_werdyktu = ((iid, stos, tuple(zmiany)),) if zmiany else None
        self._po_werdykcie((stos,), list(frame_ids), zmienione=bool(n),
                           nastepne=self._nastepne_obrazy(stos))
        if n:
            # Potwierdzone wejście czyni powód stosu zwietrzałym, a ten liczy się do plakietki.
            self.stan_porzadkow_changed.emit()
        # Klinga jest idempotentna, więc powtórzony ten sam werdykt daje 0 — a „Potwierdzono 0"
        # brzmi jak porażka zapisu, którym nie jest (QUIET: brak zmiany mówi o braku zmiany).
        klucz = ("grid.lin.judged_none" if not n else
                 "grid.lin.judged_excluded" if excluded else "grid.lin.judged_confirmed")
        zdanie = i18n.t(klucz, n=n)
        if n and excluded:
            zdanie += self._czlon_bez_wejsc((stos,))
        self.status_message.emit(zdanie)
        # Recepta PO zdaniu (kontrakt `status_recipe`); gest bez zmian recepty nie dostaje.
        self._ustaw_recepte_gestu((stos,) if zmiany else (), _ODWROT_WERDYKTU if zmiany else None)

    def _czlon_bez_wejsc(self, stosy):
        """Człon zdania odrzucenia: ile obrazów gestu zostało BEZ ANI JEDNEGO wejścia (AR-178) - ze
        stanu po zapisie. Obraz, któremu werdykt ręki potwierdził same klatki zrobione po nim, po
        odrzuceniu nie ma rodowodu, i to jest prawda o nim (`D-1016-1`); zdanie mówi ten skutek
        wprost, zamiast zostawić go stanowi kolumny. Pusty przy zerze."""
        k = sum(1 for s in stosy
                if not any(not r["excluded"] for r in queries.stack_lineage_inputs(self.con, s)))
        return i18n.t_plural("grid.lin.left_without_inputs", k) if k else ""

    def _perspektywa_kolejki_rodowodu(self):
        """Czy widok stoi w perspektywie, z której gest jednego stosu w panelu „Rodowód” wypycha stos:
        „Rodowód z klatkami nowszymi niż obraz” (AR-178) albo „Rodowód do potwierdzenia” (AR-196 -
        potwierdzone wejście wietrzy powód stosu, `queries.lineage_reason_stale`, a odrzucenie
        ostatniego kandydata zostawia mu pustą propozycję)."""
        return bool(getattr(self, _FLAGA_NOWSZYCH) or getattr(self, _FLAGA_POTWIERDZENIA))

    def _nastepne_obrazy(self, stos):
        """Kandydaci na cel po geście jednego stosu w perspektywie kolejki rodowodu
        (`_perspektywa_kolejki_rodowodu`), w kolejności tabeli: obrazy za stosem, potem przed nim (od
        najbliższego). Pierwszy, który po przeładowaniu jest w zbiorze, przejmuje zaznaczenie
        (`_panel_po_werdykcie`) - gest na kolejnym stosie jest wtedy o klik bliżej. Poza nią - pusto."""
        if not self._perspektywa_kolejki_rodowodu():
            return ()
        ids = [r["frame_id"] for r in self.model._rows if "_group" not in r]
        if stos not in ids:
            return ()
        i = ids.index(stos)
        return tuple(ids[i + 1:] + ids[:i][::-1])

    def _cel_nowszych(self):
        """Cel gestu zbiorczego: `master_frame_id → wejścia do odrzucenia` (`queries.lineage_newer_inputs`)
        dla obrazów, które WIDAĆ (doktryna §5, jak makro - facet w perspektywie zawęża cel)."""
        widoczne = set(self._frame_ids)
        return {m: ids for m, ids in queries.lineage_newer_inputs(self.con).items() if m in widoczne}

    def _sync_menu_nowszych(self):
        """Uczciwy disabled gestu zbiorczego w chwili pokazania menu: zajętość (etap, inny zapis) albo
        widok bez wejść do odrzucenia - powód w podpowiedzi pozycji; inaczej liczba obrazów celu."""
        n = len(self._cel_nowszych())
        powod = self._powod_zajetosci() or (None if n else "grid.lin.reject_newer_all_none")
        self.act_reject_newer_all.setEnabled(powod is None)
        self.act_reject_newer_all.setToolTip(
            i18n.t(powod) if powod is not None
            else i18n.t_plural("grid.lin.reject_newer_all_tip", n, undo=i18n.t("grid.lin.undo")))

    def _on_reject_newer_all(self):
        """„Odrzuć nowsze niż obraz we wszystkich obrazach" (perspektywa „Rodowód z klatkami nowszymi
        niż obraz", menu prawego kliku, AR-178): gest przycisku panelu na KAŻDYM widocznym obrazie
        naraz - jedna klinga (`repo.judge_stacks_inputs`: jedna transakcja dla wszystkich stosów)
        i jedno „Cofnij werdykt" na pasku, wykonalne bez odsłaniania (`_ODWROT_WERDYKTU`).

        Cel liczony OD NOWA w chwili kliknięcia, nie z chwili pokazania menu - stan mógł się zmienić.
        Bramka zajętości jak przy pozostałych gestach menu (etap albo zapis plików pisze do bazy)."""
        if self._odmowa_w_drodze():
            return
        zajety = self._powod_zajetosci()
        if zajety is not None:
            self.status_message.emit(i18n.t(zajety))
            return
        cel = self._cel_nowszych()
        if not cel:
            self.status_message.emit(i18n.t("grid.lin.reject_newer_all_none"))
            return
        wynik = repo.judge_stacks_inputs(self.con, inputs_by_master=cel, excluded=True,
                                         now=self._now())
        n = sum(len(zmiany) for _m, _iid, zmiany in wynik)
        stosy = tuple(m for m, _iid, _zmiany in wynik)
        self._zacznij_gest()
        self._migawka_werdyktu = tuple((iid, m, zmiany) for m, iid, zmiany in wynik) or None
        self._po_werdykcie(stosy, [], zmienione=bool(n))
        if not n:
            self.status_message.emit(i18n.t("grid.lin.judged_none"))
            return
        self.stan_porzadkow_changed.emit()
        self.status_message.emit(i18n.t("grid.lin.judged_excluded", n=n)
                                 + i18n.t_plural("grid.lin.judged_in_images", len(stosy))
                                 + self._czlon_bez_wejsc(stosy))
        self._ustaw_recepte_gestu(stosy, _ODWROT_WERDYKTU)

    def _ile_werdyktow_do_cofniecia(self, cel):
        """Ile zmian ostatniego werdyktu WCIĄŻ stoi w bazie (wiersz `user` z tym samym werdyktem) -
        recepta żyje, dopóki to prawda. Nowszy werdykt albo przebieg rodowodu na tych wierszach ją
        gasi: cofnięcie nadpisałoby decyzję, której ten gest nie podjął (ta sama reguła, co CAS
        klingi `restore_integration_judgment`). `cel` = klatki stosów gestu (kontrakt
        `_Odwrot.zostalo`); migawka = `((integration_id, stos, zmiany), …)` - jeden stos z panelu
        albo wszystkie obrazy gestu zbiorczego (AR-178)."""
        if self._migawka_werdyktu is None:
            return 0
        if tuple(cel) != tuple(stos for _iid, stos, _zmiany in self._migawka_werdyktu):
            return 0
        ile = 0
        for _iid, stos, zmiany in self._migawka_werdyktu:
            teraz = {r["input_frame_id"]: (r["asserted_by"], r["excluded"])
                     for r in queries.stack_lineage_inputs(self.con, stos)}
            ile += sum(1 for z in zmiany if teraz.get(z.input_frame_id) == ("user", z.excluded))
        return ile

    def _cofnij_werdykt(self):
        """Wykonawca recepty „Cofnij" po werdykcie - wiersze wracają do stanu sprzed gestu
        (`repo.restore_integration_judgments`: JEDNA transakcja dla wszystkich stosów gestu, CAS per
        wiersz; wiersz, którego przed gestem nie było, znika i odtworzy go automat). Cel nie musi być
        na ekranie (AR-178): stosy wracają do zbioru i zaznaczenia przeładowaniem (`_po_werdykcie`),
        a panel jednego stosu - z zaznaczonymi wierszami cofniętego gestu.

        MIGAWKA SCHODZI PO POWODZENIU TRANSAKCJI, nie przed nią: błąd bazy (blokada, awaria zapisu)
        wycofuje cofnięcie w całości, więc materiał i recepta zostają, a ponowienie robi to samo od
        nowa. Po powodzeniu drugi klik nie ma czego cofać."""
        migawka = self._migawka_werdyktu
        if migawka is None:
            self._zacznij_gest()
            self.status_message.emit(i18n.t("grid.lin.undo_nothing"))
            return
        try:
            n = repo.restore_integration_judgments(
                self.con, changes=[(iid, z) for iid, _stos, zmiany in migawka for z in zmiany],
                now=self._now())
        except sqlite3.Error:
            self.status_message.emit(i18n.t("grid.lin.undo_failed", undo=i18n.t("grid.lin.undo")))
            self.ponow_recepte()
            return
        self._migawka_werdyktu = None
        self._zacznij_gest()
        if n:
            self.stan_porzadkow_changed.emit()
        wiersze = [z.input_frame_id for z in migawka[0][2]] if len(migawka) == 1 else []
        self._po_werdykcie(tuple(stos for _iid, stos, _zmiany in migawka), wiersze,
                           zmienione=bool(n))
        self.status_message.emit(i18n.t("grid.lin.undone", n=n) if n
                                 else i18n.t("grid.lin.undo_nothing"))
        self._ustaw_recepte_gestu(())

    def _po_werdykcie(self, stosy, wiersze_listy, *, zmienione, nastepne=()):
        """Ogon werdyktu i jego cofnięcia: zbiór i liczniki listwy liczone OD NOWA, bo gest zmienia
        stan rodowodu stosu - kolumnę, facet „Rodowód" i perspektywę „Rodowód do potwierdzenia".
        Przy aktywnym facecie „do potwierdzenia" stos, któremu właśnie dano rodowód, ma zniknąć ze
        zbioru, a nie stać pod filtrem, któremu przeczy (ekran nie kłamie).

        CEL WRACA, JEŚLI DALEJ NALEŻY DO ZBIORU: stosy gestu idą celem (`_cel_gestu`, FC-2), a panel
        po przyłożeniu odtwarza zaznaczenie wierszy listy (wiz #8). Stos wypchnięty ze zbioru nie
        wraca, a „Cofnij werdykt" działa bez odsłaniania (AR-178) - cofnięty stos wraca tą samą
        drogą. `nastepne` - kandydaci na cel, gdy stos z perspektywy wypadł (`_nastepne_obrazy`).
        Gest bez zmiany przeładowania nie potrzebuje: panel odświeża się wprost."""
        if not zmienione:
            self._refresh_lineage(select_frame_ids=wiersze_listy)
            return
        self._cel_gestu = list(stosy)
        self._cichy_raport_gen = self._zbior_gen + 1     # generacja TEGO przeładowania
        self.refresh(w_tle=True, potem=partial(self._panel_po_werdykcie, wiersze_listy,
                                               stosy=tuple(stosy), nastepne=tuple(nastepne)))

    def _panel_po_werdykcie(self, wiersze_listy, *, stosy=(), nastepne=()):
        """Ogon przeładowania po werdykcie: zaznaczenie stosu wystartowało debounce panelu, który
        odbudowałby listę BEZ zaznaczenia wierszy - zatrzymujemy go i odświeżamy panel od razu.

        CEL NA NASTĘPNY OBRAZ (AR-178, AR-196): stos wypadł z perspektywy kolejki rodowodu,
        zaznaczenie jest puste (cel gestu nie wrócił, a w trakcie składu tabela nie przyjmuje
        klików) - pierwszy z `nastepne`, który jest w zbiorze, przejmuje zaznaczenie i panel.
        Zaznaczenia, które stoi, nie ruszamy: ogon bywa przyłożony do zbioru nowszego zlecenia."""
        self._date_timer.stop()
        widoczne = set(self._frame_ids)
        if (nastepne and self._perspektywa_kolejki_rodowodu() and not set(stosy) & widoczne
                and not self._selected_data_rows()):
            cel = next((f for f in nastepne if f in widoczne), None)
            if cel is not None:
                self._przywroc_zaznaczenie([cel])
                self._date_timer.stop()
                self._refresh_lineage()
                return
        self._refresh_lineage(select_frame_ids=wiersze_listy)

    # ---- „pokaż te klatki w Zbiorach" (dwuklik w panelu rodowodu, obie osie) ----
    def _on_lineage_frames(self, frame_ids, cel, tryb):
        """Dwuklik wiersza panelu → zbiór klatek tej listy, z dwukliknięta zaznaczoną.

        ZDANIE CHIPU NAZYWA ŹRÓDŁO, nie liczbę: „Wejścia obrazu X (190)" mówi, skąd ten zbiór się
        wziął i do czego „×" wraca. Nazwę bierzemy z zaznaczonego wiersza gridu - panel pokazuje
        materiał DOKŁADNIE JEDNEGO zaznaczonego wiersza (`_refresh_lineage`), więc to on jest
        źródłem listy. Droga idzie przez gospodarza, gdy jest (`show_frames_fn`): on zna nawigację."""
        wiersze = self._selected_data_rows()
        nazwa = _ogon_sciezki(wiersze[0].get("path")) if len(wiersze) == 1 else ""
        etykieta = i18n.t(_KLUCZE_POKAZ[tryb], name=nazwa, n=len(frame_ids))
        (self.show_frames_fn or self.show_frames)(frame_ids, label=etykieta, focus=cel)

    def show_frames(self, frame_ids, *, label, focus=None):
        """Ustaw zbiór na WSKAZANE klatki - publiczny seam dla wejść spoza listwy i perspektyw
        (dwuklik w panelu rodowodu przez most gospodarza, `MainWindow.show_frames_in_collections`).
        `frame_ids` = klatki do pokazania, `label` = zdanie chipu i paska kryteriów, `focus` =
        klatka do zaznaczenia (i przewinięcia kadru) po przyłożeniu zbioru.

        WZÓR TRIMU, NIE FILTRA: zbiór to gotowa lista `frame_id` przecinana w `_sklad_zbioru`
        (jak `_TRIMY` i tekst uwag), więc listwa liczy na tych samych klatkach co grid. Drzewo
        filtra nie umie wyrazić „te 190 klatek" bez 190 liści.

        WEJŚCIE ZASTĘPUJE ZBIÓR (jak most obiektu i Znajdź): flagi, facety, filtr i uwagi schodzą,
        a pozycja listy wraca do „Przeglądu" - przecięcie z poprzednim zbiorem dawałoby zwykle
        pustkę (perspektywa stosów nie zawiera lightów, które w nie weszły). Poprzedni stan NIE
        GINIE: „×" chipu do niego wraca (`_wroc_ze_wskazanych`), razem z zaznaczeniem - człowiek
        wraca do stosu, z którego przyszedł, jednym kliknięciem. Wejście z wejścia (dwuklik
        w panelu nad już wskazanym zbiorem) odkłada stan na stos, więc „×" cofa o jeden krok.

        Pusta lista to błąd wołającego (EXPECT): pusty trim pokazałby „nic", a pusty zbiór bez
        trimu - całe archiwum; żadne z nich nie jest tym, o co proszono."""
        ids = list(dict.fromkeys(frame_ids))
        if not ids:
            raise ValueError("show_frames: pusta lista klatek")
        self._powrot_wskazanych = self._stan_do_powrotu()
        self._zeruj_flagi()
        self._filter_tree = None
        self.filter_panel.set_tree(None)
        self.note_query = None
        self._terminy = []
        self._stan_zapytania = None
        self._facet_state = facet_model.empty_state()
        self._wskazane = (tuple(ids), label)
        self._ustaw_pozycje_listy(("preset", _PRESET_CZYSTY), PRESETS[_PRESET_CZYSTY].get("group_by"))
        self._zdejmij_wynik_gestu_zapisu()
        # Cel zaznaczenia jedzie mechanizmem celu gestu (FC-2): odkłada się na POKAZANEJ tabeli
        # z przewinięciem kadru, przy pierwszym przyłożeniu zbioru - także składanego w tle.
        self._cel_gestu = [focus] if focus in ids else []
        self.refresh(w_tle=True)

    def _stan_do_powrotu(self):
        """Stan zbioru, do którego wraca „×" chipu klatek wskazanych - KOPIA, bo stan żyje dalej."""
        return {"flagi": {atrybut: getattr(self, atrybut) for atrybut, _ in _TRIMY},
                "filtr": copy.deepcopy(self._filter_tree),
                "facety": copy.deepcopy(self._facet_state),
                "uwagi": self.note_query,
                "terminy": list(self._terminy),
                # Tożsamość zapytania Znajdź: bez niej „×" przywracał zbiór, ale już nie pytanie.
                "zapytanie": copy.deepcopy(self._stan_zapytania),
                "pozycja": self.combo_persp.currentData(),
                "grupa": self.combo_group.currentData(),
                "wskazane": self._wskazane,
                "powrot": self._powrot_wskazanych,
                "zaznaczone": [r["frame_id"] for r in self._selected_data_rows()]}

    def _wroc_ze_wskazanych(self):
        """„×" chipu klatek wskazanych: zbiór wraca do stanu sprzed wejścia, z zaznaczeniem.
        Bez zapamiętanego stanu (nie powinno się zdarzyć, ale stan bywa składany w testach ręką)
        schodzi sam składnik. Przeładowanie robi wołający (`zdejmij_skladnik`)."""
        powrot, self._powrot_wskazanych = self._powrot_wskazanych, None
        self._wskazane = None
        if powrot is None:
            return
        for atrybut, wartosc in powrot["flagi"].items():
            setattr(self, atrybut, wartosc)
        self._filter_tree = powrot["filtr"]
        self.filter_panel.set_tree(self._filter_tree)
        self._facet_state = powrot["facety"]
        self.note_query = powrot["uwagi"]
        self._terminy = powrot["terminy"]
        self._stan_zapytania = powrot["zapytanie"]
        self._wskazane = powrot["wskazane"]
        self._powrot_wskazanych = powrot["powrot"]
        self._ustaw_pozycje_listy(powrot["pozycja"], powrot["grupa"])
        self._cel_gestu = list(powrot["zaznaczone"])

    def _ustaw_pozycje_listy(self, dane, grupa):
        """Pozycja listy perspektyw i grupowanie BEZ sygnału (stan zbioru ustawia wołający). Pozycja,
        której już nie ma (perspektywę skasowano w międzyczasie), oddaje miejsce „Przeglądowi"."""
        idx = next((i for i in range(self.combo_persp.count())
                    if self.combo_persp.itemData(i) == dane), None)
        if idx is None:
            dane = ("preset", _PRESET_CZYSTY)
            idx = next(i for i in range(self.combo_persp.count())
                       if self.combo_persp.itemData(i) == dane)
        self.combo_persp.blockSignals(True)
        self.combo_persp.setCurrentIndex(idx)
        self.combo_persp.blockSignals(False)
        g = self.combo_group.findData(grupa)
        self.combo_group.blockSignals(True)
        self.combo_group.setCurrentIndex(g if g >= 0 else 0)
        self.combo_group.blockSignals(False)
        spec = self._spec_pozycji(dane)
        self._wyglad_z_perspektywy(spec if spec is not None else PRESETS[_PRESET_CZYSTY])
        self._oznacz_zmiane_perspektywy()

    def nakladka_wskazanych(self):
        """Czy zbiór to dziś klatki wskazane z panelu (`show_frames`) - nakładka nad zbiorem, do
        którego „×" wraca. Kontener Znajdź nie czyści wtedy pola zapytania: po powrocie zapytanie
        znów opisuje zbiór (`_wroc_ze_wskazanych` przywraca `_stan_zapytania`)."""
        return self._wskazane is not None

    def _zdejmij_wskazane(self):
        """Wejście, które ZASTĘPUJE zbiór (perspektywa, most, Znajdź, „× Wyczyść zbiór"), zdejmuje
        klatki wskazane razem z drogą powrotu - powrót do stanu sprzed nowego wejścia byłby
        powrotem do czegoś, czego człowiek już nie ogląda."""
        self._wskazane = None
        self._powrot_wskazanych = None

    def _describe_criteria(self):
        """Opis zbioru słowami do paska: drzewo EFEKTYWNE (facety + advanced — F4R#8, samo
        `_filter_tree` nie widzi facetów) + flagi perspektyw spoza silnika (`only_dups`/`only_review`
        - grid.py PRESETS; drzewo ich nie koduje, F4R2#7), łączone „ · ".

        OSTATNI CZŁON MÓWI, CZEGO TEN BUILD NIE ZASTOSOWAŁ (D-V-9f): perspektywa zapisana nowszym
        wydaniem może nieść warunek, którego tu nie znamy, a wtedy zbiór jest szerszy niż zapisany.
        Pytamy pozycję, która JEST na liście - dlatego `_refresh` woła ten opis PO właścicielu
        etykiety: gdy zbiór przestał być tą perspektywą, ostrzeżenie o niej też przestaje dotyczyć.

        CZŁONY ZAWĘŻENIA IDĄ PIERWSZE, „wszystkie klatki" TYLKO BEZ NICH: pasek elidował
        „wszystkie klatki · tylko duplikaty" do „wszystkie klatki…", czyli mówił odwrotność trimu.
        Kolejność: trim perspektywy, tekst uwag, potem facety i filtr (drzewo efektywne), na końcu
        ostrzeżenie. Tekst uwag stoi przed drzewem z tego samego powodu co trim: jest zawężeniem,
        więc „wszystkie klatki" przy nim byłoby nieprawdą."""
        parts = [i18n.t(_klucz_kryterium(atrybut)) for atrybut, _ in _TRIMY
                 if getattr(self, atrybut)]
        if self._wskazane is not None:
            parts.append(self._wskazane[1])
        if self.note_query is not None:
            parts.append(i18n.t("grid.criteria.notes", text=self.note_query))
        drzewo = filter_engine.describe(self._effective_tree)
        if not parts or drzewo != filter_engine.describe(None):
            parts.append(drzewo)
        data = self.combo_persp.currentData()
        spec = self._spec_pozycji(data) if data and data[0] == "saved" else None
        pominiete = _nieznane_warunki(spec) if spec is not None else []
        if pominiete:
            parts.append(i18n.t_plural("grid.criteria.unknown_keys", len(pominiete),
                                       keys=", ".join(pominiete)))
        return " · ".join(parts)

    def _zeruj_flagi(self):
        """Zdejmij WSZYSTKIE flagi perspektyw - skład z `_TRIMY`, jak każda inna enumeracja rodziny."""
        for atrybut, _ in _TRIMY:
            setattr(self, atrybut, False)

    def _zbior_zawezony(self):
        """Czy zbiór trzyma coś, co ZDEJMUJE „× Wyczyść zbiór" - facety albo filtr zaawansowany.

        JEDEN WŁAŚCICIEL TEGO PREDYKATU: karmi i uczciwy disabled przycisku, i receptę powrotu po
        geście osi (FC-2). Dwie kopie rozjechałyby się dokładnie tak, jak rozjechała się rodzina
        `only_*` - a tu cena rozjazdu jest wyższa niż wygaszony przycisk: zdanie po geście
        wskazywałoby gest, który zawężenia nie zdejmuje. Flagi perspektywy są POZA tym predykatem
        świadomie, bo ten przycisk ich nie tyka (`_on_clear_selection`). Tekst uwag jest W NIM, bo
        przycisk go zdejmuje - inaczej zbiór zawężony samymi uwagami miałby szary przycisk."""
        return (bool(self._facet_state) or self._filter_tree is not None
                or self.note_query is not None or self._wskazane is not None)

    def _trim_aktywny(self):
        """Czy trim perspektywy przycina zbiór - LICZONE W MIEJSCU UŻYCIA, nie zapamiętane (BP-4).

        Bliźniak `_zbior_zawezony` i tak samo jedyny właściciel swojego predykatu. Do tej zmiany
        odpowiadał atrybut `_trim_active` stawiany raz w `refresh()`: klasa „recepta czyta stan
        nieaktualny" była pusta wyłącznie dlatego, że KAŻDA ścieżka zmieniająca zbiór kończy się
        `refresh()` - czyli przez kolejność wywołań, bez żadnego strażnika. Pierwszy czytelnik
        spoza tej kolejności dostałby stan sprzed gestu, a recepta wskazałaby gest, który niczego
        nie odsłania.

        Zero SQL i zero kosztu: czytamy same flagi, a nie zbiory, które one wybierają."""
        return any(getattr(self, atrybut) for atrybut, _ in _TRIMY)

    # ---- reakcje ----
    def _on_filter(self, tree):
        """Jedyny odbiorca `filterApplied` panelu - „Zastosuj", Enter w polu wartości i „Wyczyść"
        panelu (także pośrednio przez `_on_clear_selection`). `set_tree` sygnału nie emituje, więc
        przełączenie perspektywy tędy nie przechodzi.

        ETYKIETA IDZIE ZA ZBIOREM (BP-5, bliźniak przez panel filtra): panelowe „Wyczyść" omija
        `_on_clear_selection`, a „Kalibracja" zostawała nad pełnym zbiorem. Rozstrzyga właściciel na
        końcu `_refresh`, jak po każdym przeładowaniu. Filtr ZMIENIONY etykiety nie rusza (żaden
        preset go nie definiuje, a właściciel nie zgaduje); przeskok następuje dopiero, gdy stan
        znów jest definicją presetu - w praktyce po zdjęciu filtra."""
        self._filter_tree = tree
        self.refresh(w_tle=True)

    def _on_columns(self, cols):
        self._columns = cols
        self.przeladuj_z_zaznaczeniem()     # kolumny ręką to widok zbioru, nie nawigacja (AR-172)

    def _perspektywa_obrazow(self):
        """Czy perspektywa jest jedną z tych, w których kolumna „Obrazy" ma treść (`_FLAGI_OBRAZOW`)."""
        return any(getattr(self, atrybut) for atrybut in _FLAGI_OBRAZOW)

    def _obrazy_widoczne(self):
        """Widoczność kolumny „Obrazy". Pierwszeństwo: gest ręki po wejściu w perspektywę >
        wybór zapisany w perspektywie (`view`, AR-36) > gest ręki sprzed wejścia > domyślna
        perspektywy. Gest po wejściu zdejmuje wybór perspektywy (`_on_images_toggled`), więc
        pierwsze dwa człony rozstrzyga już sam stan."""
        if self._obrazy_perspektywy is not None:
            return self._obrazy_perspektywy
        return self._obrazy_reka if self._obrazy_reka is not None else self._perspektywa_obrazow()

    def _on_images_toggled(self, on):
        """Ręka w „Polach" włączyła albo wyłączyła kolumnę „Obrazy" - wybór obowiązuje w KAŻDEJ
        perspektywie do końca sesji widoku (bije domyślną z `_FLAGI_OBRAZOW`). Bez przeładowania
        zbioru: zmienia się tylko widoczność kolumny, nie dane."""
        self._obrazy_reka = bool(on)
        self._obrazy_perspektywy = None    # gest po wejściu bije wybór zapisany w perspektywie
        self._uloz_kolumny()

    def _ukryj_kolumny(self):
        """Ukrycie kolumn po ZNACZENIU: schowana bywa wyłącznie „Obrazy" (`_obrazy_widoczne`).
        Liczone dla CAŁEGO układu, bo nagłówek trzyma stan ukrycia pod numerem, a po zmianie
        liczby kolumn - pod POZYCJĄ WIZUALNĄ (zmierzone: z podglądem stojącym za „Ścieżką" ukrycie
        „Obrazów" przechodziło po jego zdjęciu na pierwszy keyword). Zwraca widoczność „Obrazów".

        W prezentacji Znajdź chowane są też kolumny keywordów: model je trzyma (przełączenie
        prezentacji nie przeładowuje zbioru), a prosty zestaw kolumn ich nie pokazuje. „Obrazów"
        Znajdź w ogóle nie ma."""
        m = self.model
        obrazy = m.base_col("_images") if m.has_base_col("_images") else None
        widoczne = self._obrazy_widoczne()
        keywordy = (set(range(m.n_bazowych() + m._kw_off(), m.n_bazowych() + m._kw_off()
                              + len(m._keywords)))
                    if self.prezentacja == PREZENTACJA_ZNAJDZ else set())
        # „Gotowe obrazy": Δh (nagłówek - nazwa) jest kolumną warsztatu nazw lightów, a gotowy obraz
        # czasu w nazwie nie niesie - pusta kolumna zabierała miejsce ścieżce (wizytacja natywna).
        delta = (m.base_col("_dt_delta") if m.has_base_col("_dt_delta")
                 and self._widok_gotowych_obrazow() else None)
        # Podgląd zapisany przez commit szuflady (AR-207) stoi schowany, dopóki go ogon nie zdejmie -
        # także przez przyłożenie zbioru i sort w trakcie składu. Świeży podgląd to inny obiekt.
        zapisany = (m._preview_col() if self._podglad_po_zapisie is not None
                    and self._podglad_po_zapisie is m._preview else None)
        for c in range(m.columnCount()):
            self.table.setColumnHidden(c, (c == obrazy and not widoczne) or c in keywordy
                                       or c == delta or c == zapisany)
        return widoczne

    def _widok_gotowych_obrazow(self):
        """Czy lista perspektyw stoi na presecie „Gotowe obrazy" (wygląd kolumn tego presetu)."""
        return self.combo_persp.currentData() == ("preset", PRESET_READY_IMAGES)

    def _uloz_kolumny(self):
        """Układ kolumn tabeli po każdym `set_data` - właściciel trzech rzeczy, które Qt pamięta
        PO NUMERZE kolumny, a numer zmienia się z perspektywą (kolumna „Wersja" wchodzi przed
        keywordy):
          * ukrycie kolumny „Obrazy" (`_obrazy_widoczne`) - stan nagłówka przeżywa reset modelu
            pod starym numerem, więc liczymy go od nowa dla CAŁEGO układu, nie tylko dla jednej;
          * wskaźnik sortu nagłówka - model pamięta sort po znaczeniu (`sort_column`), a nagłówek
            po numerze; bez przestawienia strzałka stała nad cudzą kolumną. Bez sygnału, bo model
            już jest posortowany - emisja kazałaby mu przebudować się drugi raz;
          * szerokość i elizja kolumny ścieżki w perspektywach `_FLAGI_SCIEZKI_Z_TRESCI`
            (`kolumna_z_tresci`); poza nimi elizja wraca do domyślnej, a szerokość zostaje ręki.
            Zapisana perspektywa z własną szerokością (AR-36) zostaje przy niej: elizja tak,
            liczenie z treści nie - inaczej każde przeładowanie zjadałoby zapisany wybór."""
        m = self.model
        widoczne = self._ukryj_kolumny()
        self.fields.set_images_checked(widoczne)
        naglowek = self.table.horizontalHeader()
        naglowek.blockSignals(True)
        naglowek.setSortIndicator(m.sort_column(), m.sort_order())
        naglowek.blockSignals(False)
        sciezka = m.base_col("path")
        if any(getattr(self, atrybut) for atrybut in _FLAGI_SCIEZKI_Z_TRESCI):
            if self._szerokosc_sciezki is None:
                kolumna_z_tresci(self.table, sciezka)
            else:
                elizja_w_srodku(self.table, sciezka)
        elif self._widok_gotowych_obrazow():
            # Nazwy stosów różnią się KOŃCEM (filtr, wariant `_drizzle`, `_autocrop`), a elizja
            # z prawej zjadała właśnie koniec - dziesięć wierszy „NGC3034_2022…" nie do odróżnienia.
            elizja_w_srodku(self.table, sciezka)
        else:
            self.table.setItemDelegateForColumn(sciezka, None)

    def _on_group(self):
        # Grupa wersji jest pochodną liczoną w `_refresh` tylko wtedy, gdy ktoś o nią pyta
        # (`_potrzebne_wersje`) - wybór tej pozycji musi więc przeładować zbiór, inaczej każdy
        # wiersz wylądowałby w „(brak)". Pozostałe klucze model przegrupowuje sam, bez SQL.
        # Zbiór ten sam - zaznaczenie wraca po przyłożeniu (AR-172).
        if self.combo_group.currentData() == _GRUPA_WERSJI:
            self.przeladuj_z_zaznaczeniem()
            return
        self.model.set_group_by(self.combo_group.currentData())

    # ---- odczyt → widok ----
    def refresh(self, *, w_tle=False, potem=None):
        """Silnik filtra → zbiór frame_id → base_rows + pivot → model. Źródło prawdy = baza (bez
        cache między refreshami). F4: drzewo EFEKTYWNE = compose(stan facetów, drzewo panelu);
        trimy SETAMI literałowymi PRZED base_rows - JEDNA derywacja trimu dla zbioru głównego
        i sibling-setów listwy (SPOT, F4R2#2); liczniki listwy per sibling-set (F4R#1). Skład liczy
        `_sklad_zbioru` (bez widżetów), przykłada `_zastosuj_zbior`.

        DWA TRYBY, JEDEN SKŁAD (AR-27). Zmierzone 1,2-1,5 s na kopii żywej bazy (16 901 klatek) -
        przy KAŻDYM kliku facetu, perspektywy, kolumn i po każdym przebiegu Dostawy okno stało.
        `w_tle=True` (nawigacja) w widoku gospodarza oddaje skład `ZbiorWorker`-owi i wraca od razu:
        tabela trzyma zbiór poprzedni, pasek mówi „Wczytuję…", wynik przykłada `_on_zbior_done`.
        `potem` jest ogonem zlecenia (krok, który musi zobaczyć NOWY zbiór) - leci po przyłożeniu
        wyniku. Wynik zlecenia wyprzedzonego przez nowsze idzie do kosza, ale jego ogon przechodzi
        na nowsze: ogony czytają STAN widoku (perspektywa, flagi), a nie wynik, więc po przyłożeniu
        nowszego zbioru wciąż mówią prawdę - zgubiony zostawiłby perspektywę bez recepty.
        Gesty zapisu też idą `w_tle` (AR-84): kroki czytające model po odświeżeniu (zaznaczenie celu,
        liczba klatek poza widokiem, zdanie, recepta) niesie ogon `potem` (`_ogon_gestu`).
        Bez `w_tle` (porażka składu w tle, testy) i w widoku bez wątku skład idzie synchronicznie
        pod NAZWANĄ FAZĄ (F-1): wołający czyta model zaraz po powrocie, a wynik zlecenia w tle, które
        było w drodze, trafia do kosza generacją - synchroniczny skład jest od niego nowszy.

        Faza i zdanie końcowe idą kanałem `load_report`, nie `status_message`: odświeżenie bywa
        wołane, gdy Zbiorów nie widać, a o tym, czy raport ma paść teraz, wie tylko gospodarz."""
        self._zbior_gen += 1                 # PRZED fazą: `busy` doręcza kolejkę, a w niej bywa
        self._zbior_odlozony = None          # wynik zlecenia w tle - ma trafić do kosza; odłożony też
        if potem is not None:
            self._zbior_ogony.append(potem)
        if w_tle and self._zbior_async and self._db_path and not self._pola_stop:
            self.load_report.emit(i18n.t("busy.read_frames"))
            if self._zbior_worker is not None:
                # Bieg w drodze liczy stan, którego już nie ma: przerwij go, a nowy ruszy po jego
                # końcu (`_sprzataj_zbior`) na stanie z TAMTEJ chwili - przy szybkim klikaniu
                # facetów liczy się jeden bieg naraz, zawsze ostatni.
                self._zbior_ponow = True
                self._zbior_worker.request_cancel()
            else:
                self._start_zbior()
            # Akcje na CAŁYM widoku gasną do przyłożenia: tabela pokazuje zbiór poprzedni, a cel
            # (`_frame_ids`) i nazwa perspektywy w combo opisują już różne zbiory.
            self._sync_zbioru_w_drodze()
            return
        self._zbior_ponow = False
        if self._zbior_worker is not None:
            self._zbior_worker.request_cancel()   # wynik i tak do kosza - nie liczmy go do końca
        try:
            with busy.busy(self.load_report.emit, i18n.t("busy.read_frames")):
                self._refresh()
        finally:
            # Wyjątek składu nie zostawia tabeli w stanie „w drodze" (`NoSelection`, bez wyzwalaczy
            # edycji): przyłożenie, które to zdejmuje, nie doszło do skutku.
            self._sync_zbioru_w_drodze()
        # RECEPTA GESTU SKŁADA SIĘ ZE STANU PO KAŻDYM PRZEŁADOWANIU (FH-2e). Raport wczytania
        # gasi na pasku receptę (każdy raport ją gasi), więc bez tej emisji dwuczłonowa recepta
        # umierała po wykonaniu pierwszego członu - dokładnie wtedy, gdy drugi stawał się
        # wykonalny. Milczy, gdy żaden gest recepty nie zostawił.
        self.ponow_recepte()
        self._wykonaj_ogony()

    def _wykonaj_ogony(self):
        """Ogony zleceń (`refresh(potem=…)`) po przyłożeniu zbioru - w kolejności zleceń, każdy raz."""
        ogony, self._zbior_ogony = self._zbior_ogony, []
        for ogon in ogony:
            ogon()

    def _refresh(self):
        """Wykonawcza połowa `refresh` w trybie synchronicznym (fazę zakłada wołający - JEDEN jej
        właściciel): skład na połączeniu widoku i przyłożenie."""
        self._zastosuj_zbior(_sklad_zbioru(self.con, self._migawka_zbioru()))

    def _migawka_zbioru(self):
        """Stan widoku, z którego składa się zbiór - KOPIA, bo `ZbiorWorker` czyta ją w innym wątku,
        a widok w tym czasie żyje dalej. Ustawia też drzewo EFEKTYWNE (źródło paska kryteriów, F4R#8)."""
        self._effective_tree = facet_model.compose(self._facet_state, self._filter_tree)
        return {"drzewo": copy.deepcopy(self._effective_tree),
                "facety": copy.deepcopy(self._facet_state),
                "filtr": copy.deepcopy(self._filter_tree),
                "trimy": [nazwa for atrybut, nazwa in _TRIMY if getattr(self, atrybut)],
                "uwagi": self.note_query,
                "wskazane": None if self._wskazane is None else list(self._wskazane[0]),
                "wskazane_etykieta": None if self._wskazane is None else self._wskazane[1],
                "terminy": list(self._terminy),
                "kolumny": list(self._columns),
                "wersje": self._potrzebne_wersje()}

    def _zbior_w_drodze(self):
        """Czy tabela pokazuje zbiór, który zaraz zostanie zastąpiony - JEDEN predykat dla gaszenia
        akcji całego widoku, wyzwalaczy edycji i odmowy w slotach. Bieg liczący generację nieaktualną
        (wyprzedzony synchronicznym przeładowaniem) się nie liczy: jego wynik idzie do kosza."""
        return (self._zbior_ponow or self._zbior_odlozony is not None
                or (self._zbior_bieg_gen is not None and self._zbior_bieg_gen == self._zbior_gen))

    def zbior_w_drodze(self):
        """Publiczne pytanie kontenera strony (Znajdź): czy tabela pokazuje zbiór, który zaraz
        zostanie zastąpiony - zdanie o zapytaniu w toku czeka wtedy na jego przyłożenie."""
        return self._zbior_w_drodze()

    def ponow_raport_wczytania(self):
        """Podaj „Czytam klatki…" jeszcze raz, gdy zbiór jest w drodze - wejście gospodarza zaraz po
        podpięciu `load_report`: pierwsze zlecenie leci z `__init__`, zanim ktokolwiek słucha."""
        if self._zbior_w_drodze():
            self.load_report.emit(i18n.t("busy.read_frames"))

    def _odmowa_w_drodze(self):
        """Druga linia obrony slotów akcji na całym widoku (pierwsza: wygaszone przyciski)."""
        if not self._zbior_w_drodze():
            return False
        self.status_message.emit(i18n.t("grid.sel.loading_refused"))
        return True

    def _sync_zbioru_w_drodze(self):
        """Stany zależne od `_zbior_w_drodze` - po każdej jego zmianie.

        ZAZNACZENIE STOI, GDY ZBIÓR JEST W DRODZE (AR-84). Klik w tabeli zaznaczałby wiersz zbioru,
        który przyłożenie zaraz zastąpi: po nawigacji zaznaczenie i tak znika z resetem modelu, a po
        geście ogon odkłada w nim cel gestu (`_ogon_gestu`) - wybór zrobiony w tym oknie przepadłby
        bez śladu, a następny gest trafiłby w cel, którego człowiek nie wskazał. `NoSelection` trzyma
        zaznaczenie, które widać, i nie przyjmuje nowego (klik, Shift, Ctrl+A); kod stawia zaznaczenie
        dalej (`_przywroc_zaznaczenie` idzie przez model zaznaczenia, nie przez tryb widoku).
        Kursor zajętości nad tabelą mówi, że klik w tym oknie nic nie zaznaczy - bez niego klik
        przepadał bez sygnału. Panel Rodowód gaśnie tą samą drogą (`_sync_lineage_busy`)."""
        self._sync_edycji()
        self._sync_akcji_zbioru()
        self._sync_lineage_busy()
        w_drodze = self._zbior_w_drodze()
        self.table.setSelectionMode(QAbstractItemView.NoSelection if w_drodze
                                    else QAbstractItemView.ExtendedSelection)
        if w_drodze:
            self.table.viewport().setCursor(Qt.BusyCursor)
        else:
            self.table.viewport().unsetCursor()

    def _sync_akcji_zbioru(self):
        """Akcje na CAŁYM widoku (Podgląd/Do stagingu makra i renamu, „Wydaj na stół…") ze stanu:
        widoczne klatki, staging drugiej klingi, zbiór w drodze. W biegu etapu Dostawy stanem
        rządzi `set_busy` - tu nie włączamy niczego, co tamten zgasił."""
        if self._etap_w_biegu:
            return
        ma = bool(self._frame_ids)
        self.macro_bar.set_actions_enabled(ma)       # szczery disabled makra na pustym gridzie (#4)
        self.rename_bar.set_actions_enabled(ma)      # bliźniaczo dla renamu
        self.sel_bar.set_have_frames(ma)             # pusty zbiór gasi „Wydaj na stół…" (F3R#2)
        self._sync_staging_mutex()                   # staging jednej klingi wyłącza „Do stagingu" drugiej
        tip = i18n.t("grid.sel.loading_tip") if self._zbior_w_drodze() else ""
        for btn in (self.macro_bar.btn_prev, self.rename_bar.btn_prev):
            btn.setToolTip(tip)
        if tip:
            for btn in (self.macro_bar.btn_prev, self.rename_bar.btn_prev, self.sel_bar.btn_proj):
                btn.setEnabled(False)
            self.sel_bar.btn_proj.setToolTip(tip)

    def _start_zbior(self):
        self._zbior_bieg_gen = self._zbior_gen
        worker = ZbiorWorker(self._zbior_gen, self._migawka_zbioru(), self._db_path)
        worker.done.connect(self._on_zbior_done)
        worker.failed.connect(self._on_zbior_failed)
        self._zbior_worker = worker
        self._zbior_thread = QThread(self)
        worker.moveToThread(self._zbior_thread)
        self._zbior_thread.started.connect(worker.run)
        worker.finished.connect(self._zbior_thread.quit)
        self._zbior_thread.finished.connect(self._sprzataj_zbior)
        self._zbior_thread.start()

    def _sprzataj_zbior(self):
        """Koniec wątku składu. ŚWIĘTA KOLEJNOŚĆ jak w `_sprzataj_pola` (deadlock AB-BA GIL ×
        ~QThread): worker.deleteLater → wait → thread.deleteLater. Wątek zebrany już przez
        `_zatrzymaj_zbior` nie ma tu czego sprzątać."""
        if self._zbior_thread is None:
            return
        self._zbior_worker.deleteLater()
        self._zbior_thread.wait()
        self._zbior_thread.deleteLater()
        self._zbior_worker = None
        self._zbior_thread = None
        self._zbior_bieg_gen = None
        if self._zbior_ponow and not self._pola_stop:
            self._zbior_ponow = False
            self._start_zbior()              # generacja i ogon - ostatniego zlecenia
        else:
            self._sync_zbioru_w_drodze()     # bieg bez przyłożenia (wyprzedzony) - stan bez niego

    def _zatrzymaj_zbior(self):
        """Widok znika: przerwij skład i ZBIERZ wątek (wzór `zatrzymaj_pola`). Idempotentne."""
        self._zbior_ponow = False
        self._zbior_ogony = []
        self._zbior_odlozony = None
        self._zbior_bieg_gen = None
        self._zbior_gen += 1
        if self._zbior_thread is None:
            return
        self._zbior_worker.request_cancel()
        self._zbior_thread.quit()
        self._zbior_worker.deleteLater()
        while not self._zbior_thread.wait(100):
            self._zbior_worker.request_cancel()
        self._zbior_thread.deleteLater()
        self._zbior_worker = None
        self._zbior_thread = None

    @Slot(int, object)
    def _on_zbior_done(self, gen, wynik):
        if gen != self._zbior_gen:
            return                           # wyprzedzony przez nowsze zlecenie - do kosza
        self._zbior_bieg_gen = None
        if self._edytor_otwarty():
            # EDYTOR KOMÓRKI CZEKA NA CZŁOWIEKA, NIE NA WYNIK. Reset modelu domknąłby go z zapisem
            # (`_domknij_edycje`), czyli zatwierdził tekst w połowie pisania. Wynik czeka, aż edytor
            # się zamknie (`_przyloz_odlozony`); nowsze zlecenie w tym czasie wyrzuca go generacją.
            self._zbior_odlozony = (gen, wynik)
            return
        self._przyloz(wynik)

    def _przyloz(self, wynik):
        self._zastosuj_zbior(wynik)
        self.ponow_recepte()                 # jak po synchronicznym przeładowaniu (FH-2e)
        self._wykonaj_ogony()

    def _edytor_otwarty(self):
        delegat = self.table.itemDelegate()
        return isinstance(delegat, _EdycjaKomorki) and delegat.aktywny is not None

    def _przyloz_odlozony(self):
        """Edytor komórki się zamknął (zatwierdzenie, anulowanie, domknięcie przed resetem) - wynik
        odłożony przez `_on_zbior_done` trafia do widoku, o ile wciąż jest najnowszy."""
        if self._zbior_odlozony is None or self._edytor_otwarty():
            return
        (gen, wynik), self._zbior_odlozony = self._zbior_odlozony, None
        if gen != self._zbior_gen:
            self._sync_zbioru_w_drodze()
            return
        if wynik is None:                    # skład w tle padł (`_on_zbior_failed`)
            self._ponow_synchronicznie()
            return
        self._przyloz(wynik)

    def _ponow_synchronicznie(self):
        """Drugie podejście do TEGO SAMEGO zlecenia na wątku GUI (skład w tle padł). Znacznik
        przeładowania nie-nawigacyjnego przechodzi na generację ponowienia - to nie nowa przyczyna,
        więc zaznaczenie wraca jak po udanym składzie (AR-172)."""
        if self._przeladowanie_z_zaznaczeniem == self._zbior_gen:
            self._przeladowanie_z_zaznaczeniem = self._zbior_gen + 1
        self.refresh()

    @Slot(int, str)
    def _on_zbior_failed(self, gen, msg):
        """Skład w tle padł (nie przerwanie - to ma starszą generację). Drugie podejście na wątku
        GUI tą samą drogą co gesty: dane dojeżdżają, a błąd, który nie jest przypadłością wątku,
        wychodzi stamtąd tak samo jak przed AR-27 - zamiast zbioru zamrożonego bez słowa. Ogony
        czekające na ten wynik zabiera synchroniczne przeładowanie.

        PORAŻKA CZEKA NA EDYTOR JAK SUKCES (AR-83). Synchroniczne przeładowanie resetuje model, a reset
        domyka otwarty edytor komórki z zapisem (`_domknij_edycje`) - zatwierdziłby tekst w połowie
        pisania. Odłożony jest więc sam zamiar: `wynik=None` w `_zbior_odlozony` znaczy „przeładuj
        synchronicznie", a wykonuje go zamknięcie edytora (`_przyloz_odlozony`). Nowsze zlecenie
        w tym czasie wyrzuca zamiar generacją, jak odłożony wynik."""
        if gen != self._zbior_gen:
            return
        self._zbior_bieg_gen = None
        if self._edytor_otwarty():
            self._zbior_odlozony = (gen, None)
            return
        self._ponow_synchronicznie()

    def _zastosuj_zbior(self, wynik):
        """Wynik `_sklad_zbioru` → model i każda powierzchnia, która czyta zbiór (wątek GUI)."""
        # MENU TABELI OTWARTE NAD STARYM ZBIOREM ZAMYKA SIĘ PRZED RESETEM. Jego pozycje liczyły
        # stan z zaznaczenia w chwili pokazania, a przyłożenie zmienia wiersze i zaznaczenie (cel
        # gestu niżej) - klik zapisywałby na innych klatkach niż te, dla których menu otwarto.
        for menu in (*self._menu_tabeli.findChildren(QMenu), self._menu_tabeli):
            if menu.isVisible():
                menu.hide()
        # ZAZNACZENIE PRZEŻYWA PRZEŁADOWANIE NIE-NAWIGACYJNE (`przeladuj_z_zaznaczeniem`, AR-172):
        # migawka ze STAREGO modelu tuż przed resetem, o ile przykładany zbiór jest zbiorem takiego
        # zlecenia - każde inne zlecenie podbiło generację i znacznik nie pasuje (wynik przykładany
        # tu jest zawsze generacji bieżącej: `_on_zbior_done`, `_przyloz_odlozony`, skład synchroniczny).
        migawka = (self._migawka_zaznaczenia()
                   if self._przeladowanie_z_zaznaczeniem == self._zbior_gen else None)
        base, pv, keywords = wynik["base"], wynik["pivot"], wynik["keywords"]
        base_ids = wynik["base_ids"]
        self._frame_ids = base_ids     # cel makra = to, co WIDAĆ (po filtrach dups/review), doktryna §5
        self.model.set_data(base, pv, keywords, group_by=self.combo_group.currentData(),
                            version_col=self._kolumna_wersji(),
                            images_unknown=self._perspektywa_obrazow())
        self._uloz_kolumny()
        if self.model._version_col() is not None:
            # Domyślne 100 px elidowało „inna integracja · 2026-02-21 12:43 · 33 wejścia", czyli
            # właśnie te fakty, po które perspektywa istnieje. Koszt znikomy: perspektywa ma na
            # kopii żywego archiwum 40 stosów (2026-09-26).
            self.table.resizeColumnToContents(self.model._version_col())
        # CEL OSTATNIEGO GESTU WRACA RAZEM ZE ZBIOREM (FC-2, firsthand). Recepta powrotu odsłania
        # zbiór, ale sama nie ODNAJDUJE w nim celu: zmierzone na żywym archiwum - po wykonaniu
        # recepty widok miał 16 901 wierszy, zaznaczenie 0 i wygaszoną kontrolkę, więc 43 klatki
        # gestu były nie do wyłuskania. Recepta prowadziła w ślepy zaułek dokładnie tam, gdzie
        # miała pomóc. Cel odkłada się więc sam przy najbliższym przeładowaniu zbioru.
        # JEDNORAZOWO, wzorem `_reveal_facet`: stan konsumuje PIERWSZY refresh po geście, także
        # gdy niczego nie odłożył. Bez wygaszania CEL GESTU wracałby przy dowolnym późniejszym
        # odświeżeniu - czyli tam, gdzie user o niego nie prosił (granica „cel gestu przeżywa GEST,
        # nie każdy refresh", pinowana od R-S2b-3). Zaznaczenie przeżywa też przeładowanie
        # nie-nawigacyjne (wynik Pól, kolumny ręką, Dostawa - AR-164, AR-172) - ale własną migawką
        # z generacją (wyżej), nie tym celem; cel gestu konsumuje każde przyłożenie.
        # Konsumpcja TU, odłożenie niżej - PO pokazaniu tabeli (FH-11).
        cel, self._cel_gestu = self._cel_gestu, []
        n = len(set(base_ids))      # klatki, nie wiersze - ta sama oś co zaznaczone (`_update_count`)
        self._n_total = n
        self._update_count()
        if n == 0:
            # Rozróżnienie „filtr nic nie wpuścił" vs „w bazie NIC nie ma" (wiz F5 #8) - fakt
            # z tego samego składu (`baza_ma_klatki`). Wariant niepustej bazy wybiera decyzja
            # recepty powrotu (FH-4) - patrz `_ustaw_pusty_stan`.
            self._ustaw_pusty_stan(wynik["baza_ma_klatki"])
        self.empty_box.setVisible(n == 0)    # pojemnik i etykieta RAZEM: `empty.isVisible()` zostaje
        self.empty.setVisible(n == 0)        # kontraktem, a etykieta nie wisi widoczna w ukrytym pudle
        self.table.setVisible(n > 0)
        # CEL GESTU ODKŁADA SIĘ DOPIERO NA POKAZANEJ TABELI (FH-11). Odkładany przed `setVisible`
        # trafiał po recepcie z pustego widoku w tabelę UKRYTĄ, a `scrollTo` na ukrytym widoku
        # nic nie robi - zaznaczone klatki stały na dolnej krawędzi kadru albo pod nią.
        # Migawka przeładowania tą samą drogą i w tym samym miejscu. Cel gestu BIJE migawkę, gdy
        # odłożył choć jedną klatkę - to nowsza, jawna intencja (oba naraz: „Policz teraz” i koniec
        # Dostawy). CEL BEZ KLATKI W ZBIORZE USTĘPUJE ZAZNACZENIU CZŁOWIEKA: migawka zostaje CAŁA -
        # zaznaczenie, bieżąca komórka i wybór w panelu (`_przywroc_zaznaczenie` bez trafień zaznaczenia
        # nie rusza). Pusty ekran zgubiłby wybór, którego AR-172 broni, a pokazanie go zamiast
        # nieistniejącego celu nie mówi nieprawdy. Cel schodzi w obu przypadkach (konsumpcja wyżej).
        panel = {}
        if migawka is not None:
            # Wraca każde zaznaczenie, bez progu kosztu (AR-202, `_TabelaKlatek`).
            zaznaczone, biezacy, kolumna, panel = migawka
            self._przywroc_zaznaczenie(zaznaczone, biezacy=biezacy, kolumna=kolumna)
        if cel and self._przywroc_zaznaczenie(cel):
            panel = {}                       # panel opisze klatki celu, wybór z migawki ich nie dotyczy
        self.sel_bar.set_clearable(self._zbior_zawezony())
        self._zastosuj_listwe(wynik["listwa"])               # listwa (F4)
        self._sync_zbioru_w_drodze()                         # akcje całego widoku i edycja - za zbiorem
        # Odłożenie zaznaczenia ruszyło debounce panelu daty i rodowodu (`selectionChanged`), a oba
        # odświeżają się tu, od razu - debounce przebudowałby panel 150 ms później BEZ wyboru
        # z migawki (noc, relacja, wiersze listy).
        self._date_timer.stop()
        self._refresh_date_echo()                           # panel daty odbija świeże widoczne (echo warunkowe)
        self._refresh_lineage(**panel)                       # …i panel rodowodu, tak samo warunkowo
        # Przeładowanie WYWOŁANE GESTEM w panelu rodowodu milczy (`_po_werdykcie`): raport „Grid: N
        # klatek" przykrywał zdanie gestu („Odrzucono 2") razem z sensem recepty „Cofnij werdykt".
        if self._cichy_raport_gen != self._zbior_gen:
            self.load_report.emit(
                i18n.t("grid.status.loaded", frames=i18n.t_plural('grid.frames', n), cols=len(keywords)))
        # ETYKIETA PERSPEKTYWY JEST POCHODNĄ STANU (BP-5 domknięty tutaj): każda droga, która zmienia
        # zbiór, kończy się tym przeładowaniem, więc właściciel etykiety ma JEDNO miejsce wołania,
        # a nie po jednym przy każdym geście - tamte trzy przegapiły klik w listwie facetów.
        self._etykieta_perspektywy_za_stanem()
        # Kryteria zbioru SŁOWAMI (F3) - PO etykiecie, bo ostatni człon opisu pyta pozycję listy
        # perspektyw o warunki, których ten build nie zna (D-V-9f); przed rozstrzygnięciem
        # etykiety pytałby pozycję, która za chwilę przestanie być bieżąca.
        self.sel_bar.set_criteria(self._describe_criteria())
        # Chipy aktywnego stanu (Znajdź) z migawki TEGO zbioru - razem z modelem, nie ze stanu intencji.
        migawka = wynik.get("migawka") or {}
        self._skladniki_przylozone = self._skladniki_z_migawki(migawka)
        # Czy to wciąż zbiór ostatniego zapytania: stan, który ono postawiło, bez flag perspektywy.
        # Raz rozjechany zostaje rozjechany - pole zapytania zostało już wyczyszczone.
        if self._stan_zapytania is not None and (
                migawka.get("trimy") or migawka.get("wskazane") is not None
                or (migawka.get("facety") or {}) != self._stan_zapytania[0]
                or migawka.get("filtr") != self._stan_zapytania[1]
                or migawka.get("uwagi") != self._stan_zapytania[2]):
            self._stan_zapytania = None
        self._zapytanie_aktualne = self._stan_zapytania is not None
        self.stan_zbioru_zmieniony.emit()

    def _zastosuj_listwe(self, listwa):
        """Liczniki z `_liczniki_listwy` → listwa facetów, z bieżącym stanem i odsłonięciem."""
        counts, extras, aliases, alias_forms = listwa
        # `_reveal_facet` jest JEDNORAZOWY: gasimy go tu, nie u wołającego — inaczej każdy kolejny
        # refresh (klik w listwie, zmiana perspektywy) skakałby do celu sprzed pół godziny.
        reveal, self._reveal_facet = self._reveal_facet, None
        self.facet_rail.set_data(counts, self._facet_state, extras, reveal=reveal,
                                 aliases=aliases, alias_forms=alias_forms)

    def _on_facet_change(self, state):
        """Klik w listwie (cykl none→in→ex→none policzony w `facet_model.cycle`) → nowy stan →
        przeskładanie zbioru. Stan JEST własnością FramesView (widżet emituje wynik). W tle
        (AR-27): przy szybkim klikaniu liczy się tylko ostatni stan."""
        self._facet_state = state
        self.refresh(w_tle=True)

    def _on_clear_selection(self):
        """„× Wyczyść zbiór" (wiz F4 #3): zdejmij facety + filtr advanced JEDNYM klikiem. Flagi
        perspektywy (`only_dups`/`only_review`) zostają — są własnością perspektywy, nie filtra.
        `_clear` panelu emituje `filterApplied(None)` → `_on_filter` → jeden refresh.

        ETYKIETA PERSPEKTYWY IDZIE ZA ZBIOREM (BP-5): preset „Kalibracja" zawęża filtrem, więc ten
        gest zdejmuje całą jego definicję, a zapisana perspektywa traci swoje facety. Rozstrzyga
        właściciel etykiety na końcu `_refresh`, do którego ten gest dochodzi przez `_on_filter`;
        kontrakt wobec flag zostaje bez zmian, bo od niego zależy wykonalność recepty powrotu
        (`_rodzaj_recepty_powrotu`).

        Tekst uwag schodzi razem z facetami: gest zastępuje zbiór, a uwagi są jego składnikiem."""
        self._facet_state = facet_model.empty_state()
        self.note_query = None
        self._zdejmij_wskazane()    # „Wyczyść" czyści, nie wraca: powrót niesie „×" chipu
        self._terminy = []
        self.filter_panel._clear()

    def _on_selection_changed(self):
        self._update_count()
        self._date_timer.start()                             # debounced echo daty (R1 #15)

    def _update_count(self):
        """Licznik = widoczne klatki + (gdy jest) zaznaczenie: „N klatek · M zaznaczonych" (wizytator G2 —
        akcja na zaznaczeniu musi potwierdzać cel). Nagłówki grup są nieselektowalne → nie liczą się.
        Odświeża też żywą etykietę celu renamu (R1 #18): zaznaczenie-first, inaczej widoczne.
        Odmiana przez `plural` [#11]: ścieżka Duplikatów robi z n=1 przypadek TYPOWY, a „1 klatek"
        na pasku zbioru czytało się jak błąd (wiz K7 / wiz F5 #7).

        JEDEN PRZEBIEG ZAZNACZENIA NA ZDARZENIE (R-S2b-7). Do S3 ta metoda chodziła po zaznaczeniu
        DWA razy — raz po licznik (`selectedRows()`), raz po id-y (`_selected_data_rows`) — a każdy
        przebieg kosztował **1,06 s** przy pełnym zaznaczeniu 16 648 klatek. Licznik bierze się więc
        z tej samej listy wierszy, z której biorą się id-y.

        OBIE STRONY LICZĄ KLATKI: zaznaczone po `frame_id`, widoczne - `_n_total` po klatkach zbioru
        (`_zastosuj_zbior`). Kontrakt read-modelu to wiersz na klatkę (`queries.base_rows`, test
        kontraktu), ale etykieta nie stoi na nim - duplikat wiersza nie zmieni osi jednej ze stron."""
        rows = self._selected_data_rows()
        sel = len({r["frame_id"] for r in rows})    # klatki, nie wiersze (AR-187)
        txt = i18n.t_plural("grid.frames", self._n_total) + (
            f"  ·  {i18n.t_plural('grid.selected', sel)}" if sel else "")
        self.count_label.setText(txt)
        self._sync_object_actions(rows)
        if hasattr(self, "rename_bar"):
            # Etykieta celu z katalogu (AR-205: literał „Cel:” stał także w UI EN).
            self.rename_bar.set_target_label(i18n.t(
                "grid.rename.target", what=i18n.t_plural("grid.selected", sel) if sel
                else i18n.t_plural("grid.visible", self._n_total)))

    def _sync_object_actions(self, rows=None):
        """Uczciwy disabled osi obiektu — liczony z ZAZNACZENIA, nie z widocznych (§4/14c-a).

        BEZ DEBOUNCE'U, i to jest wynik POMIARU, nie zaniechanie (R-S2b-7). Znalezisko mówiło
        „read-model w gorącej pętli" i szacowało koszt na `json.dumps` 15 890 id + `json_each`
        na wątku GUI. Zmierzone przy pełnym zaznaczeniu 16 648 klatek: `selection_object_state`
        = **31 ms**, czyli 1,5% kosztu `_update_count`; całe 2 040 ms brał `selectedRows()`,
        wołany dwa razy — i to jego zdjęcie (zakresy zamiast `QModelIndex`) załatwiło pętlę,
        z 2 071 ms na **2 ms**. Debounce dołożony NA WIERZCH tej naprawy kupowałby 31 ms na
        zdarzenie, a płacił niezmiennikiem „po zmianie zaznaczenia pasek mówi prawdę": stan
        pozycji menu zależałby od timera, więc każda bramka uczciwości disabled musiałaby pompować
        pętlę zdarzeń. Zła cena za 1,5%.

        `rows` przekazuje wołający, gdy już je ma — jeden przebieg zaznaczenia na zdarzenie.
        Read-model pytamy tylko wtedy, gdy jest o co pytać: przy pustym zaznaczeniu odpowiedź jest
        znana bez SQL-a."""
        if rows is None:
            rows = self._selected_data_rows()
        ids = [r["frame_id"] for r in rows]
        stan = queries.selection_object_state(self.con, ids) if ids else None
        # „Zmień obiekt…" (AR-17 krok 3) z TYCH SAMYCH wierszy, bez drugiego zapytania: klatka
        # nieba, żywa (niewycofana, niezastąpiona) i z DOKŁADNIE jedną obecną kopią (tylko taką
        # planer przeniesie) - z obiektem albo bez, bo gest przepina każde źródło. Prezentacja, nie
        # prawda: resztę odsiewa planer z powodem, dlatego tooltip mówi „do sprawdzenia w podglądzie”.
        changeable = sum(1 for r in rows
                         if r.get("kind") in LIGHT_KINDS and r.get("n_present") == 1
                         and r.get("retired_at") is None and r.get("superseded_by") is None)
        self.sel_bar.set_object_actions(
            namable=stan["namable"] if stan else 0,
            clearable=stan["clearable"] if stan else 0,
            changeable=changeable,
            stacks=stan["stacks_touchable"] if stan else 0,
            restorable=stan["restorable"] if stan else 0,
            reason=_object_gate_reason(stan))
        # OŚ ŻYWOTNOŚCI liczy się z TYCH SAMYCH wierszy, bez drugiego zapytania: `base_rows` niesie
        # komplet (`retired_at`, `superseded_by`, `present`, `n_present`). Predykat jest lustrem
        # guardów klingi (`repo._retire_verdict`) — a rozstrzyga i tak klinga, w transakcji.
        retirable = sum(1 for r in rows
                        if r.get("retired_at") is None and r.get("superseded_by") is None
                        and r.get("present") == 0 and (r.get("n_present") or 0) == 0)
        restorable = sum(1 for r in rows if r.get("retired_at") is not None)
        alive = sum(1 for r in rows if (r.get("n_present") or 0) > 0)
        self.sel_bar.set_frame_actions(retirable=retirable, restorable=restorable,
                                       reason=_frame_gate_reason(len(rows), alive), notes=len(rows))

    # ---- oś ŻYWOTNOŚCI klatki (D-OW-3/R2) ----

    def _on_frame_retire(self):
        """„Wycofaj klatkę…": zamyka sprawę klatki, której pliku już nie ma na dysku.

        POTWIERDZENIE, w odróżnieniu od sąsiadów z osi obiektu, i to z jednego powodu: skutek tego
        gestu jest NIEWIDOCZNY NATYCHMIAST — klatka wypada z kubełków i z bieżącej perspektywy,
        więc ekran po geście nie pokazuje tego, co się właśnie stało. Okno podaje liczbę, którą
        gest realnie ruszy (tę samą, co tooltip kontrolki), zanim cokolwiek zostanie zapisane.

        Cel = ZAZNACZENIE, jak wszystkie gesty pasków w tym widoku. Klatki żywe, zastąpione
        i już wycofane odsiewa KLINGA (`repo._retire_verdict`), nie ten slot: filtr w read-modelu
        stałby POZA transakcją, więc plik, który wrócił między oknem a zapisem, przeszedłby."""
        if self._odmowa_zajetosci():
            return
        ids = self._object_gesture_ids()
        if not ids:
            return
        if QMessageBox.question(
                self, i18n.t("grid.sel.frame_retire"),
                i18n.t("grid.sel.frame_retire_ask", n=len(ids))) != QMessageBox.Yes:
            return
        gest = repo.retire_frames(self.con, frame_ids=ids, now=self._now())
        # ODWRACALNY (FH-6): „Przywróć klatkę" istnieje (`repo.restore_frames`), a klatka po geście
        # zwykle wypada z widoku - bez recepty jedyną drogą powrotu była pamięć człowieka o tym,
        # że perspektywa „Wycofane" w ogóle istnieje.
        self._po_gescie_klatki("grid.sel.frame_retired", gest, odwrot=_ODWROT_WYCOFANIA)

    def _on_frame_restore(self):
        """„Przywróć klatkę" — DROGA POWROTU z wycofania. Bez potwierdzenia, bo gest jest
        NIEDESTRUKCYJNY i odwraca cudzy skutek: pytanie o zgodę na naprawę pomyłki byłoby
        kolejną przeszkodą dokładnie tam, gdzie człowiek już raz się pomylił."""
        if self._odmowa_zajetosci():
            return
        ids = self._object_gesture_ids()
        if not ids:
            return
        gest = repo.restore_frames(self.con, frame_ids=ids, now=self._now())
        self._po_gescie_klatki("grid.sel.frame_restored", gest)

    def _po_gescie_klatki(self, klucz, gest, *, odwrot=None):
        """Ogon gestów osi żywotności: zdanie z ROZBICIEM per powód + odświeżenie + zaznaczenie.

        `odwrot` jak w `_po_gescie_osi` - recepta składa się w jednym kodzie dla obu osi (FH-6).

        Rozbicie idzie z `RetireGesture.skipped_breakdown` (JEDEN właściciel składu), nie z literału
        tutaj — ta sama lekcja, którą repo dostało już na osi obiektu: człon dołożony później
        wpadał do sumy „z M" i znikał z rozbicia, czyli z jedynego miejsca, gdzie tłumaczył.

        CZŁON „POZA WIDOKIEM" TA SAMA FUNKCJA, CO NA OSI OBIEKTU (FC-2, bramka pakietu): tutaj
        wypchnięcie celu jest wręcz REGUŁĄ, bo wycofanie zdejmuje klatkę z kubełków roboczych -
        a zdanie, które „bywa jedynym śladem", milczało o tym, gdzie te klatki się podziały."""
        zaznaczone = [r["frame_id"] for r in self._selected_data_rows()]
        self._zacznij_gest()                # recepta poprzedniego gestu przestaje obowiązywać
        # Odmiana po WSZYSTKICH klatkach gestu („z 1 klatki", „z 5 klatek").
        msg = i18n.t_plural(klucz, gest.done + gest.skipped, done=gest.done)
        for sufiks, n in gest.skipped_breakdown:
            if n:
                msg += i18n.t(f"grid.sel.frame_skip_{sufiks}", n=n)
        # ZDANIE PO ODŚWIEŻENIU I TYLKO JEDNO (`_ogon_gestu`) - repo dostało tę klasę już DWA RAZY
        # na sąsiedniej osi. Waży to tu podwójnie: po udanym wycofaniu klatka ZNIKA z perspektywy,
        # więc to zdanie bywa jedynym śladem, że gest się odbył.
        # Cel recepty = klatki realnie wycofane albo przywrócone (`gest.frame_ids`) - już wycofana
        # klatka w zaznaczeniu niesie cudzą decyzję i odwrót jej nie tyka (Z1, jak na osi obiektu).
        if gest.done:
            # Wycofanie i przywrócenie ruszają cztery liczniki Porządków naraz (wycofane,
            # „a plik wrócił", zniknięte, brakujące kopie) - plakietka ma to wiedzieć bez wejścia
            # w Porządki. `refresh_counts` nie mówi na pasek stanu.
            self.stan_porzadkow_changed.emit()
            self._przeladuj_po_gescie(msg, zaznaczone, recepta=gest.frame_ids, odwrot=odwrot,
                                      ts=queries.last_hand_ts(self.con))
            return
        self.status_message.emit(msg)
        self._ustaw_recepte_gestu(gest.frame_ids, odwrot)

    # ---- UWAGI klatki (0032) - fakt ręki, zapis wyłącznie klingą `repo` ----

    def _on_notes(self):
        """„Uwagi…" (czasownik Znajdź i pozycja menu „Klatka ▾"): cel = WYŁĄCZNIE zaznaczenie, jak
        na osiach zaznaczenia - przy setkach widocznych klatek chybione kliknięcie i zamierzony
        gest wyglądają tak samo.

        ODMOWA PRZED OKNEM, nie po nim: etap Dostawy albo zapis nagłówków pisze do tej samej bazy
        z innego połączenia (zapis uwagi czekałby na `busy_timeout`), a zbiór w drodze znaczy, że
        zaznaczenie wskazuje wiersze zbioru, który za chwilę zniknie. Okno bazy nie dotyka -
        bieżące uwagi czyta tu `queries.notes_for`, a klinga dostaje intencję. Odmowa klingi
        (`ValueError` przed zapisem: klatka zniknęła, treść za długa) wraca oknem z jej zdaniem."""
        powod = self._powod_zajetosci()
        if powod is not None:
            self.status_message.emit(i18n.t(_UWAGI_ZAJETE[powod]))
            return
        if self._odmowa_w_drodze():
            return
        ids = self._object_gesture_ids()
        if not ids:
            return
        dlg = NoteDialog(current=queries.notes_for(self.con, ids), frame_count=len(ids), parent=self)
        dlg.exec()
        if dlg.intent is None:
            return
        akcja, tresc = dlg.intent
        try:
            if akcja == "set":
                gest = repo.set_frame_note(self.con, frame_ids=ids, body=tresc, now=self._now())
            else:
                gest = repo.clear_frame_note(self.con, frame_ids=ids, now=self._now())
        except ValueError as e:
            QMessageBox.warning(self, i18n.t("grid.notes.action"), str(e))
            return
        self._po_gescie_uwag(gest, after=tresc if akcja == "set" else None)

    def _po_gescie_uwag(self, gest, *, after):
        """Ogon gestu uwag: zdanie, odświeżenie z zachowaniem zaznaczenia (wzór `_po_gescie_osi`)
        i recepta „Cofnij uwagi".

        NOŚNIK COFNIĘCIA TO MIGAWKA, NIE NAZWA METODY: recepta osi pamięta `(cel, _Odwrot)`,
        bo jej odwrót to inna pozycja menu na tych samych klatkach. Odwrotem uwag jest stan SPRZED
        gestu - inny dla każdej klatki (jedna miała „chmury", druga nic) - więc widok trzyma
        `(before, after)` z klingi obok recepty, a `_Odwrot` uwag wskazuje metody, które z niej
        czytają. Gest, który niczego nie zmienił (treść już była), recepty nie dostaje."""
        zaznaczone = [r["frame_id"] for r in self._selected_data_rows()]
        self._zacznij_gest()
        klucz = "grid.notes.set_done" if after is not None else "grid.notes.cleared_done"
        msg = i18n.t(klucz, changed=len(gest.changed),
                     total=len(gest.changed) + len(gest.unchanged))
        if gest.changed:
            self._migawka_uwag = (dict(gest.before), after)
            # Uwaga bywa składnikiem zbioru (`note_query`), więc gest potrafi wypchnąć cel z widoku
            # - ten sam pomiar i człon, co na osiach zaznaczenia, w tym samym ogonie po składzie.
            self._przeladuj_po_gescie(msg, zaznaczone, recepta=gest.changed, odwrot=_ODWROT_UWAG,
                                      ts=queries.last_hand_ts(self.con))
            return
        self.status_message.emit(msg)
        self._ustaw_recepte_gestu(())

    def _ile_uwag_do_cofniecia(self, cel):
        """Ile klatek celu niesie WCIĄŻ uwagę, którą zostawił gest - recepta żyje, dopóki to prawda.
        Późniejsza edycja tych klatek (inny tekst, zdjęcie) gasi ją: cofnięcie nadpisałoby
        decyzję, której gest nie podjął."""
        if self._migawka_uwag is None:
            return 0
        before, after = self._migawka_uwag
        biezace = queries.notes_for(self.con, list(cel))
        return sum(1 for fid in cel if fid in before and biezace.get(fid) == after)

    def _cofnij_uwagi(self):
        """Wykonawca recepty „Cofnij uwagi" - przywraca stan sprzed gestu (`repo.restore_frame_notes`)
        na klatkach, które wciąż niosą uwagę gestu; klatek zmienionych później nie tyka (ta sama
        reguła, co `_ile_uwag_do_cofniecia`). Migawka znika PRZED zapisem: drugi klik nie ma czego
        cofać, a recepta schodzi z paska po tym geście.

        Cel bez widoku (AR-195, `_ODWROT_UWAG.bez_widoku`): klatki z migawki, nie z zaznaczenia, więc
        po przeładowaniu zaznaczone jest to, co cofnięto, a człon „poza widokiem” liczy cofnięte
        klatki, których widok nie pokazuje."""
        migawka, self._migawka_uwag = self._migawka_uwag, None
        if migawka is None:
            self.status_message.emit(i18n.t("grid.notes.undo_nothing"))
            return
        before, after = migawka
        biezace = queries.notes_for(self.con, list(before))
        zywe = {fid: b for fid, b in before.items() if biezace.get(fid) == after}
        if not zywe:
            self.status_message.emit(i18n.t("grid.notes.undo_nothing"))
            self._ustaw_recepte_gestu(())
            return
        self._zacznij_gest()
        try:
            # Odczyt wyżej jest PREZENTACJĄ (zdanie „nie ma czego cofać"); prawdę rozstrzyga klinga
            # pod blokadą - `expected` zatrzymuje cofnięcie na klatce, którą w międzyczasie zmieniło
            # drugie połączenie (etap Dostawy nie pisze uwag, ale druga instancja aplikacji może).
            gest = repo.restore_frame_notes(self.con, before=zywe,
                                            expected={fid: after for fid in zywe}, now=self._now())
        except ValueError as e:
            QMessageBox.warning(self, i18n.t("grid.notes.action"), str(e))
            self._ustaw_recepte_gestu(())
            return
        msg = i18n.t("grid.notes.restored", changed=len(gest.changed))
        if gest.changed:
            self._przeladuj_po_gescie(msg, list(gest.changed), recepta=())
            return
        self.status_message.emit(msg)
        self._ustaw_recepte_gestu(())

    # ---- WERSJE STOSÓW (perspektywa „Wersje stosów") ----

    def _perspektywa_wersji(self):
        """Czy widok stoi w perspektywie „Wersje stosów" - flaga z `_TRIMY` pod stałą `_FLAGA_WERSJI`."""
        return bool(getattr(self, _FLAGA_WERSJI))

    def _potrzebne_wersje(self):
        """Czy przeładowanie ma policzyć grupy wersji - tylko gdy ktoś o nie pyta: perspektywa
        (kolumna „Wersja") albo grupowanie „Wersja stosu". Poza tym `_refresh` nie płaci za read-model
        (zmierzone 17 ms na 193 stosach żywego archiwum, przy każdym kliknięciu w listwie).
        Kolumna „Wersja" włączona w Znajdź liczy się w OBU prezentacjach: fakty muszą już być
        w wierszach, gdy człowiek wróci do Znajdź - przełączenie prezentacji nie przeładowuje zbioru."""
        return (self._perspektywa_wersji() or self.combo_group.currentData() == _GRUPA_WERSJI
                or self._wersja_w_znajdz)

    def _kolumna_wersji(self):
        """Czy model ma pokazać kolumnę „Wersja": perspektywa „Wersje stosów" albo wybór w „Kolumny ▾"
        Znajdź (AR-50 (5)) - ten drugi tylko w prezentacji, która go oferuje."""
        return self._perspektywa_wersji() or (
            self.prezentacja == PREZENTACJA_ZNAJDZ and self._wersja_w_znajdz)

    def _on_version_col(self, on):
        """„Kolumny ▾ → Wersja" w Znajdź. Przeładowanie, bo fakty grup wersji liczą się w składzie
        tylko wtedy, gdy ktoś o nie pyta (`_potrzebne_wersje`). Zbiór ten sam - zaznaczenie wraca
        po przyłożeniu (AR-172)."""
        self._wersja_w_znajdz = bool(on)
        self.przeladuj_z_zaznaczeniem()

    def _uloz_belki_i_wersje(self):
        """Układ widoku po każdym resecie modelu (sygnał `modelReset`): belki grup i kolumna „Wersja".

        BELKA GRUPY NA CAŁĄ SZEROKOŚĆ (`setSpan`) przy KAŻDYM grupowaniu: podpis belki żył
        w kolumnie „Ścieżka" i był w niej ucięty - z grupy wersji (obiekt, filtr, ekspozycja, okno
        co do sekundy) zostawało „IC1795 · Ha ·…", a z długich nazw obiektów i kluczy to samo.
        Spany są własnością WIDOKU i reset modelu ich nie zdejmuje (zmierzone: span przeżywa
        `beginResetModel`/`endResetModel` przy zmianie wierszy i liczby kolumn), więc po sorcie
        wisiałyby na cudzych wierszach, a bez grupowania na wierszach danych - stąd `clearSpans`
        przed każdym układaniem.

        „WERSJA" ZA „ŚCIEŻKĄ" przesunięciem WIZUALNYM (`moveSection`), nie nowym indeksem w modelu:
        logiczna pozycja kolumny (`_version_col`) zostaje tam, gdzie liczą ją sort, podgląd klingi
        i przesunięcie keywordów, a człowiek widzi nazwę pliku i fakty wersji obok siebie. Zmiana
        liczby kolumn kasuje przesunięcia nagłówka, więc ustawiamy je przy każdym resecie; poza
        perspektywą wracają na miejsca logiczne (nagłówek nie ma `setSectionsMovable`, więc innych
        przesunięć niż nasze nie ma).

        PODGLĄD KLINGI ZARAZ ZA „ŚCIEŻKĄ" tą samą regułą (AR-57; rename, makro, edycja komórki):
        logicznie ostatni (`_preview_col`), więc numery keywordów, ich szerokości i strzałka sortu
        nie jadą razem z nim; wizualnie bezpośredni sąsiad „Ścieżki" (przed „Wersją"), bo stara
        nazwa i nowa mają stać obok siebie. Szerokość z treści i elizja w środku
        (`kolumna_z_tresci`) - nazwa pliku ma widoczne oba końce, a w nich to, co podgląd ma
        pokazać (FLATGRP, końcowe `_`). Elizję podglądu zdejmujemy z każdej innej kolumny
        keywordów: numer podglądu wraca jako keyword, gdy „Wersja" wejdzie w trakcie podglądu
        albo gdy po jego zdjęciu ręka dołoży keyword w „Polach"."""
        t = self.table
        m = self.model
        t.clearSpans()
        if m._group_by not in (None, ""):
            n = m.columnCount()
            for i, row in enumerate(m._rows):
                if "_group" in row:
                    t.setSpan(i, 0, 1, n)
        h = t.horizontalHeader()
        wersja = m._version_col()
        podglad = m._preview_col()
        # (kolumna logiczna, pozycja wizualna) W KOLEJNOŚCI RUCHÓW: podgląd ląduje za ścieżką jako
        # drugi, więc „Wersja" zjeżdża o jeden dalej - ścieżka, nowa nazwa, wersja. „Za ścieżką"
        # liczone od JEJ numeru: w klasycznej to pozycja 1, w Znajdź ścieżka („Plik") stoi ostatnia
        # wśród bazowych, więc oba przesunięcia lądują na końcu prostego zestawu kolumn.
        za_sciezka = m.base_col("path") + 1
        docelowe = []
        if wersja is not None:
            docelowe.append((wersja, za_sciezka))
        if podglad is not None:
            docelowe.append((podglad, za_sciezka))
        if h.sectionsMoved():
            for i in range(h.count()):
                if h.visualIndex(i) != i:
                    h.moveSection(h.visualIndex(i), i)
        for k, p in docelowe:
            h.moveSection(h.visualIndex(k), p)
        # SZEROKOŚĆ IDZIE ZA ZNACZENIEM KOLUMNY, NIE ZA NUMEREM. Zmierzone: zmiana liczby kolumn
        # kasuje przesunięcia nagłówka, ale szerokości zostają na POZYCJACH WIZUALNYCH - po zdjęciu
        # podglądu stojącego po bazowych jego szerokość lądowała na pierwszym keywordzie. Migawka
        # sprzed resetu (`_zapamietaj_szerokosci`) oddaje każdej kolumnie bazowej i keywordowi
        # jej szerokość; keyword świeży dostaje domyślną. „Wersję" i podgląd ustawia treść.
        # Ukrycie najpierw, tą samą regułą (`_ukryj_kolumny`): stan „ukryta" też zostaje na pozycji
        # wizualnej, a szerokości sekcji ukrytej nie odtwarzamy (Qt trzyma ją wtedy jako 0).
        self._ukryj_kolumny()
        szerokosci, self._szerokosci_przed_resetem = self._szerokosci_przed_resetem, {}
        self._znaczenia_kolumn = [m._sort_id_for(c) for c in range(m.columnCount())]
        if szerokosci:
            for c, znaczenie in enumerate(self._znaczenia_kolumn):
                if (znaczenie is not None and znaczenie != ("version",)
                        and not h.isSectionHidden(c)):
                    t.setColumnWidth(c, szerokosci.get(znaczenie, h.defaultSectionSize()))
        # Elizja w środku należy do ścieżki (ustawia ją `_uloz_kolumny`) i do podglądu; każdy inny
        # numer, który ją niesie, dostał ją pod innym znaczeniem - numer podglądu niesie teraz
        # keyword, a po zmianie prezentacji numer ścieżki niesie „Obiekt".
        sciezka = m.base_col("path")
        for c in range(m.columnCount()):
            if (c not in (podglad, sciezka)
                    and isinstance(t.itemDelegateForColumn(c), _ElizjaWSrodku)):
                t.setItemDelegateForColumn(c, None)
        if podglad is not None:
            kolumna_z_tresci(t, podglad)

    def _zapamietaj_szerokosci(self):
        """Migawka szerokości kolumn po ZNACZENIU tuż przed resetem modelu - druga połowa reguły
        „szerokość idzie za znaczeniem" w `_uloz_belki_i_wersje`. Znaczenia bierzemy z OSTATNIEGO
        układu (`_znaczenia_kolumn`), nie z modelu: `set_data` zmienia keywordy i „Wersję" przed
        `beginResetModel`, więc model w tej chwili opisuje już układ następny.

        OSTATNIA WIDOCZNA SEKCJA POZA MIGAWKĄ: `setStretchLastSection` rozciąga ją do viewportu,
        więc jej szerokość nie jest wyborem ręki. Utrwalona, jechałaby za keywordem, który przestał
        być ostatni - seria zmian „Pól" zostawiała kilka kolumn szerokich na pół ekranu."""
        t = self.table
        h = t.horizontalHeader()
        rozciagnieta = next((h.logicalIndex(v) for v in range(h.count() - 1, -1, -1)
                             if not h.isSectionHidden(h.logicalIndex(v))), None)
        self._szerokosci_przed_resetem = {
            znaczenie: t.columnWidth(c) for c, znaczenie in enumerate(self._znaczenia_kolumn)
            if znaczenie is not None and c < h.count() and c != rozciagnieta
            and not h.isSectionHidden(c)}             # ukryta ma 0 px - to nie jest wybór ręki

    def _on_table_menu(self, pos):
        """Prawy klik na tabeli: menu z sekcją „Zostaw tę wersję" (perspektywa „Wersje stosów"),
        sekcją dróg wyjścia z izolacji zapisu w miejscu (perspektywy zapisu albo klatka z kopią
        izolowaną), gestem „Uzgodnij pliki…" (perspektywa „Plik nie zgadza się z obiektem") i gestem
        zbiorczym rodowodu (perspektywa „Rodowód z klatkami nowszymi niż obraz", AR-178).
        Żadna sekcja nie pasuje → menu się nie pokazuje i zaznaczenie zostaje.

        Wiersz pod kursorem, którego nie ma w zaznaczeniu, staje się zaznaczeniem - konwencja
        platformy, a zarazem jedyny sposób, żeby „tę" wskazywało to, na co człowiek kliknął.
        Kliknięcie W zaznaczenie zostawia je, jak jest: przy kilku zaznaczonych gest wersji odmówi
        z powodem w tooltipie pozycji, zamiast po cichu wybrać jeden z nich, a gesty zapisu
        obejmą wszystkie zaznaczone kopie izolowane (liczba stoi w tooltipie).

        Poza perspektywami menu pyta o izolację klatek, na które wskazuje klik (zaznaczenie albo
        wiersz pod kursorem), ZANIM cokolwiek zaznaczy - prawy klik na zwykłej klatce ma zostać
        niczym, a nie przestawiać zaznaczenia. Tak samo pyta, czy wskazana JEDNA klatka czeka na
        kopię wiodącą (podmenu „Ta kopia prowadzi", AR-23); w perspektywach kopii podmenu stoi
        zawsze.

        ZBIÓR W DRODZE - MENU NIE POWSTAJE (AR-84). Zaznaczenie stoi wtedy w `NoSelection`, więc
        „wiersz pod kursorem staje się zaznaczeniem" nic nie robi, a pozycje liczyłyby stan ze
        starego zaznaczenia: „Zostaw tę wersję" kopiowała do schowka ścieżki wersji, którą człowiek
        właśnie wskazał do zostawienia. Odmowa mówi to zdaniem na pasku."""
        if self._odmowa_w_drodze():
            return
        idx = self.table.indexAt(pos)
        sm = self.table.selectionModel()
        pod_kursorem = (self.model._rows[idx.row()] if idx.isValid() else None)
        poza_zaznaczeniem = (idx.isValid() and sm is not None
                             and not sm.isRowSelected(idx.row(), QModelIndex()))
        wersje = self._perspektywa_wersji()
        zapis = self._perspektywa_zapisu()
        zastapione = bool(getattr(self, _FLAGA_ZASTAPIONYCH))
        kopie = any(getattr(self, atrybut) for atrybut in _FLAGI_KOPII_WIODACEJ)
        zgodnosc = bool(getattr(self, _FLAGA_ZGODNOSCI_PLIKU))
        optyka = bool(getattr(self, _FLAGA_OPTYKI))
        nowsze = bool(getattr(self, _FLAGA_NOWSZYCH))
        if (not wersje and not zapis and not zastapione and not zgodnosc and not optyka
                and not nowsze):
            if poza_zaznaczeniem:
                wiersze = ([pod_kursorem] if isinstance(pod_kursorem, dict)
                           and "_group" not in pod_kursorem else [])
            else:
                wiersze = self._selected_data_rows()
            cel = [r["frame_id"] for r in wiersze]
            zapis = bool(queries.isolated_inplace_ops(self.con, cel))
            # Poza perspektywami kopii gest żyje nad JEDNĄ klatką z kilkoma obecnymi kopiami, która
            # czeka na decyzję (predykaty wierszy Porządków) - liczba kopii z wiersza odsiewa
            # archiwum, zanim cokolwiek zapyta bazę.
            kopie = kopie or (len(wiersze) == 1 and (wiersze[0].get("n_present") or 0) > 1
                              and lead_copy.awaiting_hand(self.con, cel[0]))
            if not zapis and not kopie:
                return
        if poza_zaznaczeniem:
            self.table.selectRow(idx.row())
        self.act_keep_version.setVisible(wersje)
        self.act_keep_all_versions.setVisible(wersje)    # `_sync_menu_wersji` wybiera jedną z dwóch
        self.act_reopen_versions.setVisible(False)
        self._sep_zapisu.setVisible(wersje and zapis)
        for act in (self.act_finish_write, self.act_restore_header, self._sep_zwolnienia,
                    self.act_release_file):
            act.setVisible(zapis)
        self._sep_przeniesienia.setVisible(zastapione and (wersje or zapis))
        self.act_transfer_facts.setVisible(zastapione)
        self._sep_kopii.setVisible(kopie and (wersje or zapis or zastapione))
        self._menu_kopii.menuAction().setVisible(kopie)
        self._sep_zgodnosci.setVisible(zgodnosc and (wersje or zapis or zastapione or kopie))
        self.act_align_files.setVisible(zgodnosc)
        self._sep_optyki.setVisible(optyka and (wersje or zapis or zastapione or kopie or zgodnosc))
        self.act_fix_optics.setVisible(optyka)
        if optyka:
            zajety = self._powod_zajetosci()
            self.act_fix_optics.setEnabled(zajety is None and bool(self._selected_data_rows()))
            self.act_fix_optics.setToolTip(i18n.t(zajety) if zajety is not None
                                           else i18n.t("grid.optics.fix_tip"))
        self._sep_nowszych.setVisible(
            nowsze and (wersje or zapis or zastapione or kopie or zgodnosc or optyka))
        self.act_reject_newer_all.setVisible(nowsze)
        if nowsze:
            self._sync_menu_nowszych()
        if zgodnosc:
            self._sync_menu_zgodnosci()
        if kopie:
            self._sync_menu_kopii()
        if wersje:
            self._sync_menu_wersji()
        if zapis:
            self._sync_menu_zapisu()
        if zastapione:
            zajety = self._powod_zajetosci()
            self.act_transfer_facts.setEnabled(zajety is None)
            self.act_transfer_facts.setToolTip(
                i18n.t(zajety) if zajety is not None else i18n.t("supersede.transfer.action_tip"))
        # `popup`, nie `exec`: menu nie trzyma własnej pętli zdarzeń, a wybór i tak dochodzi
        # sygnałem `triggered`. Blokujący `exec` zawiesza każdy przebieg bez człowieka przy myszy.
        self._menu_tabeli.popup(self.table.viewport().mapToGlobal(pos))

    def _on_transfer_facts(self):
        """„Przenieś fakty ręki na następczynię" (AR-41): cel = zaznaczenie perspektywy
        „Zastąpione". Zapis klingą `repo.transfer_human_facts` przez `supersede.transfer_gesture`;
        zdanie mówi każdą oś, która przeszła, i werdykt obiektu zatrzymany na zastąpionej
        (`object_kept`). Bramka zajętości jak przy gestach izolacji - etap mógł ruszyć między
        menu a kliknięciem."""
        if self._odmowa_w_drodze():                      # zaznaczenie zbioru, który zaraz zniknie
            return
        zajety = self._powod_zajetosci()
        if zajety is not None:
            self.status_message.emit(i18n.t(zajety))
            return
        ids = [r["frame_id"] for r in self._selected_data_rows()]
        if not ids:
            return
        try:
            g = supersede.transfer_gesture(self.con, frame_ids=ids, now=self._now())
        except Exception as e:
            # Klatki przed błędem SĄ zapisane (klinga per klatka) - widok, osie i plakietka idą
            # za raportem częściowym, zanim cokolwiek powiemy albo puścimy wyjątek dalej.
            czesc = getattr(e, "przeniesienie", None)
            if czesc is not None:
                self._po_przeniesieniu(czesc, ids)
            if isinstance(e, ValueError):        # błąd klingi - okno, jak gesty osi obiektu
                QMessageBox.warning(self, i18n.t("supersede.transfer.action"),
                                    i18n.t("supersede.transfer.interrupted", err=str(e)))
                return
            raise                                # EXPECT (np. nieznany powód klingi)
        self._po_przeniesieniu(g, ids)

    def _po_przeniesieniu(self, g, ids):
        """Ogon gestu przeniesienia: odświeżenie ZAWSZE (klatka, której ogniwo zgasł skan,
        wypada z perspektywy także przy zerze przeniesień), sygnały osi, które gest ruszył
        (obiekt i zestaw mieszkają w przeglądzie obiektów, stanowisko w osi obserwatorium),
        plakietka i JEDNO zdanie po odświeżeniu (lekcja `_po_gescie_klatki`) - zaznaczenie i zdanie
        w ogonie po składzie w tle (`_ogon_gestu`, AR-84), sygnały przed zleceniem składu."""
        if g.object_moved or g.config_moved:
            self.object_axis_changed.emit()
        if g.observatory_moved:
            self.observatory_axis_changed.emit()
        self.stan_porzadkow_changed.emit()
        self._przeladuj_po_gescie(supersede.zdanie_przeniesienia(g), ids, poza=False)

    # ---- KOPIA WIODĄCA (AR-4, AR-23): „Ta kopia prowadzi" ----
    # Gdy obecne kopie klatki mówią różnie albo klatka mówi głosem kopii, której już nie ma, kopię
    # wiodącą wskazuje człowiek. Gest woła rdzeń `lead_copy` (przejęcie zeznania klingą
    # `repo.adopt_testimony` z aktorem `user:local` + pochodne) wątkiem tła przez uchwyt `self._wb`:
    # nagłówek kopii bywa na udziale SMB, a uchwyt niesie mutex „zapis → Dostawa".

    def _cel_kopii_wiodacej(self):
        """Klatka gestu z ZAZNACZENIA, liczona od nowa - `(frame_id, None)` albo `(None, klucz
        powodu)`. Jedna klatka naraz: kopię wskazuje się dla konkretnej klatki, a gest na kilku
        byłby kilkoma decyzjami pod jedną pozycją menu. Klatka, która nie czeka na decyzję (stan
        zmienił się od odświeżenia), gestu nie dostaje - jego robotą są wiersze Porządków."""
        wiersze = self._selected_data_rows()
        if len(wiersze) != 1:
            return None, "grid.lead.select_one"
        fid = wiersze[0]["frame_id"]
        if not lead_copy.awaiting_hand(self.con, fid):
            return None, "grid.lead.not_waiting"
        return fid, None

    def _sync_menu_kopii(self):
        """Pozycje podmenu „Ta kopia prowadzi" ze stanu z chwili pokazania: jedna pozycja na OBECNĄ
        kopię (pełna ścieżka - kopie jednej klatki zwykle mają tę samą nazwę pliku w różnych
        katalogach), dopisek „mówi teraz" przy kopii, której głosem mówi klatka („zgodna
        z zeznaniem", gdy takich kopii jest kilka), znacznik i zaznaczenie kopii wskazanej ręką
        (`LeadChoice.reka`) i pola rozjazdu w podpowiedzi (`queries.copy_divergence`, ten sam
        właściciel co podpowiedź „×N").
        Kopia, która już mówi, zostaje klikalna: kopie zgodne w ośmiu polach zeznania mogą różnić
        się resztą nagłówka, a wybór jednej z nich jest dalej decyzją człowieka.
        Zajętość albo złe zaznaczenie gasi całe podmenu z powodem w podpowiedzi."""
        self._menu_kopii.clear()
        akcja = self._menu_kopii.menuAction()
        fid, powod = self._cel_kopii_wiodacej()
        powod = self._powod_zajetosci() or powod
        akcja.setEnabled(powod is None)
        akcja.setToolTip(i18n.t(powod) if powod is not None else i18n.t("grid.lead.menu_tip"))
        if powod is not None:
            return
        kopie = lead_copy.lead_copy_choices(self.con, fid)
        # „Mówi teraz" jest prawdą o jednej kopii; gdy zgodnych z zeznaniem jest kilka, głos klatki
        # nie wskazuje żadnej z nich - dopisek mówi wtedy „zgodna", a wybór ręki niesie znacznik.
        zgodne = sum(k.mowi for k in kopie)
        for k in kopie:
            tekst = k.path
            if k.reka:
                tekst += i18n.t("grid.lead.hand")
            if k.mowi:
                tekst += i18n.t("grid.lead.speaks" if zgodne == 1 else "grid.lead.agrees")
            elif not k.fakty:
                tekst += i18n.t("grid.lead.unread")
            act = self._menu_kopii.addAction(tekst)
            # Pozycje checkable, zaznaczona kopia wskazana ręką - wybór trwa po zamknięciu menu
            # i widać go przy następnym otwarciu, nie tylko w zdaniu po geście.
            act.setCheckable(True)
            act.setChecked(k.reka)
            tip = i18n.t(("grid.lead.speaks_tip" if zgodne == 1 else "grid.lead.agrees_tip")
                         if k.mowi else "grid.lead.choice_tip")
            if k.reka:
                tip = i18n.t("grid.lead.hand_tip", lead=i18n.t("grid.lead.menu")) + "\n" + tip
            if k.rozne:
                pola = [_pole_rozjazdu(e, k.fakty_kopii) for e in k.rozne]
                tip += i18n.t("grid.tip.copy_diff", fields=", ".join(pola))
            act.setToolTip(tip)
            # Lambda z wartością domyślną: `triggered` niesie `checked: bool`, a pętla wiąże
            # `location_id` tej pozycji, nie ostatniej.
            act.triggered.connect(lambda _=False, lid=k.location_id: self._on_lead_copy(lid))

    def _on_lead_copy(self, location_id):
        """„Ta kopia prowadzi" na kopii `location_id`: bramka zajętości i celu PONOWNIE (druga linia
        za wygaszeniem - etap mógł ruszyć między menu a kliknięciem), potem wątek tła. Bez
        potwierdzenia: gest niczego nie rusza na dysku, a przy kopii, która mówiła wcześniej,
        drogą powrotu jest ten sam gest na niej (zdanie po geście ją nazywa)."""
        if self._odmowa_w_drodze():                      # zaznaczenie zbioru, który zaraz zniknie
            return
        zajety = self._powod_zajetosci()
        if zajety is not None:
            self.status_message.emit(i18n.t(zajety))
            return
        fid, powod = self._cel_kopii_wiodacej()
        if powod is not None:
            self.status_message.emit(i18n.t(powod))
            return
        # Para (lokacja, klatka): klinga odmówi (`raced`), gdy skan przepiął lokację na inną klatkę
        # między menu a zapisem - ręka nie zapisze się na klatce, której człowiek nie wskazał.
        self._odpal_gest_plikowy("lead_copy", (location_id, fid), [fid], self._after_lead_copy)

    @Slot(str, object)
    def _after_lead_copy(self, op, res):
        """Ogon gestu na wątku głównym - wspólny z gestami izolacji (`_po_gescie_zapisu`: odświeżenie
        z celem w zaznaczeniu, szuflada, plakietka Porządków, JEDNO zdanie po odświeżeniu). Po
        przejęciu osie obiektu i stanowiska dostają sygnał: pochodne przeliczone z nowego zeznania
        mogły zmienić obiekt, zestaw i stanowisko klatki. Odmowa z błędem systemu klasą niesie surowy
        tekst systemu w podpowiedzi szuflady (AR-184), zdanie mówi klasę w języku UI."""
        self.drawer.end_progress()
        if self._undo_mode is not None:
            self.drawer.set_commit_actions_visible(False)
        if res.verdict == "adopted":
            self.object_axis_changed.emit()
            self.observatory_axis_changed.emit()
        zdanie, podpowiedz = _zdanie_kopii_wiodacej(res)
        self._po_gescie_zapisu(zdanie, self._cel_gestu_zapisu, podpowiedz)

    def _sync_menu_wersji(self):
        """Uczciwy disabled gestu „Zostaw tę wersję" - z planu liczonego w chwili pokazania menu.

        Pozycja żyje wyłącznie wtedy, gdy jest co skopiować: dokładnie jeden zaznaczony stos, który
        ma w grupie co najmniej jedną wersję z dowodem odrębności względem siebie. Tooltip mówi, ile
        ścieżek pójdzie do schowka - tę samą liczbę, którą potwierdzi pasek po geście - albo
        dlaczego nie ma czego kopiować. Grupa z werdyktem „zostawiam wszystkie" gasi ten gest: ścieżki
        „do usunięcia" przeczyłyby werdyktowi, a drogą jest najpierw go cofnąć.

        Gesty werdyktu pytają o zajętość jak gesty izolacji (`_powod_zajetosci`): etap Dostawy albo
        zapis nagłówków przestawia klucze grup w połowie zbioru, więc grupa liczona w ich trakcie
        bywa przejściowa, a werdykt o niej byłby werdyktem o grupie, której człowiek nie widział."""
        wiersze = self._selected_data_rows()
        zajety = self._powod_zajetosci()
        plan = (queries.keep_version_plan(self.con, wiersze[0]["frame_id"])
                if len(wiersze) == 1 and zajety is None else None)
        if len(wiersze) != 1:
            self.act_keep_version.setEnabled(False)
            self.act_keep_version.setToolTip(i18n.t("grid.version.select_one"))
        elif zajety is not None:
            # Ścieżki „do usunięcia” z grupy przejściowej (etap albo zapis w biegu) byłyby
            # podpowiedzią skasowania na niepełnym obrazie grupy - ta sama bramka co werdykt.
            self.act_keep_version.setEnabled(False)
            self.act_keep_version.setToolTip(i18n.t(zajety))
        elif plan and plan["kept"]:
            self.act_keep_version.setEnabled(False)
            self.act_keep_version.setToolTip(self._zdanie_blokady_werdyktem())
        elif not plan or not plan["paths"]:
            self.act_keep_version.setEnabled(False)
            self.act_keep_version.setToolTip(i18n.t("grid.version.nothing"))
        else:
            self.act_keep_version.setEnabled(True)
            self.act_keep_version.setToolTip(
                i18n.t_plural("grid.version.keep_tip", len(plan["paths"])))
        # Werdykt grupy: jedna z dwóch pozycji, zależnie od stanu grupy zaznaczenia.
        grupa, powod = self._grupa_werdyktu()
        kept = grupa is not None and grupa["kept"]
        self.act_keep_all_versions.setVisible(not kept)
        self.act_reopen_versions.setVisible(kept)
        akcja = self.act_reopen_versions if kept else self.act_keep_all_versions
        akcja.setEnabled(grupa is not None and zajety is None)
        if zajety is not None or grupa is None:
            akcja.setToolTip(i18n.t(zajety or powod))
        elif kept:
            akcja.setToolTip(i18n.t_plural("grid.version.reopen_tip", len(grupa["frame_ids"])))
        else:
            akcja.setToolTip(i18n.t_plural("grid.version.keep_all_tip", len(grupa["frame_ids"])))

    def _grupa_werdyktu(self):
        """Grupa wersji, której dotyczy werdykt „zostawiam wszystkie" - z ZAZNACZENIA, liczona od nowa
        (`queries.stack_version_group_of`): `(grupa, None)` albo `(None, klucz powodu)`. Zaznaczenie
        może objąć jeden stos albo kilka, ale z jednej grupy - werdykt jest o grupie, a gest na dwóch
        grupach naraz byłby dwoma werdyktami pod jedną nazwą."""
        wiersze = self._selected_data_rows()
        if not wiersze:
            return None, "grid.version.select_group"
        grupa = queries.stack_version_group_of(self.con, wiersze[0]["frame_id"])
        if grupa is None:
            return None, "grid.version.no_group"
        if any(r["frame_id"] not in grupa["frame_ids"] for r in wiersze):
            return None, "grid.version.select_group"
        return grupa, None

    def _on_keep_all_versions(self):
        """„Zostaw wszystkie wersje": werdykt człowieka, że grupa zostaje w całości (AR-10, 0026).
        Grupa znika z roboty Porządków (plakietka), zostaje w perspektywie - wyciszona, z werdyktem
        w kolumnie „Wersja" i drogą powrotu w tym samym menu. Bez potwierdzenia: gest niczego nie
        rusza na dysku, a cofnięcie jest jednym kliknięciem."""
        self._po_werdykcie_wersji(keep=True)

    def _on_reopen_versions(self):
        """„Cofnij »zostaw wszystkie«" - droga powrotu werdyktu: grupa wraca do roboty."""
        self._po_werdykcie_wersji(keep=False)

    def _po_werdykcie_wersji(self, *, keep):
        """Wspólny ogon obu gestów werdyktu: grupa od nowa (między menu a kliknięciem mógł przejść
        skan), zapis klingą, odświeżenie z zachowaniem zaznaczenia, plakietka Porządków przez
        `stan_porzadkow_changed` (jedyny właściciel tej emisji) i JEDNO zdanie po odświeżeniu
        (`refresh()` mówi własnym zdaniem, wcześniejsze by przepadło - lekcja `_po_gescie_klatki`).

        Bramka zajętości to druga linia za wygaszeniem pozycji: etap mógł ruszyć między pokazaniem
        menu a kliknięciem. Zero
        ruszonych klatek ma własne zdanie: werdykt zapisał albo cofnął w międzyczasie ktoś inny,
        więc „Zapisano"/„Cofnięto" byłoby nieprawdą o tym geście."""
        if self._odmowa_w_drodze():                      # zaznaczenie zbioru, który zaraz zniknie
            return
        zajety = self._powod_zajetosci()
        if zajety is not None:
            self.status_message.emit(i18n.t(zajety))
            return
        grupa, powod = self._grupa_werdyktu()
        if grupa is None:
            self.status_message.emit(i18n.t(powod))
            return
        if keep:
            n = repo.keep_stack_versions(self.con, frame_ids=grupa["frame_ids"],
                                         group_key=grupa["group_id"], now=self._now())
        else:
            n = repo.reopen_stack_versions(self.con, frame_ids=grupa["frame_ids"], now=self._now())
        if not n:
            self.status_message.emit(i18n.t("grid.version.kept_none" if keep
                                            else "grid.version.reopened_none"))
            return
        zaznaczone = [r["frame_id"] for r in self._selected_data_rows()]
        klucz = "grid.version.kept_done" if keep else "grid.version.reopened_done"
        self.stan_porzadkow_changed.emit()
        self._przeladuj_po_gescie(i18n.t_plural(klucz, len(grupa["frame_ids"])), zaznaczone,
                                  poza=False)

    def _zdanie_blokady_werdyktem(self):
        """Powód wygaszenia „Zostaw tę wersję" w grupie z werdyktem - z nazwą drogi wyjścia."""
        return i18n.t("grid.version.keep_blocked_kept", reopen=i18n.t("grid.version.reopen"))

    def _on_keep_version(self):
        """„Zostaw tę wersję": ścieżki obecnych kopii POZOSTAŁYCH wersji grupy idą do schowka,
        a pasek mówi, ile ich skopiowano. BEZ ZAPISU - Horreum niczego nie kasuje ani nie przenosi:
        usuwa człowiek, poza programem, a skan po usunięciu zdejmie grupę z tej listy (predykat
        wymaga obecnej kopii). Dlatego gest nie woła `stan_porzadkow_changed`: stan bazy się nie
        zmienił.

        Plan liczony OD NOWA w chwili gestu, nie wzięty z menu - między pokazaniem a kliknięciem
        mógł przejść skan. Do schowka trafiają wyłącznie stosy z DOWODEM odrębności względem
        zostawianego (`queries.keep_version_plan`); pochodne tej wersji i członkowie bez dowodu
        zostają, a zdanie liczy tych drugich, żeby cisza schowka o nich nie udawała, że ich nie ma.
        Separator `\\n` - Qt zamienia go w schowku Windows na CRLF."""
        if self._odmowa_w_drodze():                      # druga linia za menu (`_on_table_menu`)
            return
        wiersze = self._selected_data_rows()
        if len(wiersze) != 1:
            self.status_message.emit(i18n.t("grid.version.select_one"))
            return
        zajety = self._powod_zajetosci()
        if zajety is not None:
            self.status_message.emit(i18n.t(zajety))
            return
        plan = queries.keep_version_plan(self.con, wiersze[0]["frame_id"])
        if plan and plan["kept"]:
            self.status_message.emit(self._zdanie_blokady_werdyktem())
            return
        if not plan or not plan["paths"]:
            self.status_message.emit(i18n.t("grid.version.nothing"))
            return
        QGuiApplication.clipboard().setText("\n".join(plan["paths"]))
        msg = (i18n.t_plural("grid.version.copied", len(plan["paths"]))
               + i18n.t_plural("grid.version.copied_stacks", plan["stacks"]))
        if plan["unknown"]:
            msg += i18n.t_plural("grid.version.skipped_unknown", plan["unknown"])
        self.status_message.emit(msg + i18n.t("grid.version.no_delete"))

    # ---- IZOLACJA ZAPISU W MIEJSCU: drogi wyjścia z GUI (warunek wsadu AR-17 (1)(2)) ----
    # Kopia z operacją zapisu w fazie izolującej (`repo.INPLACE_ISOLATING_PHASES`) jest pomijana
    # przez skan i przez każdą inną mutację pliku. Rdzeń ma trzy drogi wyjścia; tu dostają gesty:
    # „Dokończ zapis" (`writeback.finish_inplace`), „Przywróć nagłówek sprzed zapisu"
    # (`writeback.recover_torn`) i „Zwolnij plik do skanu…" (`writeback.release_isolation`).
    # Wszystkie trzy biorą blokadę pliku, więc idą wątkiem tła przez TEN SAM uchwyt co commit makra
    # (`self._wb`) - a z nim dziedziczą mutex „writeback → Dostawa" i „jeden zapis naraz"
    # (`busy_changed` → gospodarz). Zwolnienie nie pisze pliku, ale zdejmuje izolację, więc czeka
    # na blokadę jak pozostałe: bez niej drugi proces w trakcie zapisu zostawiłby skanowi rozdarty
    # nagłówek.

    def _perspektywa_zapisu(self):
        """Czy widok stoi w jednej z dwóch perspektyw izolacji zapisu (flagi z `_TRIMY`)."""
        return any(getattr(self, atrybut) for atrybut in _RECEPTY_ZAPISU)

    def _operacje_gestu(self):
        """Operacje izolujące kopie ZAZNACZONYCH klatek - liczone od nowa (menu i gest pytają w swojej
        chwili; między nimi mógł przejść inny zapis). Cel to wyłącznie zaznaczenie, jak na osiach."""
        return queries.isolated_inplace_ops(
            self.con, [r["frame_id"] for r in self._selected_data_rows()])

    def _powod_zajetosci(self):
        """Klucz powodu, dla którego gest izolacji nie może ruszyć teraz, albo `None`. Etap Dostawy
        pisze do bazy w tle, a zapis z tego widoku albo z okna naprawy trzyma pliki - odzysk czy
        dokończenie w środku byłyby drugim pisarzem obok nich."""
        if self._etap_w_biegu:
            return "grid.inplace.busy_stage"
        if self._wb.is_busy or self._foreign_wb:
            return "grid.inplace.busy_write"
        return None

    def _sync_menu_zapisu(self):
        """Uczciwy disabled trzech gestów izolacji - ze stanu liczonego w chwili pokazania menu.

        Każda pozycja mówi w tooltipie, ile kopii ruszy, albo DLACZEGO nie ruszy żadnej: zajętość
        (etap, inny zapis), brak kopii izolowanej w zaznaczeniu, faza, w której gest nie ma sensu
        („Dokończ" wyłącznie przy zapisie, który czeka na dokończenie - przerwany zapis nie ma czego
        dokańczać). „Przywróć" i „Zwolnij" żyją przy każdej fazie izolującej: przy zapisie
        czekającym na dokończenie powrót rozstrzyga rdzeń kontrolą danych i odmawia z powodem, gdy
        zapis jest poprawny - tooltip mówi o tym z góry."""
        ops = self._operacje_gestu()
        akcje = (self.act_finish_write, self.act_restore_header, self.act_release_file)
        powod = self._powod_zajetosci() or (None if ops else "grid.inplace.none")
        if powod is not None:
            for act in akcje:
                act.setEnabled(False)
                act.setToolTip(i18n.t(powod))
            return
        do_dokonczenia = [o for o in ops if o["phase"] in queries.INPLACE_PENDING_FINISH_PHASES]
        wiele = _kopie_wielokrotne(ops)
        self.act_finish_write.setEnabled(bool(do_dokonczenia))
        self.act_finish_write.setToolTip(
            i18n.t_plural("grid.inplace.finish_tip", len(do_dokonczenia))
            + i18n.t("grid.inplace.finish_tip_else", restore=i18n.t("grid.inplace.restore"),
                     release=i18n.t("grid.inplace.release"))
            + _zdanie_kopii_wielokrotnych(_kopie_wielokrotne(do_dokonczenia)) if do_dokonczenia
            else i18n.t("grid.inplace.finish_open_only", restore=i18n.t("grid.inplace.restore")))
        tip = i18n.t_plural("grid.inplace.restore_tip", len(ops))
        if do_dokonczenia:
            tip += i18n.t("grid.inplace.restore_tip_written", finish=i18n.t("grid.inplace.finish"))
        self.act_restore_header.setEnabled(True)
        self.act_restore_header.setToolTip(tip + _zdanie_kopii_wielokrotnych(wiele))
        self.act_release_file.setEnabled(True)
        self.act_release_file.setToolTip(i18n.t_plural("grid.inplace.release_tip", len(ops))
                                         + _zdanie_kopii_wielokrotnych(wiele))

    def _on_finish_write(self):
        """„Dokończ zapis": kontrola danych i re-sync operacji `written` zaznaczonych kopii."""
        ops = [o for o in self._operacje_gestu()
               if o["phase"] in queries.INPLACE_PENDING_FINISH_PHASES]
        self._start_gestu_zapisu("finish_inplace", ops, pusty=i18n.t(
            "grid.inplace.finish_open_only", restore=i18n.t("grid.inplace.restore")))

    def _on_restore_header(self):
        """„Przywróć nagłówek sprzed zapisu": odzysk operacji otwartej albo droga powrotu z fazy
        czekającej na dokończenie - rozstrzyga rdzeń pod blokadą pliku (`writeback.recover_torn`)."""
        self._start_gestu_zapisu("recover_torn", self._operacje_gestu(),
                                 pusty=i18n.t("grid.inplace.none"))

    def _start_gestu_zapisu(self, op, ops, *, pusty, uzasadnienie=None):
        """Wspólny start trzech gestów plikowych: bramka zajętości i pustego celu (druga linia za
        wygaszeniem - bramka woła slot, nie pozycję menu), potem wątek tła `self._wb`. Cel klatek
        zapamiętany TU, nie w ogonie: w trakcie biegu człowiek może zmienić zaznaczenie.
        `uzasadnienie` = powód człowieka przy zwolnieniu - jedzie do rdzenia razem z operacjami."""
        if self._odmowa_w_drodze():                      # zaznaczenie zbioru, który zaraz zniknie
            return
        powod = self._powod_zajetosci()
        if powod is not None:
            self.status_message.emit(i18n.t(powod))
            return
        if not ops:
            self.status_message.emit(pusty)
            return
        cel = [o["op_id"] for o in ops]
        if uzasadnienie is not None:
            cel = {"ops": cel, "reason": uzasadnienie}
        self._odpal_gest_plikowy(op, cel, sorted({o["frame_id"] for o in ops}),
                                 self._after_gestu_zapisu)

    def _odpal_gest_plikowy(self, op, cel, frame_ids, after_slot):
        """Ostatni krok startu gestu plikowego spoza stagingu (gesty izolacji, „Ta kopia prowadzi"):
        klatki celu i zdanie szuflady sprzed gestu zapamiętane dla ogona `_po_gescie_zapisu`, potem
        wątek tła `self._wb`. Zdanie RAZEM ze szczegółem (AR-204): zmiana perspektywy oddaje szufladzie
        oba - sam tekst zostawiał np. „1 błąd” bez pliku i powodu systemu pod kursorem."""
        self._cel_gestu_zapisu = frame_ids
        # Zdanie sprzed PIERWSZEGO gestu serii: drugi gest z rzędu nie ma wracać do wyniku pierwszego.
        teraz = self._para_szuflady()
        przed = (self._wynik_gestu_zapisu[0] if self._wynik_gestu_zapisu is not None
                 and teraz == self._wynik_gestu_zapisu[1] else teraz)
        self._wynik_gestu_zapisu = (przed, None)
        self._start_writeback(op, cel, after_slot)

    def _para_szuflady(self):
        """`(zdanie, szczegół)` wyniku szuflady - jednostka pamięci i porównania wyniku gestu."""
        return self.drawer.result.text(), self.drawer.result.szczegol()

    def _oznacz_wynik_gestu_zapisu(self):
        """Znacznik wyniku gestu spoza stagingu = para, którą szuflada pokazuje po jego końcu - po
        sukcesie (`_po_gescie_zapisu`) i po awarii całej operacji (`_on_wb_failed`). Bez znacznika
        zmiana perspektywy nie oddawała zdania sprzed gestu, a pamięć i tak schodziła."""
        przed = self._wynik_gestu_zapisu[0] if self._wynik_gestu_zapisu is not None else ("", "")
        self._wynik_gestu_zapisu = (przed, self._para_szuflady())

    @Slot(str, object)
    def _after_gestu_zapisu(self, op, res):
        """Ogon gestu plikowego na wątku głównym: szuflada wraca ze stanu postępu (bez zdejmowania
        „Cofnij" poprzedniego commitu), zdanie wyniku idzie do szuflady i na pasek."""
        self.drawer.end_progress()
        if self._undo_mode is not None:
            self.drawer.set_commit_actions_visible(False)
        self._po_gescie_zapisu(_zdanie_gestu_zapisu(op, res), self._cel_gestu_zapisu,
                               _podpowiedz_gestu_zapisu(op, res))

    def _on_release_file(self):
        """„Zwolnij plik do skanu…": jawne zwolnienie izolacji RĘKĄ (`writeback.release_isolation`).

        To jest rozstrzygnięcie człowieka, że plik jest w porządku (np. przywrócony z pełnej
        kopii), więc okno żąda powodu - bez niego przycisk jest wygaszony - a powód idzie do
        zdarzenia `location.writeback_released`. Plik nietknięty. Rdzeń zwalnia pod blokadą pliku
        z fazą czytaną pod nią, więc idzie wątkiem tła jak dwa pozostałe gesty. Operacja, która
        przestała izolować między menu a gestem (inny proces ją domknął), wraca jako zablokowana
        z powodem rdzenia - reszta idzie dalej."""
        if self._odmowa_w_drodze():                      # zaznaczenie zbioru, który zaraz zniknie
            return
        powod = self._powod_zajetosci()
        if powod is not None:
            self.status_message.emit(i18n.t(powod))
            return
        ops = self._operacje_gestu()
        if not ops:
            self.status_message.emit(i18n.t("grid.inplace.none"))
            return
        dlg = ReleaseDialog(len(ops), parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._start_gestu_zapisu("release_inplace", ops, pusty=i18n.t("grid.inplace.none"),
                                 uzasadnienie=dlg.reason())

    def _po_gescie_zapisu(self, msg, cel, szczegol=""):
        """Wspólny ogon trzech gestów izolacji: odświeżenie zbioru z celem w zaznaczeniu, człon
        „poza widokiem" (w perspektywach zapisu udany gest WYPYCHA klatkę - to jest jego skutek),
        szuflada, plakietka Porządków i JEDNO zdanie po odświeżeniu (`refresh()` kończy własnym
        zdaniem, które zjadłoby wcześniejsze - lekcja `_po_gescie_osi`). Plakietka zawsze: gest
        rozstrzyga rdzeń, a porażka w połowie też mogła zmienić fazę. `szczegol` - surowy tekst
        systemu powodów zdania, pod kursorem szuflady (AR-204).

        Szuflada nie czyta zbioru - dostaje wynik od razu; zaznaczenie, człon, zdanie i recepta idą
        ogonem po składzie w tle (`_ogon_gestu`, AR-84)."""
        self._zacznij_gest()                # recepta poprzedniego gestu przestaje obowiązywać
        self._refresh_drawer()
        self.drawer.set_result(msg)
        self._podpowiedz_wyniku(szczegol)
        self._oznacz_wynik_gestu_zapisu()
        self.stan_porzadkow_changed.emit()
        self._przeladuj_po_gescie(msg, cel, recepta=cel, ts=queries.last_hand_ts(self.con),
                                  szczegol=szczegol)    # szczegół także w podpowiedzi paska (AR-218)

    def _zdejmij_wynik_gestu_zapisu(self):
        """Zmiana perspektywy zdejmuje z szuflady wynik gestu izolacji (AR-30 (5)) i oddaje jej zdanie
        sprzed gestu ze szczegółem (np. „Zatwierdzono…" przy żywym „Cofnij", AR-204). Tylko gdy
        szuflada wciąż pokazuje ten wynik (parę zdanie + szczegół) - zdanie wpisane później przez commit
        albo cofnięcie zostaje."""
        stan, self._wynik_gestu_zapisu = self._wynik_gestu_zapisu, None
        if stan is not None and stan[1] is not None and self._para_szuflady() == stan[1]:
            self.drawer.result.ustaw(*stan[0])

    # ---- panel inspekcji daty (G1/G4 — RenameBar) ----
    def _selected_data_rows(self):
        """Wiersze-klatki (bez markerów grup) dla zaznaczenia. Puste zaznaczenie → [].

        Z ZAKRESÓW zaznaczenia, nie z `selectedRows()` (R-S2b-7). `QItemSelectionRange.indexes()`
        woła `model.flags()` dla KAŻDEJ komórki zakresu i buduje `QModelIndex` per wiersz —
        zmierzone **1,06 s** na 16 648 zaznaczonych klatkach, czyli ta sama klasa kosztu, którą
        `b5d1b5c` zdjęło z przeładowania tabeli. Zakresy niosą samą geometrię (O(zakresów)),
        a jedyne, czego ta metoda potrzebuje, to NUMERY wierszy.

        Filtr `"_group" not in row` zostaje jedynym sitem i to on odtwarza kontrakt starej wersji:
        `indexes()` odsiewał nagłówki grup przez `ItemIsSelectable`, zakres ich nie odsieje, bo nie
        pyta modelu o flagi. Zakresy potrafią się nakładać (kontrakt Qt), więc numery deduplikujemy
        — inaczej klatka wpadłaby do zapisu dwa razy.

        KOLEJNOŚĆ ZMIENIA SIĘ ŚWIADOMIE: `selectedRows()` oddawał wiersze w kolejności KLIKANIA,
        ta droga — w kolejności w tabeli. Sprawdzone na parytecie (zbiór identyczny w każdym
        przypadku, także przy zakresach nakładających się i przy grupowaniu) oraz u wszystkich
        pięciu wołających: każdy bierze zbiór albo długość, żaden nie stoi na kolejności kliknięć.
        Porządek wierszowy jest przy tym DETERMINISTYCZNY, a tamten zależał od tego, jak user
        klikał."""
        sm = self.table.selectionModel()
        if sm is None:
            return []
        numery = set()
        for zakres in sm.selection():
            numery.update(range(zakres.top(), zakres.bottom() + 1))
        out = []
        for i in sorted(numery):
            row = self.model._rows[i]
            if isinstance(row, dict) and "_group" not in row:
                out.append(row)
        return out

    def _refresh_date_echo(self):
        """Odśwież panel daty RenameBar z zaznaczenia (albo widocznych, gdy puste). G1 ŚWIADOMIE
        WARUNKOWE (R1 #17): przy ZAMKNIĘTYM panelu echo zaznaczenia niesie już licznik G2 — pełne
        echo daty wymaga otwartego panelu renamu (przepływ renamu i tak dzieje się przy otwartym;
        `_toggle_panel` woła echo PO pokazaniu strony — F3R#4)."""
        if not self._rename_panel_open():
            return
        scope = self._selected_data_rows() or self.model._data_rows
        if len(scope) == 1:
            r = scope[0]
            h = naming.header_dt(r.get("date_obs"))
            fn = naming.filename_dt(os.path.basename(r["path"])) if r.get("path") else None
            primary = (i18n.t("grid.echo.dateobs", ts=f"{h:%Y-%m-%d %H:%M:%S}") if h
                       else i18n.t("grid.echo.dateobs_none"))
            secondary = (i18n.t("grid.echo.fname_time", ts=f"{fn:%Y-%m-%d %H:%M:%S}") if fn
                         else i18n.t("grid.echo.fname_none"))
            d = r.get("_dt_delta")
            if d is None:
                self.rename_bar.set_echo(primary, secondary, i18n.t("grid.echo.delta_none"),
                                         i18n.t("grid.echo.no_time_src"), flag_role="secondary")
            else:
                flag = i18n.t("grid.echo.delta_subhour") if abs(d - round(d)) > 1e-9 else ""
                self.rename_bar.set_echo(primary, secondary, i18n.t("grid.echo.delta", d=f"{d:g}"), flag)
            return
        # wsad (>1): mediana Δ + rozrzut (1 interakcja/wsad, §5b briefu-matki) + align
        deltas = [r["_dt_delta"] for r in scope if r.get("_dt_delta") is not None]
        primary = i18n.t("grid.echo.batch", n=len(scope), both=len(deltas))
        if deltas:
            med = statistics.median(deltas)
            spread = max(deltas) - min(deltas)
            self.rename_bar.set_echo(primary,
                                     i18n.t("grid.echo.batch_stats", med=f"{med:g}", spread=f"{spread:g}"),
                                     "", "", median=med, spread=spread)
        else:
            # Brak Δ to brak DRUGIEGO źródła do porównania, nie brak czasu: nazwy składają się
            # z DATE-OBS bez nazwy-świadka (pliki NINA). „Brak źródła czasu" tylko, gdy żadna
            # klatka wsadu nie ma czasu ani w nagłówku, ani w nazwie.
            ma_czas = any(naming.header_dt(r.get("date_obs")) or (
                r.get("path") and naming.filename_dt(os.path.basename(r["path"]))) for r in scope)
            self.rename_bar.set_echo(
                primary, i18n.t("grid.echo.no_delta_batch" if ma_czas else "grid.echo.no_time_batch"),
                "", "")

    def set_busy(self, busy):
        """Podczas etapu pipeline'u wyłącz akcje ZAPISU grida (makro/rename/staging/commit/undo) — worker
        pisze do bazy w tle (wizytator C1). Po etapie przywróć SZCZERE stany (paski wg widocznych klatek,
        commit/odrzuć wg liczby oczekujących AKTYWNEJ klingi); nie tykamy etykiet/widoczności szuflady (D2).
        Gesty izolacji zapisu w miejscu nie mają stałej kontrolki - stan menu liczy się przy jego
        pokazaniu, więc zapamiętujemy sam fakt biegu (`_powod_zajetosci`)."""
        self._etap_w_biegu = bool(busy)
        self._sync_edycji()                              # edycja komórek gaśnie razem z akcjami zapisu
        if self._okno_zmiany_obiektu is not None:        # okno modalne - poza akcjami widoku
            self._okno_zmiany_obiektu.set_pipeline_busy(busy)
        if busy:
            self.macro_bar.set_actions_enabled(False)
            self.rename_bar.set_actions_enabled(False)
            self.sel_bar.btn_proj.setEnabled(False)      # „Wydaj" gaśnie w biegu etapu (F3R#7)
            # „Wydaj obiekt…" czyta `calibration` i rodowód, które etap Dostawy właśnie przepisuje -
            # plan policzony w środku przebiegu wydałby mastery sprzed i po przeliczeniu naraz.
            self.sel_bar.btn_obj.setEnabled(False)
            self.drawer.btn_commit.setEnabled(False)
            self.drawer.btn_reject.setEnabled(False)
            # Panel „Rodowód" to CZWARTA powierzchnia zapisu (I-2d) i pisze do tego samego stołu,
            # który worker właśnie przelicza — bez tej linii werdykt ręki wchodził w środek etapu.
            self._sync_lineage_busy()
            if hasattr(self, "_undo_btn"):
                self._undo_btn.setEnabled(False)
        else:
            n = self._active_pending_count()             # mode-aware (R1 #2): makro LUB rename
            self.drawer.btn_commit.setEnabled(n > 0)
            self.drawer.btn_reject.setEnabled(n > 0)
            self._sync_lineage_busy()                    # panel wraca, o ile nie trwa zapis plików
            self.sel_bar.btn_obj.setEnabled(True)        # nie zależy od zbioru - wraca od razu
            if hasattr(self, "_undo_btn"):
                self._undo_btn.setEnabled(True)
            self._sync_akcji_zbioru()                    # paski i „Wydaj" wg widocznych - i zbioru w drodze

    def set_writeback_busy(self, busy):
        """DRUGA powierzchnia writebacku (dialog „Napraw nagłówek…") pisze do plików — wygaś
        Zatwierdź/Odrzuć/Cofnij (D-PD-3). To NIE to samo co `set_busy`: tam pisze pipeline do BAZY
        i gasną wszystkie akcje zapisu; tu chodzi o jeden zasób — mutację plików pod jedną
        transakcją. Własny bieg gridu tej ścieżki nie używa (jego akcje są wtedy schowane paskiem
        postępu), więc flaga mówi wyłącznie o CUDZEJ operacji."""
        self._foreign_wb = busy
        self._sync_edycji()                              # cudzy zapis plików - bez edycji komórek
        self._sync_lineage_busy()                        # …i bez gestów panelu Rodowód
        if busy:
            self.drawer.btn_commit.setEnabled(False)
            self.drawer.btn_reject.setEnabled(False)
            if hasattr(self, "_undo_btn"):
                self._undo_btn.setEnabled(False)
        else:
            if hasattr(self, "_undo_btn"):
                self._undo_btn.setEnabled(True)
            self._refresh_drawer()                       # szczere stany wg oczekujących AKTYWNEJ klingi

    # ---- makro / staging (KROK 4, druga klinga) ----
    def _targets_fn(self, frame_ids):
        return queries.writeback_frame_targets(self.con, frame_ids)

    def _cards_fn(self, frame_id):
        return queries.frame_cards(self.con, frame_id)

    def _run(self, md, run_id=None):
        """Uruchom makro nad widocznymi frame_ids (czysty silnik + wstrzyknięte akcesory). Błąd
        DEFINICJI makra (składnia/węzeł) → komunikat, None."""
        try:
            return macro_mod.run_macro(md, self._frame_ids, targets_fn=self._targets_fn,
                                       cards_fn=self._cards_fn, run_id=run_id)
        except (macro_mod.expr.ExprError, ValueError) as exc:
            # Błąd DEFINICJI makra → sprzężenie w szufladzie + status (bez modalu - doktryna §5, #3).
            # Powód z kodem (`expr_*`, `macro_def_*`, AR-194) mówi w języku UI; szczegółu systemu
            # nie niesie (tekst `SyntaxError` stoi w zdaniu), więc podpowiedź zostaje zdaniem.
            from horreum.gui.wb_worker import tekst_powodu
            from horreum.item_reasons import powod_wyjatku
            zdanie = i18n.t("grid.macro.error", exc=tekst_powodu(powod_wyjatku(exc)))
            self.drawer.set_count(self._pending_count(), result=zdanie)
            self.status_message.emit(zdanie)
            return None

    def _show_preview(self, run):
        """Wrzuć podgląd makra do modelu (stara→nowa / pominięto) i zwróć (touched, skipped).
        Grid kluczuje FRAME, a touched niesie location_id → mapuj przez `location.frame_id`."""
        self._note_preview_takeover("macro")
        preview = {}
        for pv in run.touched:
            fid = self._frame_for_location(pv.location_id)
            if fid is not None:
                preview[fid] = {"keyword": pv.keyword, "old": pv.old_value, "new": pv.new_value,
                                "op": pv.op}
        for sk in run.skipped:
            preview[sk.frame_id] = {"skipped": sk.reason}
        self.model.set_preview(preview)
        self._pokaz_kolumne_podgladu()
        return len(run.touched), len(run.skipped)

    def _pokaz_kolumne_podgladu(self):
        """Kadr na parę „Ścieżka" + podgląd klingi (stoją obok siebie, `_uloz_belki_i_wersje`).
        Obie w kadrze - nic nie ruszamy. Inaczej przewijamy w poziomie tak, by „Ścieżka" była lewą
        krawędzią: przewinięcie do samego podglądu wypychało z kadru starą nazwę, czyli połowę
        porównania. Wiersz na górze widoku zostaje."""
        t, m = self.table, self.model
        podglad = m._preview_col()
        if podglad is None or not m.rowCount():
            return
        sciezka = m.base_col("path")
        szer = t.viewport().width()
        if all(0 <= t.columnViewportPosition(c)
               and t.columnViewportPosition(c) + t.columnWidth(c) <= szer
               for c in (sciezka, podglad)):
            return
        t.scrollTo(m.index(max(t.rowAt(0), 0), sciezka))

    def _frame_for_location(self, location_id):
        return queries.frame_for_location(self.con, location_id)

    def _on_macro_preview(self, md):
        if self._odmowa_w_drodze():                      # cel = widoczne, a widać zbiór poprzedni
            return
        if not self._frame_ids:
            self.status_message.emit(i18n.t("grid.macro.no_frames_count"))
            return
        run = self._run(md)
        if run is None:
            return
        t, s = self._show_preview(run)
        self.status_message.emit(i18n.t("grid.macro.preview_result", t=t, s=s))

    def _on_macro_stage(self, md):
        if self._odmowa_w_drodze():
            return
        if not self._frame_ids:
            self.status_message.emit(i18n.t("grid.macro.no_frames"))
            return
        if self._rename_pending_count() > 0:             # mutex symetryczny: staging renamu w toku
            self.status_message.emit(i18n.t("grid.macro.staging_busy"))
            return
        czeka = self._komorki_w_szufladzie()
        if czeka:                                        # re-stage niżej czyści cały przebieg (AR-61)
            self.status_message.emit(i18n.t_plural("grid.cell.macro_blocked", czeka))
            return
        self._dismiss_undo()                             # nowy staging unieważnia leftover „Cofnij" (wiz #3)
        if self._run_id is None:
            self._run_id = uuid.uuid4().hex
        repo.clear_pending_for_run(self.con, self._run_id)   # idempotentny re-stage (R#5)
        run = self._run(md, run_id=self._run_id)
        if run is None:
            return
        for p in run.touched:
            repo.stage_pending(
                self.con, run_id=self._run_id, location_id=p.location_id, keyword=p.keyword,
                idx=p.idx, op=p.op, old_value=p.old_value, new_value=p.new_value,
                new_type=p.new_type, new_comment=p.comment,
                expected_header_hash=p.expected_header_hash)
        self._show_preview(run)
        self._refresh_drawer()
        self.status_message.emit(i18n.t_plural("grid.macro.staged", len(run.touched), s=len(run.skipped)))

    def _komorki_w_szufladzie(self):
        """Ile edycji komórek (AR-61) czeka w szufladzie BIEŻĄCEGO przebiegu makra - ze stanu
        stagingu, nie z pamięci: commit (także przerwany anulowaniem) i „Odrzuć" zmieniają status albo
        kasują wiersze, a pamięć `_komorki` zna tylko klucze. Inny przebieg = zero (commit albo
        odrzucenie zamknęło ten, pod którym edytowano)."""
        if self._run_id is None or self._komorki_run != self._run_id or not self._komorki:
            return 0
        return sum(1 for r in writeback.pending_for_run(self.con, self._run_id)
                   if r["status"] == "pending" and (r["location_id"], r["keyword"]) in self._komorki)

    def _sync_edycji(self):
        """Wyzwalacze edycji komórek wg zajętości (etap Dostawy, cudzy zapis plików): zajęty widok nie
        otwiera edytora, a model nie zgłasza komórek jako edytowalnych (wzorzec `set_busy` osi
        w `app.py`). Edytor otwarty PRZED zajętością odbije bramka w `_on_cell_edit`.

        Zbiór w drodze (AR-27) też zamyka NOWE edycje: wiersz pod kursorem za chwilę zniknie albo
        zmieni miejsce. Edytor otwarty wcześniej pisze dalej - wynik czeka na jego zamknięcie
        (`_on_zbior_done`), a zatwierdzenie idzie po stabilnym celu delegata, nie przez `flags`."""
        wolny = not self._etap_w_biegu and not self._foreign_wb and not self._zbior_w_drodze()
        self.model.set_editable(wolny)
        self.table.setEditTriggers(self._edit_triggers if wolny
                                   else QAbstractItemView.NoEditTriggers)

    def _podglad_ze_stagingu(self):
        """Podgląd klingi makra liczony z oczekujących wpisów przebiegu `_run_id`: frame_id →
        `{"cards": [{keyword, old, new, op, comment}, …]}` w kolejności stagingu - wszystkie karty
        klatki, które commit zapisze, razem z komentarzem, który zapis wniesie (`None` = zastany
        zostaje). Klatkę pod lokacją daje JEDNO zapytanie (`queries.pending_cards_for_run`)."""
        podglad = {}
        if self._run_id is None:
            return podglad
        for w in queries.pending_cards_for_run(self.con, self._run_id):
            podglad.setdefault(w["frame_id"], {"cards": []})["cards"].append(
                {"keyword": w["keyword"], "old": w["old_value"], "new": w["new_value"],
                 "op": w["op"], "comment": w["new_comment"]})
        return podglad

    def _podglad_nazw_ze_stagingu(self):
        """Podgląd klingi nazw z oczekujących wpisów przebiegu `_rename_run_id` - bliźniak
        `_podglad_ze_stagingu`, kształt `_show_rename_preview` (nazwa stara → nowa). Klatkę pod
        lokacją daje JEDNO zapytanie (`queries.pending_renames_for_run`)."""
        if self._rename_run_id is None:
            return {}
        return {w["frame_id"]: {"op": "rename", "old": os.path.basename(w["old_path"]),
                                "new": os.path.basename(w["new_path"])}
                for w in queries.pending_renames_for_run(self.con, self._rename_run_id)}

    def _domknij_edycje(self, podglad):
        """Domknij otwarty edytor komórki z zapisem do szuflady (AR-61) - przed resetem modelu
        (`podglad="pozniej"`), przed przełączeniem prezentacji (`"teraz"`: podgląd pada od razu, żeby
        żaden reset nie przyszedł po odtworzeniu zaznaczenia) i zanim widok zniknie (`"bez"`:
        zamknięcie okna, przełączenie bazy - połączenie jeszcze otwarte, podglądu nie ma już komu
        pokazać). Odmowę (zajętość, bramka
        karty) mówi `_on_cell_edit` na pasku - wpis nie ginie po cichu."""
        delegat = self.table.itemDelegate()
        if not isinstance(delegat, _EdycjaKomorki) or delegat.aktywny is None:
            return
        self._podglad_edycji = podglad
        try:
            delegat.domknij()
        finally:
            self._podglad_edycji = "teraz"
        if podglad != "bez":
            QTimer.singleShot(0, self._przyloz_odlozony)   # domknięcie nie emituje `closeEditor`

    def _podglad_po_domknieciu(self):
        """Podgląd stagingu po edycji domkniętej w resecie - już poza resetem."""
        if self._preview_owner in (None, "macro") and self._run_id is not None:
            self._note_preview_takeover("macro")
            self.model.set_preview(self._podglad_ze_stagingu())

    def _on_cell_edit(self, frame_id, keyword, text, comment):
        """Edycja JEDNEJ komórki keyworda → szuflada (AR-61). Te same bramki i ta sama klinga co makro:
        `macro.plan_manual_change` (cel kopii + reguły karty) → `repo.stage_pending_replacing` pod
        przebiegiem `_run_id`. Commit, „Odrzuć" i „Cofnij" są więc wspólne z makrem, a cel cofnięcia
        łapie `_install_undo` w chwili commitu (`_undo_commit_id`) - edycja nie zakłada trzeciego trybu.

        Odmowa (zajętość, staging nazw, bramka celu albo karty) mówi powód na pasku i niczego nie
        zapisuje. Druga edycja tej samej karty ZASTĘPUJE pierwszą (także wpis makra tej karty).
        Edytor otwarty przed składem w tle zatwierdza w jego trakcie - żeton (`_podbij_zeton`)
        chroni to zdanie przed ogonem starszego gestu."""
        self._podbij_zeton()
        zajety = self._powod_zajetosci()
        if zajety is not None:
            self.status_message.emit(i18n.t(zajety))
            return
        if self._rename_pending_count() > 0:             # staging na wyłączność (R2 #8)
            self.status_message.emit(i18n.t("grid.cell.staging_busy"))
            return
        pv, powod = macro_mod.plan_manual_change(
            queries.writeback_frame_targets(self.con, [frame_id]), keyword, text,
            cards_fn=lambda lid: queries.location_cards(self.con, lid), comment=comment)
        if pv is None:
            from horreum.gui.wb_worker import tekst_powodu   # reguła karty w języku UI (AR-167)
            self.status_message.emit(i18n.t("grid.cell.refused", kw=keyword,
                                            reason=tekst_powodu(powod)))
            return
        self._dismiss_undo()                             # nowy staging unieważnia leftover „Cofnij"
        if self._run_id is None:
            self._run_id = uuid.uuid4().hex
        if self._komorki_run != self._run_id:
            self._komorki_run, self._komorki = self._run_id, set()
        _id, zastapione = repo.stage_pending_replacing(self.con, run_id=self._run_id, preview=pv)
        self._komorki.add((pv.location_id, pv.keyword))
        # Podgląd z BIEŻĄCEGO STAGINGU przebiegu, nie ze sklejanego słownika: klatka bywa celem kilku
        # kart naraz (dwie edycje różnych keywordów, makro i edycja innej karty), a podgląd ma
        # pokazać dokładnie to, co zapisze commit. Podgląd innej klingi przejmuje z komunikatem.
        if self._podglad_edycji == "teraz":
            self._note_preview_takeover("macro")
            self.model.set_preview(self._podglad_ze_stagingu())
        elif self._podglad_edycji == "pozniej":
            # W środku resetu modelu drugi reset (podgląd) byłby zagnieżdżony - odkładamy go.
            QTimer.singleShot(0, self._podglad_po_domknieciu)
        self._refresh_drawer()
        self.status_message.emit(i18n.t(
            "grid.cell.staged_replaced" if zastapione else "grid.cell.staged", kw=keyword,
            old="∅" if pv.old_value is None else pv.old_value, new=pv.new_value))

    def _on_fix_optics(self):
        """„Popraw f/ w plikach…" (AR-129): zaznaczone klatki perspektywy „f/ niezgodna z teleskopem"
        dostają w szufladzie wpis `FOCRATIO` = f/ teleskopu ich zestawu (ręka, potem pliki). Każdy
        wpis idzie TĄ SAMĄ drogą co edycja komórki (`macro.plan_manual_change` →
        `repo.stage_pending_replacing`, bramki celu i karty), więc zapis, „Odrzuć" i „Cofnij" są
        wspólne z makrem. Plik zmienia się dopiero po „Zapisz" w szufladzie - na życzenie.
        Odmowy (RAW, kilka kopii, brak f/ teleskopu) liczą się w zdaniu, nie giną."""
        if self._odmowa_w_drodze():                      # zaznaczenie zbioru, który zaraz zniknie
            return
        zajety = self._powod_zajetosci()
        if zajety is not None:
            self.status_message.emit(i18n.t(zajety))
            return
        if self._rename_pending_count() > 0:             # staging na wyłączność (R2 #8)
            self.status_message.emit(i18n.t("grid.cell.staging_busy"))
            return
        ids = [r["frame_id"] for r in self._selected_data_rows()]
        if not ids:
            return
        wstawione, odmowy = 0, {}
        for fid, wartosc, odmowa, teleskop in queries.optics_fix_targets(self.con, ids):
            if wartosc is None:
                # strażnik większości i brak celu (N1b) - powód z katalogu, policzony (N15)
                powod = i18n.t(f"grid.optics.refused.{odmowa}", telescope=teleskop)
                odmowy[powod] = odmowy.get(powod, 0) + 1
                continue
            pv, powod = macro_mod.plan_manual_change(
                queries.writeback_frame_targets(self.con, [fid]), "FOCRATIO", f"{wartosc:g}",
                cards_fn=lambda lid: queries.location_cards(self.con, lid))
            if pv is None:
                from horreum.gui.wb_worker import tekst_powodu   # w języku UI (AR-167)
                powod = tekst_powodu(powod)
                odmowy[powod] = odmowy.get(powod, 0) + 1
                continue
            if not wstawione:
                # „Cofnij" poprzedniego zapisu znika dopiero, gdy do szuflady COŚ wchodzi (N15)
                self._dismiss_undo()
                if self._run_id is None:
                    self._run_id = uuid.uuid4().hex
                if self._komorki_run != self._run_id:
                    self._komorki_run, self._komorki = self._run_id, set()
            repo.stage_pending_replacing(self.con, run_id=self._run_id, preview=pv)
            self._komorki.add((pv.location_id, pv.keyword))
            wstawione += 1
        if wstawione:
            self._note_preview_takeover("macro")
            self.model.set_preview(self._podglad_ze_stagingu())
            self._refresh_drawer()
        zdanie = i18n.t_plural("grid.optics.staged", wstawione)
        if odmowy:
            zdanie += i18n.t("grid.optics.skipped", reasons="; ".join(
                f"{p} ({n})" for p, n in sorted(odmowy.items(), key=lambda pn: -pn[1])))
        self.status_message.emit(zdanie)

    def _on_macro_clear(self):
        self.model.set_preview({})
        self._preview_owner = None
        self.status_message.emit(i18n.t("grid.macro.preview_cleared"))

    def _pending_count(self):
        if self._run_id is None:
            return 0
        return sum(1 for r in writeback.pending_for_run(self.con, self._run_id)
                   if r["status"] == "pending")

    def _rename_pending_count(self):
        if self._rename_run_id is None:
            return 0
        return sum(1 for r in writeback.renames_for_run(self.con, self._rename_run_id)
                   if r["status"] == "pending")

    def _active_pending_count(self):
        """Oczekujące AKTYWNEJ klingi. Staging jest MUTEX — najwyżej jedna niepusta, więc `or` wybiera ją."""
        return self._pending_count() or self._rename_pending_count()

    def _sync_staging_mutex(self):
        """Staging na WYŁĄCZNOŚĆ: „Do stagingu" jednej klingi disabled+tooltip, gdy druga ma pending
        (R2 #8 — stan widoczny BEZ klikania). AUTORYTATYWNY nad `btn_stage`: gdy druga klinga zwolni
        staging, re-enable wg widocznych klatek (inaczej przycisk zostałby wyszarzony). Wołane po każdej
        zmianie stagingu i w refresh() (po `set_actions_enabled`)."""
        macro_n, rename_n = self._pending_count(), self._rename_pending_count()
        # Zbiór w drodze (AR-27) gasi „Do stagingu" także tu: tę metodę woła też szuflada
        # (`_refresh_drawer`, np. po edycji komórki), więc bez tego włączałaby przycisk w trakcie.
        w_drodze = self._zbior_w_drodze()
        has_frames = bool(self._frame_ids) and not w_drodze
        tip_wolny = i18n.t("grid.sel.loading_tip") if w_drodze else ""
        if macro_n > 0:
            self.rename_bar.btn_stage.setEnabled(False)
            self.rename_bar.btn_stage.setToolTip(i18n.t_plural("grid.macro.staging_busy_tip", macro_n))
        else:
            self.rename_bar.btn_stage.setEnabled(has_frames)
            self.rename_bar.btn_stage.setToolTip(tip_wolny)
        if rename_n > 0:
            self.macro_bar.btn_stage.setEnabled(False)
            self.macro_bar.btn_stage.setToolTip(i18n.t_plural("grid.rename.staging_busy_tip", rename_n))
        else:
            self.macro_bar.btn_stage.setEnabled(has_frames)
            self.macro_bar.btn_stage.setToolTip(tip_wolny)

    def _refresh_drawer(self):
        """Szuflada MODE-AWARE (R1 #2): pokazuje AKTYWNĄ klingę (staging mutex → najwyżej jedna niepusta).
        Rename → „N zmian nazw oczekuje" (mikro-zmiana §0); makro → domyślny. Gdy pending=0 ale „Cofnij"
        widoczny (świeży commit), NIE nadpisuj etykiety „Zatwierdzono/Przemianowano" pustostanem (D2/#2)."""
        rn = self._rename_pending_count()
        macro_n = self._pending_count()
        if rn > 0:
            self.drawer.set_count(rn, label=i18n.t_plural("grid.drawer.pending_rename", rn))
        elif macro_n > 0:
            self.drawer.set_count(macro_n)
        elif self._undo_mode is None:         # brak pending i brak świeżego „Cofnij" → pustostan
            self.drawer.set_count(0)          # (sygnał stanu, NIE isVisible() — zawodne bez show())
        # else: undo oferowany (`_undo_mode` ustawiony) → zachowaj etykietę „Zatwierdzono/Przemianowano"
        self._sync_staging_mutex()

    # ---- writeback off-thread (commit/undo w wątku tła; postęp + „Anuluj" w szufladzie) ----
    @property
    def _writeback_async(self):
        """Seam testowy „inline zamiast QThread" — ustawiany Z ZEWNĄTRZ na WIDOKU (cztery testy),
        a mieszkający na uchwycie. Property z getterem i SETTEREM, żeby oba zapisy trafiały w to
        samo miejsce po wydzieleniu wykonawcy (D-PD-3)."""
        return self._wb.async_ok

    @_writeback_async.setter
    def _writeback_async(self, value):
        self._wb.async_ok = value

    def _start_writeback(self, op, target_id, after_slot):
        """Odpal `op` (commit/commit_rename/undo/undo_rename) na wątku tła; postęp → szuflada, `done`
        → `after_slot` (post-processing na wątku GŁÓWNYM). Cykl wątku trzyma uchwyt `self._wb`;
        TUTAJ zostają wyłącznie rzeczy widżetowe (pasek szuflady, wygaszenie „Do stagingu")."""
        if self._wb.is_busy or self._foreign_wb:         # jeden writeback naraz (akcje i tak schowane)
            return
        self._wb_target_id = target_id
        self.drawer.begin_progress(0)
        self.macro_bar.btn_stage.setEnabled(False)       # bez nowego stagingu w biegu
        self.rename_bar.btn_stage.setEnabled(False)
        self._wb.start(op, target_id, on_progress=self._on_wb_progress, on_done=after_slot,
                       on_failed=self._on_wb_failed)

    @Slot(int, int, str, str)
    def _on_wb_progress(self, done, total, path, status):
        self.drawer.update_progress(done, total, path)

    @Slot(str, str, str)
    def _on_wb_failed(self, op, msg, podpowiedz):
        self.drawer.end_progress()
        if self._undo_mode is not None:
            # Żywe „Cofnij” (porażka cofnięcia albo gestu przy świeżym commicie): jedyną akcją zostaje
            # ono - `end_progress` pokazałby obok szare Zatwierdź/Odrzuć (reguła `_install_undo`).
            self.drawer.set_commit_actions_visible(False)
        blad = i18n.t("grid.wb.error", msg=msg)
        # Zdanie po przyłożeniu zbioru składanego w tle - raport wczytania by je przykrył (AR-84).
        # Zdanie operacji z katalogu (AR-204), nie token `op` - pasek mówi, co się nie udało, a szczegół
        # systemu stoi w jego podpowiedzi (AR-218), nie tylko w szufladzie.
        self._przeladuj_po_gescie(i18n.t(f"grid.wb.op.{op}", msg=msg), poza=False, szczegol=podpowiedz)
        # Szuflada ze stanu PRZED zdaniem błędu (jak `_after_commit`): `_refresh_drawer` przy
        # oczekujących zmianach czyści wynik jak przy nowym stagingu, a przy żywym „Cofnij” zostawia
        # etykietę „Zatwierdzono…” (dawne `set_count(0, …)` nadpisywało ją pustostanem). Zdanie błędu -
        # po nim, ze szczegółem systemu w podpowiedzi (AR-185).
        self._refresh_drawer()
        self.drawer.set_result(blad)
        self._podpowiedz_wyniku(podpowiedz)
        if self._wynik_gestu_zapisu is not None and self._wynik_gestu_zapisu[1] is None:
            # Padł gest spoza stagingu w toku (`_odpal_gest_plikowy`): błąd jest jego wynikiem, więc
            # zmiana perspektywy oddaje szufladzie zdanie sprzed gestu, jak po sukcesie (AR-204).
            self._oznacz_wynik_gestu_zapisu()
        # Wyjątek w ŚRODKU operacji nie mówi, ile plików zdążyło się zmienić (każdy plik to osobny
        # zapis), a przerwany zapis w miejscu sam jest wierszem Porządków (kopia izolowana) - więc
        # plakietka liczy się ze stanu także tu, bez zgadywania, czy coś się zapisało.
        self.stan_porzadkow_changed.emit()

    def _on_wb_cancel(self):
        if self._wb.is_busy:
            self._wb.cancel()                            # rdzeń sprawdza PRZED następnym plikiem
            self.drawer.btn_cancel.setEnabled(False)
            self.status_message.emit(i18n.t("grid.wb.cancelling"))

    def _commit_summary(self, res, noun_key):
        """Podsumowanie CommitResult: „N {noun} · M zablokowanych · …" + pierwszy powód (wiz #4).
        `noun_key` = klucz frazy głównej (`grid.wb.applied`/`grid.wb.renamed`) — DANE, nie string PL."""
        return zdanie_wyniku_zapisu(res, noun_key)       # jedno zdanie dla trzech powierzchni (Z11)

    @staticmethod
    def _wskazanie_powodow(res):
        """`(wskazanie, podpowiedź)` zdania wyniku zapisu w szufladzie - jak w oknach kart (AR-176).
        Przy RÓŻNYCH powodach zdanie mówi „pierwszy z N różnych powodów” i odsyła pod kursor
        (`wb.reasons_tip`); podpowiedź niesie wiersze `podpowiedz_kart` (pozostałe powody, szczegół
        systemu, spadek drogi zapisu). Wskazanie stoi wyłącznie w szufladzie: zdanie paska gospodarza
        niesie tę samą podpowiedź (AR-218), ale pod kursor odsyła tam glif wskaźnika pola raportu -
        drugie wskazanie w zdaniu byłoby podwójne."""
        return (i18n.t("wb.reasons_tip") if podpowiedz_powodow(res) else ""), podpowiedz_kart(res)

    def _podpowiedz_wyniku(self, podpowiedz):
        """Szczegół do BIEŻĄCEGO zdania szuflady - protokół pola (`EtykietaBledu.ustaw`, AR-204):
        podpowiedź = pełne zdanie (etykieta elidowana) + wiersze `podpowiedz`, wskaźnik i „Kopiuj
        szczegół”. Następne zdanie szuflady (`set_count`, `set_result`, postęp) szczegół zdejmuje."""
        if podpowiedz:
            self.drawer.result.ustaw(self.drawer.result.text(), podpowiedz)

    def _on_commit(self):
        if self._rename_pending_count() > 0:             # szuflada aktywnej klingi (staging mutex)
            self._on_commit_rename()
            return
        if self._run_id is None:
            return
        # Karta W MIEJSCU jak w oknach kart (AR-161): op `commit` to ten sam wołacz co
        # `commit_inplace` (`WritebackWorker._OPS`) - przepisanie całego pliku tylko spadkiem z powodem.
        self._start_writeback("commit", self._run_id, self._after_commit)

    def _after_commit(self, op, res):
        """Post-processing commitu makra (wątek główny). Anulowano → część 'pending' została w runie:
        run zostaje otwarty do dokończenia, bez „Cofnij" (zapisane siedzą w commits - undo po CLI).
        Zapis szedł w miejscu (AR-161): plik przepisany w całości (spadek na drogę atomową) zdanie
        mówi członem okien kart (`zdanie_drogi_zapisu`), szczegół spadku stoi w podpowiedzi."""
        from horreum.gui.wb_worker import zdanie_drogi_zapisu   # jedna reguła z oknami kart (AR-161)
        self.drawer.end_progress()
        # Szuflada ze stanu PRZED zdaniem wyniku: przy oczekujących zmianach (zapis przerwany)
        # `set_count` bez wyniku czyści go jak przy nowym stagingu - wołana po zdaniu zjadała
        # „przerwano, N do dokończenia” w tej samej chwili, w której padło.
        self._refresh_drawer()
        summary = self._commit_summary(res, "grid.wb.applied")
        wskazanie, podpowiedz = self._wskazanie_powodow(res)
        droga = zdanie_drogi_zapisu(res)                 # pusty bez spadku - jak w oknach kart
        remaining = self._pending_count()
        if remaining > 0:                                # przerwane anulowaniem
            ogon = i18n.t("grid.wb.interrupted", n=remaining)
            self.drawer.set_count(remaining, result=summary + wskazanie + droga + ogon)
        elif commit_do_cofniecia(res) is not None:       # także `failed` z kopią nagłówka (Z11)
            ogon = i18n.t("grid.wb.commit_id", id=res.commit_id)
            self._last_commit_id = res.commit_id
            self._install_undo(res.commit_id, summary + wskazanie + droga + ogon,
                               applied=len(res.applied))
            self._run_id = None                          # R#5: run domknięty commitem
        else:                                            # wszystko blocked/failed/skipped
            ogon = ""
            self.drawer.set_count(0, result=summary + wskazanie + droga)
            self._run_id = None
        self._podpowiedz_wyniku(podpowiedz)
        # Baza odświeżona - grid pokaże nowe wartości po składzie w tle; zdanie po przyłożeniu,
        # inaczej raport wczytania by je przykrył (AR-84). Zbiór ten sam, więc zaznaczenie wraca
        # migawką z chwili przyłożenia (przeładowanie nie-nawigacyjne, AR-172/AR-187).
        # PODGLĄD SCHODZI PO PRZYŁOŻENIU, nie przed zleceniem: reset podglądu odtwarza zaznaczenie,
        # a przeładowanie zaraz potem - drugi raz. Pod tabelą `_TabelaKlatek` (AR-202) odtworzenie
        # kosztuje O(zakresów), więc kolejność nie ratuje już sekund (natywnie, kopia pf4, 16 998
        # zaznaczonych: drugi reset ogona 73-95 ms) - dwa odtworzenia zostają długiem AR-250. Po
        # przyłożeniu zdjęcie podglądu ma do odtworzenia już tylko to, co przeładowanie zostawiło
        # (`_zbior_ogony`, wzór `_pokaz_okno_zmiany_obiektu`).
        # Do tej chwili kolumna stoi SCHOWANA (`_schowaj_podglad_po_zapisie`, AR-207).
        # ZAPIS PRZERWANY ANULOWANIEM (AR-220): ogon stawia podgląd z SAMYCH oczekujących wpisów
        # przebiegu - szuflada mówi „N do dokończenia”, a kolumna pokazuje, co zapisze następne
        # „Zatwierdź” (dawniej znikała). Nowy obiekt podglądu odsłania kolumnę (`_ukryj_kolumny`).
        pozostale = self._podglad_ze_stagingu() if remaining > 0 else {}
        if pozostale:
            self._preview_owner = "macro"
        self._schowaj_podglad_po_zapisie()
        self._zbior_ogony.append(partial(self.model.set_preview, pozostale))
        self._oznacz_przeladowanie_z_zaznaczeniem()
        # Szczegół zdania (spadek, różne powody, tekst systemu) - w podpowiedzi paska (AR-218).
        self._przeladuj_po_gescie(i18n.t("grid.wb.status", summary=summary + droga + ogon),
                                  poza=False, szczegol=podpowiedz)
        # Karta w pliku to zeznanie klatki (`header`, `cards`), a z niego liczą się wiersze Porządków
        # („Nagłówek inny niż folder", kopie niezgodne…) - więc commit, który COKOLWIEK podmienił,
        # rusza plakietkę. Warunek to reguła „Cofnij" (plik zmieniony, także `failed` z kopią
        # nagłówka) albo niepuste `applied` przy przerwaniu anulowaniem.
        if res.applied or commit_do_cofniecia(res) is not None:
            self.stan_porzadkow_changed.emit()

    def _schowaj_podglad_po_zapisie(self):
        """Kolumna podglądu chowa się OD RAZU po zapisie szuflady (AR-207): podgląd mówi „do zapisania”
        o nazwach i wartościach, które commit właśnie zapisał, a zdejmuje go dopiero ogon po
        przyłożeniu zbioru - drugi reset z drugim odtworzeniem zaznaczenia (przyłożenie odtwarza raz,
        ogon `set_preview` drugi; natywnie, kopia pf4, 16 998 zaznaczonych: ogon 73-95 ms przy ~2 s
        całego przeładowania, AR-202). Schowanie to nie reset modelu: natywnie +44..56 ms przy 16 998
        zaznaczonych. `_ukryj_kolumny`
        trzyma ją schowaną przez przyłożenie i sort, dopóki model niesie TEN podgląd."""
        kolumna = self.model._preview_col()
        if kolumna is None:
            return
        self._podglad_po_zapisie = self.model._preview
        self.table.setColumnHidden(kolumna, True)

    def _install_undo(self, commit_id, summary, applied):
        """Po udanym commicie makra szuflada oferuje jednorazowe „Cofnij" (undo całego commitu). Etykieta
        „Zatwierdzono…" zamiast pustostanu, by nie przeczyła wynikowi obok (wizytator D2)."""
        self.drawer.set_count(0, result=summary,
                              label=i18n.t("grid.wb.committed_label", n=applied, id=commit_id))
        self.drawer.set_commit_actions_visible(False)   # jedyna sensowna akcja teraz to Cofnij (#5)
        self._undo_commit_id = commit_id
        self._undo_mode = "macro"                        # dispatch współdzielonego „Cofnij" (R1 #3)
        self._ensure_undo_button()
        self._undo_btn.setVisible(True)

    def _ensure_undo_button(self):
        """Współdzielony przycisk „Cofnij" (tworzony RAZ, stabilny handler → dispatch po `_undo_mode`;
        bez churnu connect/disconnect, który sypał RuntimeWarning — wzorzec makra)."""
        if not hasattr(self, "_undo_btn"):
            self._undo_btn = QPushButton(i18n.t("grid.action.undo"))
            self._undo_btn.clicked.connect(self._dispatch_undo)
            self.drawer.layout().addWidget(self._undo_btn)

    def _dismiss_undo(self):
        """Nowa operacja stagingu UNIEWAŻNIA „Cofnij" poprzedniego commitu (transient undo wygasa — inny
        run w toku). Chowa przycisk + zeruje `_undo_mode`, żeby leftover „Cofnij" nie dispatchował undo
        starej klingi na wierzch świeżego stagingu = osierocenie pending + zakleszczenie mutexa bez
        widocznego powodu (recenzent #1, wizytator #3). Wołane na starcie stagingu obu kling."""
        if hasattr(self, "_undo_btn"):
            self._undo_btn.setVisible(False)
        self._undo_mode = None

    def _dispatch_undo(self):
        """Współdzielony „Cofnij" woła undo AKTYWNEJ klingi wg `_undo_mode` (R1 #3, init None)."""
        if self._undo_mode == "rename":
            self._on_undo_rename(self._undo_rename_run_id)
        else:
            self._on_undo(self._undo_commit_id)

    def _on_undo(self, commit_id):
        self._start_writeback("undo", commit_id, self._after_undo)

    def _after_undo(self, op, res):
        """Ogon cofnięcia makra - lustro `_after_undo_rename` (AR-31 (2)). BŁĄD JEST WIDOCZNY I DA
        SIĘ GO PONOWIĆ: `failed` bywa nagłówkiem przywróconym bez re-syncu bazy albo operacją
        w miejscu, która zostawiła lokację izolowaną, a rdzeń przy obu mówi „ponowne undo dokończy".
        Dawniej zdanie liczyło tylko przywrócone i zablokowane, a „Cofnij" gasło razem z jedynym
        uchwytem ponowienia (`commit_id`). Teraz zdanie niesie liczbę błędów i pierwszy powód
        (błędu przed blokadą), a przy błędzie „Cofnij" zostaje przy tym samym commicie z receptą.
        Ponowienie jest bezpieczne: pliki już cofnięte rdzeń odda jako zablokowane „już cofnięte".
        Zdanie i regułę „Cofnij zostaje” daje `wb_worker.ogon_cofniecia` - jedna dla trzech
        powierzchni (AR-160); zostaje też przy cofnięciu PRZERWANYM (`cancelled`): pętla rdzenia
        staje przed resztą backupów, więc commit nie jest w pełni cofnięty."""
        from horreum.gui.wb_worker import (ogon_cofniecia,   # wspólny ogon cofnięcia (AR-160)
                                           podpowiedz_systemu)
        msg, ponow = ogon_cofniecia(res, i18n.t("grid.action.undo"))
        szczegol = podpowiedz_systemu(res)               # szczegół systemu cofnięcia (AR-168)
        self.drawer.end_progress()
        if ponow:                                        # commit zostaje - „Cofnij" ponowi resztę
            self.drawer.set_commit_actions_visible(False)   # jedyną akcją dalej jest „Cofnij" (#5)
            self.drawer.set_result(msg)                  # etykieta „Zatwierdzono…" zostaje
        else:
            self._undo_btn.setVisible(False)
            self._undo_mode = None
            self.drawer.set_commit_actions_visible(True)  # przywróć akcje po cofnięciu (#5)
            self.drawer.set_count(0, result=msg)
        self._oznacz_przeladowanie_z_zaznaczeniem()      # zbiór ten sam - zaznaczenie wraca (AR-187)
        self._przeladuj_po_gescie(i18n.t("grid.wb.undo_status", msg=msg), poza=False,   # AR-84
                                  szczegol=szczegol)     # ...i w podpowiedzi paska (AR-218)
        self._refresh_drawer()                           # honest: odbij pending drugiej klingi (wiz #3b)
        self._podpowiedz_wyniku(szczegol)
        # Lustro commitu: zeznanie wróciło (patrz `_after_commit`). `failed` też rusza plakietkę -
        # cofnięcie w miejscu kończy się nim przy kopii izolowanej, a wtedy zmienia się wiersz
        # „Plik po przerwanym zapisie". Licz ze stanu, jak `_on_wb_failed`, zamiast zgadywać.
        if res.restored or res.failed:
            self.stan_porzadkow_changed.emit()

    def _on_reject(self):
        if self._rename_pending_count() > 0:             # szuflada aktywnej klingi (staging mutex)
            self._on_reject_rename()
            return
        if self._run_id is None:
            return
        # Zdanie odrzucenia - nie ogona starszego gestu, gdy zbiór jest w drodze (AR-84).
        self._podbij_zeton()
        n = self._pending_count()
        repo.clear_pending_for_run(self.con, self._run_id)
        self._run_id = None
        self.model.set_preview({})
        self._preview_owner = None
        self.drawer.set_count(0, result=i18n.t_plural("grid.wb.rejected", n))   # trwałe sprzężenie w szufladzie (#3)
        self._sync_staging_mutex()
        self.status_message.emit(i18n.t_plural("grid.wb.rejected", n))

    # ---- rename „Nazwy z faktów" (druga klinga plików: os.rename) ----
    def _note_preview_takeover(self, new_owner):
        """Podgląd współdzielony (jeden `_preview`, R1 #19): przejęcie przez drugą klingę zdejmuje
        pierwszy — komunikat w statusie, żeby zniknięcie nie było ciche. Wołane PRZED `set_preview`."""
        if (self._preview_owner and self._preview_owner != new_owner
                and self.model._preview_active()):
            other = (i18n.t("grid.preview.owner_macro") if self._preview_owner == "macro"
                     else i18n.t("grid.preview.owner_rename"))
            self.status_message.emit(i18n.t("grid.preview.takeover", other=other))
        self._preview_owner = new_owner

    def _rename_target_ids(self):
        """Cel wsadu renamu (D-I1): zaznaczenie jeśli niepuste, inaczej wszystkie widoczne. Zwraca
        (frame_ids, ZAMROŻONY opis celu) — opis idzie do statusu po akcji (R2 #10, cel ruchomy)."""
        rows = self._selected_data_rows()
        if rows:                                         # opis w języku UI, liczba odmieniona
            return [r["frame_id"] for r in rows], i18n.t_plural("grid.selected", len(rows))
        return list(self._frame_ids), i18n.t_plural("grid.visible", self._n_total)

    def _run_rename(self, ids, policy, run_id=None):
        return naming.run_rename(
            ids, targets_fn=lambda i: queries.rename_frame_targets(self.con, i),
            source=policy["source"], offset_hours=policy["offset_hours"],
            template=policy.get("template") or naming.DEFAULT_TEMPLATE,
            fallback=policy["fallback"], run_id=run_id)

    @staticmethod
    def _zdanie_bledu_wzoru(exc):
        """Zdanie paska dla błędu wzoru nazwy (`naming.validate_template`/`compose_name`): powód
        z kodem `rename_tpl_*` (AR-193) w języku UI - jedno dla podglądu i stagingu nazw."""
        from horreum.gui.wb_worker import tekst_powodu
        from horreum.item_reasons import powod_wyjatku
        return i18n.t("grid.rename.error", e=tekst_powodu(powod_wyjatku(exc)))

    def _show_rename_preview(self, run):
        """Podgląd renamu do modelu (nazwa stara→nowa / pominięto). `RenamePreview` niesie `frame_id`
        WPROST (bez mapowania location→frame jak makro). Etykieta kolumny „nazwa →" (R1 #4)."""
        self._note_preview_takeover("rename")
        preview = {}
        for pv in run.touched:                           # podpowiedź z katalogu (`grid.preview.rename_tip`)
            preview[pv.frame_id] = {"op": "rename", "old": os.path.basename(pv.old_path),
                                    "new": os.path.basename(pv.new_path)}
        for sk in run.skipped:                           # powód z kodem `rename_*` (AR-193) - w języku UI
            preview[sk.frame_id] = {"skipped": sk.reason}
        self.model.set_preview(preview, label=i18n.t("grid.preview.name"))
        self._pokaz_kolumne_podgladu()
        return len(run.touched), len(run.skipped)

    def _on_rename_preview(self, policy):
        if self._odmowa_w_drodze():                      # cel bez zaznaczenia = widoczne (zbiór poprzedni)
            return
        ids, target = self._rename_target_ids()
        if not ids:
            self.status_message.emit(i18n.t("grid.rename.no_count"))
            return
        try:
            run = self._run_rename(ids, policy)
        except ValueError as e:                          # zły regex orig we wzorze (INFORMUJ)
            self.status_message.emit(self._zdanie_bledu_wzoru(e))
            return
        t, s = self._show_rename_preview(run)
        self.status_message.emit(i18n.t("grid.rename.preview_result", t=t, s=s, target=target))

    def _on_rename_stage(self, policy):
        if self._odmowa_w_drodze():
            return
        ids, target = self._rename_target_ids()
        if not ids:
            self.status_message.emit(i18n.t("grid.rename.no_frames"))
            return
        if self._pending_count() > 0:                    # mutex: staging makra w toku
            self.status_message.emit(i18n.t("grid.rename.staging_busy"))
            return
        self._dismiss_undo()                             # nowy staging unieważnia leftover „Cofnij" (wiz #3)
        # Pętla życia run_id (R1 #1 + R2 #1): run niecommitowany → clear (bezpieczne, same 'pending');
        # run skommitowany → MINTUJ NOWY (clear skasowałby wiersze 'applied' = rekordy undo).
        try:
            naming.validate_template(policy.get("template") or naming.DEFAULT_TEMPLATE)  # zły regex → stop przed mintem
        except ValueError as e:
            self.status_message.emit(self._zdanie_bledu_wzoru(e))
            return
        if self._rename_run_id is None or self._rename_run_committed:
            self._rename_run_id = uuid.uuid4().hex
            self._rename_run_committed = False
        else:
            repo.clear_renames_for_run(self.con, self._rename_run_id)
        run = self._run_rename(ids, policy, run_id=self._rename_run_id)
        for p in run.touched:
            repo.stage_rename(self.con, run_id=self._rename_run_id, location_id=p.location_id,
                              old_path=p.old_path, new_path=p.new_path, expected_mtime=p.mtime)
        self._show_rename_preview(run)
        self._refresh_drawer()
        self.status_message.emit(i18n.t_plural(
            "grid.rename.staged", len(run.touched), s=len(run.skipped), target=target))

    def _on_rename_clear(self, oddaj_staging=True):
        """Zdjęcie podglądu nazw. Rename PRZEJMUJE podgląd, gdy w szufladzie czekają karty makra
        (podgląd nie jest stagingiem - mutex trzyma tylko „Do stagingu"), więc przy zdjęciu ODDAJE
        go: kolumna wraca do tego, co zapisze commit (AR-72) - inaczej oczekujące karty stałyby bez
        podglądu aż do następnej edycji. `oddaj_staging=False` woła otwarcie panelu rodowodu: tam
        podgląd żadnej klingi nie zostaje (R#9), więc i staging nie wraca.

        JEDEN RESET: podgląd stagingu zastępuje podgląd nazw wprost - zdjęcie i postawienie to dwa resety
        modelu i dwa odtworzenia zaznaczenia (AR-202)."""
        oddaje = oddaj_staging and self._pending_count() > 0
        self._preview_owner = "macro" if oddaje else None
        self.model.set_preview(self._podglad_ze_stagingu() if oddaje else {})
        if oddaje:
            self._pokaz_kolumne_podgladu()
            self.status_message.emit(i18n.t("grid.rename.preview_cleared_staging_back"))
            return
        self.status_message.emit(i18n.t("grid.rename.preview_cleared"))

    def _on_commit_rename(self):
        run_id = self._rename_run_id
        if run_id is None:
            return
        self._start_writeback("commit_rename", run_id, self._after_commit_rename)

    def _after_commit_rename(self, op, res):
        """Post-processing commitu renamu (wątek główny). Anulowano → reszta nazw została 'pending':
        run zostaje otwarty do dokończenia, bez „Cofnij"."""
        self.drawer.end_progress()
        self._refresh_drawer()                           # PRZED zdaniem wyniku - jak w `_after_commit`
        run_id = self._wb_target_id
        summary = self._commit_summary(res, "grid.wb.renamed")
        wskazanie, podpowiedz = self._wskazanie_powodow(res)   # pozostałe powody (AR-176)
        remaining = self._rename_pending_count()
        if remaining > 0:                                # przerwane anulowaniem
            ogon = i18n.t("grid.wb.interrupted", n=remaining)
            self.drawer.set_count(remaining, label=i18n.t_plural("grid.drawer.pending_rename", remaining),
                                  result=summary + wskazanie + ogon)
        elif res.applied:                                # Cofnij TYLKO gdy coś zrobione (R2 #6)
            ogon = i18n.t("grid.wb.run_id", id=run_id)   # run_id w wyniku: undo po restarcie przez CLI (R2 #7)
            self._undo_rename_run_id = run_id            # PRZECHWYĆ cel Cofnij przed re-stage (R2 #1)
            self._rename_run_committed = True
            self._install_rename_undo(run_id, summary + wskazanie + ogon, applied=len(res.applied))
        else:                                            # wszystko blocked/failed → run zwolniony
            ogon = ""
            self._rename_run_id = None
            self._rename_run_committed = False
            self.drawer.set_count(0, result=summary + wskazanie)
        self._podpowiedz_wyniku(podpowiedz)
        # Baza odświeżona - grid pokaże nowe ścieżki po składzie w tle, zdanie po przyłożeniu (AR-84).
        # Zbiór ten sam - zaznaczenie wraca migawką z chwili przyłożenia (AR-187); podgląd schodzi
        # po przyłożeniu - ten sam powód, co w `_after_commit`; do tej chwili schowany (AR-207).
        # Przerwany anulowaniem - ogon stawia podgląd pozostałych nazw (AR-220, lustro `_after_commit`).
        pozostale = self._podglad_nazw_ze_stagingu() if remaining > 0 else {}
        self._preview_owner = "rename" if pozostale else None
        self._schowaj_podglad_po_zapisie()
        self._zbior_ogony.append(partial(self.model.set_preview, pozostale,
                                         label=i18n.t("grid.preview.name")))
        self._oznacz_przeladowanie_z_zaznaczeniem()
        self._przeladuj_po_gescie(i18n.t("grid.rename.status_summary", summary=summary + ogon),
                                  poza=False, szczegol=podpowiedz)   # szczegół na pasku (AR-218)
        if res.applied:                                  # ogon zapisu → plakietka (definicja sygnału)
            self.stan_porzadkow_changed.emit()

    def _install_rename_undo(self, run_id, summary, applied):
        """Po udanym rename szuflada oferuje „Cofnij" (undo_renames przebiegu). Lustro `_install_undo`
        makra, tryb `rename` (dispatch współdzielonego przycisku). Etykieta CZYSTA (bez 32-hex szumu);
        pełny run_id zostaje w `result`=summary jako kotwica CLI-undo po restarcie (R2 #7, wiz #6)."""
        self.drawer.set_count(0, result=summary, label=i18n.t("grid.rename.renamed_label", n=applied))
        self.drawer.set_commit_actions_visible(False)
        self._undo_mode = "rename"
        self._ensure_undo_button()
        self._undo_btn.setVisible(True)

    def _on_undo_rename(self, run_id):
        self._start_writeback("undo_rename", run_id, self._after_undo_rename)

    def _after_undo_rename(self, op, res):
        """Ogon cofnięcia renamu. BŁĄD JEST WIDOCZNY I DA SIĘ GO PONOWIĆ: `failed` bywa rozdarciem
        plik↔baza („plik PRZENIESIONY…, baza NIE przepięta - zamiar renamu zapisany: ponowienie albo
        cofnięcie przebiegu dokończy przepięcie") albo czkawką
        `os.rename` na udziale, a wiersze nieudanego cofnięcia zostają w przebiegu jako 'applied'.
        Dawniej zdanie mówiło samo „przywrócono: 0", a „Cofnij" gasło - rozjazd znikał z ekranu,
        a jedyna droga ponowienia (run_id) ginęła razem z przyciskiem. Teraz zdanie niesie liczbę
        błędów i pierwszy powód (błędu przed blokadą), a przy błędzie „Cofnij" zostaje przy tym
        samym przebiegu z receptą ponowienia.
        Zdanie i regułę daje wspólny ogon `wb_worker.ogon_cofniecia` (AR-160): „Cofnij” zostaje
        przy każdym cofnięciu niedomkniętym (`UndoResult.complete`) - także PRZERWANYM
        (`undo_renames` przerywa przed resztą wierszy) i zablokowanym (`undo_renames` pomija wiersze
        już cofnięte, więc blokada znaczy plik, który NIE wrócił)."""
        from horreum.gui.wb_worker import (ogon_cofniecia,   # wspólny ogon cofnięcia (AR-160)
                                           podpowiedz_systemu)
        msg, ponow = ogon_cofniecia(res, i18n.t("grid.action.undo"))
        szczegol = podpowiedz_systemu(res)               # szczegół systemu cofnięcia (AR-168)
        self.drawer.end_progress()
        if ponow:                                        # przebieg zostaje - „Cofnij" ponowi resztę
            self.drawer.set_commit_actions_visible(False)   # jedyną akcją dalej jest „Cofnij" (#5)
            self.drawer.set_result(msg)                  # etykieta „Przemianowano…" zostaje
        else:
            self._undo_rename_run_id = None
            self._undo_mode = None
            self._rename_run_id = None
            self._rename_run_committed = False
            self._undo_btn.setVisible(False)
            self.drawer.set_commit_actions_visible(True)  # przywróć akcje po cofnięciu (#5)
            self.drawer.set_count(0, result=msg)
        self._oznacz_przeladowanie_z_zaznaczeniem()      # zbiór ten sam - zaznaczenie wraca (AR-187)
        self._przeladuj_po_gescie(i18n.t("grid.rename.undo_status", msg=msg), poza=False,  # AR-84
                                  szczegol=szczegol)     # ...i w podpowiedzi paska (AR-218)
        self._refresh_drawer()
        self._podpowiedz_wyniku(szczegol)
        if res.restored or res.failed:                   # lustro commitu renamu; błąd mógł przenieść plik
            self.stan_porzadkow_changed.emit()

    def _on_reject_rename(self):
        if self._rename_run_id is None:
            return
        # Zdanie odrzucenia - nie ogona starszego gestu, gdy zbiór jest w drodze (AR-84).
        self._podbij_zeton()
        n = self._rename_pending_count()
        repo.clear_renames_for_run(self.con, self._rename_run_id)
        self._rename_run_id = None
        self._rename_run_committed = False
        self.model.set_preview({})
        self._preview_owner = None
        self.drawer.set_count(0, result=i18n.t_plural("grid.rename.rejected", n))
        self._sync_staging_mutex()
        self.status_message.emit(i18n.t_plural("grid.rename.rejected", n))
