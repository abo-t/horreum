"""Widok PORZĄDKI — `TasksView` (F5, PLAN_ux_redesign §6): lista zadań ze STANU bazy + podstrony
osi (teleskop/obserwatorium/przegląd obiektów) montowane w wewnętrznym stacku. Trzecie miejsce
nawigacji `MainWindow` (Dostawa / Zbiory / Porządki).

Glue Qt↔read-model: liczniki liczy `queries.tasks_state` (bieżący STAN tabel, nigdy `count(event)`
- memory horreum-review-queue-from-state), a wiersze osi sprzętu, stanowiska i faktu zatrzymanego
dokłada `_liczniki_osi` od właścicieli ich predykatów; ten plik NIE wykonuje żadnego SQL (meta-test AST
`test_repo_safety.py` skanuje i ten plik). Warstwa widżetów — na whiteliście `test_gui_isolation`.

KIERUNEK IMPORTÓW (F5R2#1): ten moduł importuje widoki osi z `horreum.gui.app` MODULE-LEVEL;
`app.py` importuje `TasksView` WYŁĄCZNIE lazy w `_mount_views` (wzorzec pipeline/grid) — import
na górze `app.py` domknąłby cykl → ImportError na starcie aplikacji.

Kontrakt montażu: `TasksView(con, now_fn, parent)`; pod-widoki osi wystawione jako `.axis_view`/
`.observatory_view`/`.object_view` (MainWindow ALIASUJE je na sobie - kontrakt
`_odswiez_widoki_po_przebiegu`/`_on_pipeline_running` przeżywa przemontowanie bez zmian).
`now_fn` FORWARDOWANE do pod-widoków (F5R#2 - otrzymany argument, nie własny default: akcje osi
w podstronach piszą wstrzykniętym zegarem, asercja tożsamości `_now` w testach stabilna).

Świadomy cykl odświeżania: licznik NIE odświeża się na żywo w trakcie pracy w podstronie —
`refresh_counts()` woła gospodarz przy montażu / po przebiegu Dostawy / na wejściu w Porządki,
a sam widok przy powrocie „← Porządki" (user mógł nazwać teleskopy w podstronie)."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QStackedWidget, QVBoxLayout,
    QWidget,
)

from horreum import resolver, scan, supersede
from horreum.gui import i18n, queries, rows, theme
from horreum.gui.app import (
    _REVIEW_TAG, ObjectAxisView, ObservatoryAxisView, TelescopeAxisView, _utc_now_iso,
)
from horreum.gui.grid import (PRESET_COPY_CONFLICT, PRESET_DUPS, PRESET_LINEAGE,
                              PRESET_MISSING_COPY, PRESET_ORPHAN_TESTIMONY,
                              PRESET_PATH_HEADER_CONFLICT, PRESET_PENDING_FINISH, PRESET_RETIRED,
                              PRESET_TORN_WRITE, PRESET_RETIRED_CONFLICT, PRESET_STACK_VERSIONS,
                              PRESET_SUPERSEDED, PRESET_VANISHED, zdanie_kopii_bez_zeznania)
from horreum.gui.rows import TwoPartDelegate

# Definicja listy zadań: (klucz stanu z `tasks_state`, etykieta, akcja). Akcja: numer podstrony
# wewnętrznego stacku (int), nazwa perspektywy Zbiorów (str — sygnał `open_collection`) albo None
# (pozycja INFORMACYJNA — bez powierzchni akcji). Wiersze AKCYJNE (akcja ≠ None) z n>0 liczą się do
# badge'a sidebara — informacja nie jest zadaniem. „Zniknięte" AWANSOWAŁY z informacji na akcję wraz
# z passem obecności (P5/#7): dopóki nie było przebiegu wykrywającego, liczba była martwa i nie było
# jej gdzie rozwinąć — teraz prowadzi do perspektywy z listą klatek bez ani jednej obecnej kopii.
# Wiersz „XISF (nagłówki tylko do odczytu)" ZNIKNĄŁ w P6c: pisarz XISF istnieje, więc zdanie było
# już nieprawdą, a sam licznik plików danego formatu nie jest robotą do zrobienia (facet formatu
# w Zbiorach mówi to samo, w miejscu, gdzie się o to pyta).
# Wiersz „Obrazy bez rodowodu" DOSZEDŁ 0808 i celuje w PERSPEKTYWĘ, nie w podstronę — bo gest
# (potwierdź / odrzuć wejście / wskaż odniesienie czasu) mieszka w panelu „Rodowód" w Zbiorach
# i działa z zaznaczenia jednej klatki. Do tej zmiany liczba istniała wyłącznie w raporcie etapu
# Dostawy, a droga od niej do konkretnego obrazu wiodła przez przeklikanie całego archiwum stosów.
_PAGE_LIST, _PAGE_TELESCOPE, _PAGE_OBSERVATORY, _PAGE_OBJECTS = range(4)
# Szarość wierszy BEZ roboty: pozycje informacyjne (zawsze) i akcyjne z n=0 (wiz F5 #6 — „nic do
# zrobienia" ma być widać bez czytania liczby). Akcyjne z n=0 zostają KLIKALNE: podstrona osi to
# jedyna droga do niej po przemontowaniu nawigacji.
_DIM: dict[str, QColor] = {}


def use_theme(name):
    """Szarość wierszy bez roboty — Z MOTYWU (wzorzec `grid.use_theme`, wołane przez `app.apply_theme`).
    Sztywne `QColor(0x88,0x88,0x88)` przeżyło F6 i miało w motywie JASNYM 3,54:1 — poniżej AA;
    bramka `test_theme_jest_jedynym_wlascicielem_kolorow` go nie łapała, bo skanowała stringi,
    a to wywołanie na literałach liczbowych (wizytacja P-C #5)."""
    _DIM["fg"] = QColor(theme.accents(name)["secondary_text"])


use_theme(theme.DEFAULT)
# Szerokość listy zadań. Prawe wyrównanie liczb SKANUJE się w wąskim pasie i ROZJEŻDŻA na szerokim:
# przy oknie 1200 px etykieta lądowała na x≈185, a liczba na x≈1180 — ~900 px pustki między nimi
# (wizytator P1 #2, dług delegata przeniesionego z listwy 220 px na pełną szerokość okna).
# Liczba z POMIARU TREŚCI, nie z oka: najdłuższa etykieta ≈ 172 px (pomiar na „XISF (nagłówki tylko
# do odczytu)", wiersz zdjęty w P6c — po nim etykiety są KRÓTSZE, więc zapas tylko urósł)
# + najszerszy człon drugi („381  ›") = 35 px + `_GAP`/`_PAD` ≈ 230 px. 400 px daje oddech bez
# rozjeżdżania; przy 520 px wzrok znów gubi drogę etykieta→liczba (wizytator P1 tura 2).
_LIST_MAX_W = 400
# etykieta = KLUCZ i18n rozwiązywany w budowie/refresh (nie zamrażać PL przy imporcie).
_TASKS = [
    ("unresolved_lights", "tasks.unresolved_lights", _PAGE_OBJECTS),
    # Wiersz AKCYJNY i ROBOTA (E5-2) - stoi pod „Obiektami do przeglądu", bo to ta sama oś, ale
    # odwrotny stan: tam klatka obiektu NIE MA, tu MA go z zatwierdzonego folderu, a karta `OBJECT`
    # w pliku mówi co innego (albo coś nierozpoznanego). Prowadzi do PERSPEKTYWY, bo gesty
    # („Przypisz obiekt", makro karty w pliku) działają z zaznaczenia w Zbiorach - „Napraw
    # nagłówek…" tej klatki nie widzi (bierze wyłącznie klatki bez obiektu). Liczba i lista
    # czytają jeden predykat (`queries.path_header_conflict_frame_ids`).
    ("path_header_conflict_frames", "tasks.path_header_conflict_frames",
     PRESET_PATH_HEADER_CONFLICT),
    ("stacks_lineage_pending", "tasks.stacks_lineage", PRESET_LINEAGE),
    # Dwa wiersze AKCYJNE i ROBOTA (AR-59) - liczą KLATKI, które czekają na gest ręki na osi
    # sprzętu i na osi stanowiska. Do tej zmiany gesty istniały, ale prowadziły do nich wiersze
    # liczące co innego (teleskopy bez etykiety, stanowiska bez nazwy) - szare „0" mówiło „nie ma
    # roboty" przy 423 klatkach bez zestawu i 1223 bez stanowiska. Liczba czyta predykat jedynego
    # właściciela (`_liczniki_osi`), a klik prowadzi do podstrony z gestem.
    ("config_review_frames", "tasks.config_review_frames", _PAGE_OBJECTS),
    ("telescopes_unlabeled", "tasks.telescopes_unlabeled", _PAGE_TELESCOPE),
    ("observatory_review_frames", "tasks.observatory_review_frames", _PAGE_OBSERVATORY),
    ("observatories_unnamed", "tasks.observatories_unnamed", _PAGE_OBSERVATORY),
    ("dup_frames", "tasks.dup_frames", PRESET_DUPS),
    # Wiersz AKCYJNY i ROBOTA (0021) - świadomie POZA `_BEZ_ROBOTY`. Dwie kopie JEDNEJ klatki mówią
    # sprzeczne rzeczy (inny FILTER, inna liczba obrazów), a oś klatki pokazuje zeznanie tej, która
    # wygrała w `header` - więc jedna z nich wprowadza w błąd i ktoś musi rozstrzygnąć, która.
    # Rozstrzyga gest „Ta kopia prowadzi" w menu prawego kliku w Zbiorach (AR-4, AR-23): klatka
    # przejmuje zeznanie wskazanej kopii, a wybór jest faktem ręki. Kopie dalej się różnią, więc
    # klatka zostaje na liście (tam się decyzję widzi i zmienia), ale robotą jest wyłącznie podzbiór
    # BEZ decyzji ręki (`_ROBOTA_Z_PODZBIORU`, wzorzec „Wersji stosów"). Stoi pod „Duplikatami", bo
    # jest ich podzbiorem. Liczba i lista czytają jeden predykat (`queries.copy_conflict_frame_ids`).
    ("copy_conflict_frames", "tasks.copy_conflict_frames", PRESET_COPY_CONFLICT),
    # Wiersz AKCYJNY i ROBOTA (AR-5) - stoi pod „Kopiami niezgodnymi", bo to ta sama rodzina pytań.
    # Tam kopie kłócą się ze sobą; tu zgadzać się mogą, ale `header` mówi głosem kopii, której już
    # nie ma. Kopię wiodącą wskazuje człowiek (AR-4) gestem „Ta kopia prowadzi" (AR-23) przy ≥2
    # obecnych kopiach albo zeznaniu z ręki; po geście klatka mówi głosem obecnej kopii i wypada
    # z predykatu sama. Klatki o jednej kopii naprawia etap Dostawy, ale tylko pod korzeniem, po
    # którym chodzi - więc wiersz liczy wszystkie (`queries.orphan_testimony_frame_ids`), żeby żadna
    # nie czekała niewidoczna; gest działa i na nich.
    ("orphan_testimony_frames", "tasks.orphan_testimony_frames", PRESET_ORPHAN_TESTIMONY),
    # Wiersz AKCYJNY (0022, Q8): kopia po przerwanym zapisie nagłówka w miejscu, izolowana od skanu.
    # Robota człowieka: odzysk z dziennika operacji albo zwolnienie po własnym rozstrzygnięciu.
    ("torn_write_frames", "tasks.torn_write_frames", PRESET_TORN_WRITE),
    # Wiersz AKCYJNY i ROBOTA (AR-17 (1)): zapis w miejscu zweryfikowany, a baza jeszcze go nie
    # wciągnęła - kopia izolowana od skanu tak samo jak po przerwanym zapisie, ale robotą jest
    # dokończenie („Dokończ zapis" w Zbiorach). Bez tego wiersza taka lokacja była niewidoczna,
    # a skan ją pomijał. Stoi pod sąsiadem, bo to druga połowa tej samej izolacji.
    ("pending_finish_frames", "tasks.pending_finish_frames", PRESET_PENDING_FINISH),
    ("vanished_frames", "tasks.vanished_frames", PRESET_VANISHED),
    # Wiersz INFORMACYJNY, nie zadanie: klatka zastąpiona nie ma czego wymagać od użytkownika —
    # treść przejęła następczyni. Stoi tu, bo od 0809 wypadła z WSZYSTKICH kubełków kolejki
    # (nie jest robotą), a bez tej pozycji jedyną drogą do niej byłby przypadek w gridzie pełnym.
    ("superseded_frames", "tasks.superseded_frames", PRESET_SUPERSEDED),
    # Wiersz KLIKALNY, ale NIE ROBOTA (AR-41) - podzbiór „Zastąpionych": werdykt obiektu z ręki,
    # który został na klatce zastąpionej, bo następczyni nie jest lightem. Nic nie przepadło (append-
    # only) i żaden gest tego nie opróżni, więc wiersz stoi w `_BEZ_ROBOTY`; istnieje po to, żeby ten
    # stan był widać ZE STANU, a nie tylko ze zdania po geście przeniesienia. Liczba z predykatu
    # `supersede.kept_object_facts` (lustro klingi); dziś 0 i wtedy wiersz milczy szarym zerem.
    ("object_kept_frames", "tasks.object_kept_frames", PRESET_SUPERSEDED),
    # Dwa wiersze jednej kolumny (D-OW-3/R2), o RÓŻNEJ naturze — i to rozróżnienie jest tu całą
    # treścią. „Wycofane" to zapis historii jak „Zastąpione": klatka nie wymaga niczego, stoi na
    # liście po to, żeby dało się ją znaleźć i PRZYWRÓCIĆ. „Wycofane, a plik wrócił" jest ROBOTĄ,
    # bo to jedyny stan, w którym ŻYWA klatka wypada ze wszystkich kubełków — gdyby i on był
    # informacyjny, gest wycofania cicho ukrywałby materiał, który wrócił na dysk, czyli wnosiłby
    # dokładnie ten defekt, który ta paczka leczy.
    # Każdy z dwóch wierszy prowadzi do WŁASNEJ perspektywy (G2-7d): lista pod klikiem ma liczyć
    # to samo, co liczba obok. Wspólny cel „Wycofane" pokazywał pod „a plik wrócił 1" także
    # klatki bez pliku, malowane identycznie - a „Przywróć" na nich cofało werdykt ręki o klatce,
    # której pliku naprawdę nie ma. Liczba i perspektywa czytają ten sam predykat
    # (`queries.retired_conflict_frame_ids`), równość pinuje test.
    ("retired_frames", "tasks.retired_frames", PRESET_RETIRED),
    ("retired_conflict_frames", "tasks.retired_conflict_frames", PRESET_RETIRED_CONFLICT),
    # Wiersz KLIKALNY, ale NIE ROBOTA (D-V-9a) - trzeci stan, jak "Zastapione" i "Wycofane".
    # Klatka zyje; zniknela jej JEDNA z kopii, wiec nie ma tu nic do zrobienia i nic sie nie
    # pali. Stoi na liscie, bo po naprawie D-V-9 ten fakt widac bylo wylacznie pod kursorem,
    # jeden wiersz naraz - a dotyczy 128 gotowych obrazow.
    ("missing_copy_frames", "tasks.missing_copy_frames", PRESET_MISSING_COPY),
    # Wiersz AKCYJNY, ROBOTA LICZONA PODZBIOREM (AR-10). Wersje stosów to decyzja, którą człowiek
    # ma prawo podjąć „zostawiam wszystkie" i nigdy do niej nie wracać - od 0026 ten wybór ma werdykt
    # w bazie (gest w menu tabeli perspektywy, z drogą powrotu). Liczba i lista pod klikiem czytają
    # jeden predykat (`queries.stack_version_frame_ids`, także grupy z werdyktem - tam się go widzi
    # i cofa), a robotą jest podzbiór grup BEZ werdyktu (`_ROBOTA_Z_PODZBIORU`). Do 0026 wiersz stał
    # w `_BEZ_ROBOTY`, bo bez werdyktu świeciłby wiecznie po prawowitej decyzji.
    ("stack_versions", "tasks.stack_versions", PRESET_STACK_VERSIONS),
]

# WIERSZE, KTÓRYCH ROBOTA JEST PODZBIOREM LICZBY (AR-10): klucz wiersza → klucz licznika roboty
# w `queries.tasks_state`. Liczba i lista pod klikiem zostają jednym zbiorem; plakietkę,
# pogrubienie i kolor rozstrzyga podzbiór. Przy podzbiorze mniejszym od całości wiersz mówi
# „robota z liczby" (`tasks.of_total`), żeby rozjazd liczby z plakietką nie wyglądał na błąd.
_ROBOTA_Z_PODZBIORU = {"stack_versions": "stack_versions_open",
                       "copy_conflict_frames": "copy_conflict_open"}
# Podpowiedź części liczby, która robotą NIE jest - klucz wiersza → (klucz zdania w odmianie,
# nazwy z katalogu). Liczba tej części = liczba wiersza minus robota.
_PODPOWIEDZ_PODZBIORU = {
    "stack_versions": ("tasks.stack_versions_kept_tip", {"keep": "grid.version.keep_all"}),
    "copy_conflict_frames": ("tasks.copy_conflict_led_tip", {}),
}


def _zdanie_podzbioru(key, n):
    """Zdanie podpowiedzi o `n` pozycjach liczby wiersza `key`, które robotą nie są."""
    klucz, nazwy = _PODPOWIEDZ_PODZBIORU[key]
    return i18n.t_plural(klucz, n, **{k: i18n.t(v) for k, v in nazwy.items()})

# TRZECI STAN WIERSZA: KLIKALNY, ALE NIE ROBOTA. Do 0809 lista znała dwa — informacyjny (cel `None`,
# nie prowadzi nigdzie) i akcyjny (cel jest, liczba > 0 znaczy „tu jest robota"). Wiersz „Zastąpione"
# nie mieści się w żadnym: MA dokąd prowadzić, ale jego liczba nigdy nie jest zadaniem.
# Bez tego zbioru wpadał do odznaki sidebara i dostawał pogrubienie „TU JEST ROBOTA" — czyli tylnymi
# drzwiami odtwarzał dokładnie ten defekt, który pakiet kolejki wyleczył w kubełkach (bramka 3a
# 0809, zarzut `kimi` #4). Klucz, nie flaga w krotce: krotka opisuje POZYCJĘ, a to jest fakt o jej
# NATURZE, i tak samo czyta go badge, jak i pogrubienie.
_BEZ_ROBOTY = frozenset({"superseded_frames", "retired_frames", "missing_copy_frames",
                         "object_kept_frames"})


def _liczniki_osi(con):
    """Liczniki wierszy AR-59/AR-41, których `queries.tasks_state` nie niesie - WOŁANE od jedynych
    właścicieli predykatów, nie powielane (ten plik nie wykonuje SQL):

      * `config_review_frames` = `resolver.review_state(con).no_config` - właściciel kubełka sprzętu
        kolejki przeglądu (kind-aware: dark/bias z `grouper.NO_TELESCOPE_KINDS` nie mają zestawu
        z definicji; klatka bez zeznania i zastąpiona/wycofana poza). Lista pod klikiem
        (`queries.config_review_frames`) jest jego lustrem pinowanym testem.
      * `observatory_review_frames` = długość wejścia gestu „Wskaż stanowisko…"
        (`queries.observatory_review_frames`) - oś stanowiska jest KIND-AGNOSTIC, więc liczba
        obejmuje każdy rodzaj, dokładnie tyle, ile okno gestu pokaże.
      * `object_kept_frames` = `supersede.kept_object_facts` (AR-41).
      * `copy_conflict_open` = klatki „Kopii niezgodnych" BEZ decyzji ręki (AR-23) - robota
        wiersza (`_ROBOTA_Z_PODZBIORU`). Decyzję czyta `queries.hand_testimony_frame_ids` (jeden
        właściciel pytania „czyj głos niesie `header`"): gest „Ta kopia prowadzi" zostawia
        `header.adopted` z aktorem `user:local`. Zapis nagłówka w miejscu odmawia przy kilku
        obecnych kopiach (`macro`, D-W1), więc ręka na klatce z rozjazdem kopii to ten gest.

    Pomiar 2026-10-06 na kopii żywej bazy: 423 bez zestawu (422 light RAW bez TELESCOP w EXIF,
    1 `unknown` XISF), 1223 bez stanowiska, 0 zatrzymanych faktów."""
    niezgodne = queries.copy_conflict_frame_ids(con)
    return {
        "config_review_frames": resolver.review_state(con).no_config,
        "observatory_review_frames": len(queries.observatory_review_frames(con)),
        "object_kept_frames": len(supersede.kept_object_facts(con)),
        "copy_conflict_open": len(niezgodne - queries.hand_testimony_frame_ids(con, niezgodne)),
    }


# Wiersz, którego podstrona ma kilka kubełków: klik ZAZNACZA właściwy, żeby lista klatek i gest
# stały gotowe (klucz wiersza → tag kubełka kolejki przeglądu `ObjectAxisView`).
_KUBELEK_PODSTRONY = {"config_review_frames": "config_review"}

# Podpowiedzi wierszy AR-59/AR-41 - mówią, gdzie mieszka gest (nazwy z katalogu przy renderze).
_PODPOWIEDZI_OSI = {
    "config_review_frames": ("tasks.config_review_tip", {"assign": "object.set_config_btn"}),
    "observatory_review_frames": ("tasks.observatory_review_tip",
                                  {"assign": "obshand.btn_assign"}),
    "object_kept_frames": ("tasks.object_kept_tip", {"persp": "perspective.superseded"}),
    # AR-23: gest „Ta kopia prowadzi" mieszka w menu prawego kliku w Zbiorach - wiersz mówi, gdzie.
    "copy_conflict_frames": ("tasks.copy_conflict_tip", {"lead": "grid.lead.menu"}),
    "orphan_testimony_frames": ("tasks.orphan_testimony_tip", {"lead": "grid.lead.menu"}),
}

# WIERSZE, KTÓRYCH ZERO JEST WIEDZĄ DOPIERO PO ZEBRANIU FAKTÓW KOPII (0021). Oba predykaty porównują
# zeznania kopii, a kopia bez faktów w porównaniu nie bierze udziału - więc przed pierwszą Dostawą
# po migracji „0" znaczyło „nie wiem", a wyglądało jak „sprawdzone, czysto". Gdy są kopie bez
# faktów, zero tych wierszy mówi „?" i dlaczego, a podpowiedź - co da liczbę. Liczba i lista pod
# klikiem dalej czytają jeden predykat; zmienia się wyłącznie to, jak wiersz wypowiada swoje zero.
# „?" nie jest robotą: nie pogrubia się i nie wchodzi do plakietki (robotą jest Dostawa albo
# „Oznacz zniknięte", nie ten wiersz). Liczba niezerowa przy kopiach bez faktów jest DOLNĄ granicą
# i mówi „N+" z tą samą receptą - tam robota jest (klatki do obejrzenia), więc wiersz zostaje
# pogrubiony i klik prowadzi do perspektywy. Kopie bez faktów liczy predykat porównywalnych
# kandydatów (`scan.copy_facts_candidates(..., porownywalne=True)`): pojedynczy XISF czeka na
# uzupełnienie, ale żadnej z tych dwóch liczb nie zmieni. Kopia NIECZYTELNA bez faktów też jest
# w tej liczbie (AR-26): sterownik jej nie czyta, ale dla porównania kopii to to samo „nie wiem".
_CZEKA_NA_FAKTY_KOPII = frozenset({"copy_conflict_frames", "orphan_testimony_frames"})
# KLIK W „?" PROWADZI DO DOSTAWY, nie do perspektywy (AR-28 (b)). Lista pod klikiem czyta ten sam
# predykat co liczba, a liczba „nie wie" - więc perspektywa była pusta („Brak klatek w tej
# perspektywie"), choć szewron zapraszał. Robotą w tym stanie jest zebranie faktów kopii albo
# oznaczenie zniknięć, a oba gesty mieszkają w Dostawie (`open_intake`, gospodarz przełącza widok).

# PODPOWIEDZI WIERSZY IZOLACJI ZAPISU W MIEJSCU: klik otwiera perspektywę, ale gest mieszka w menu
# prawego kliku w Zbiorach, którego nie widać, dopóki się go nie otworzy - więc wiersz mówi, gdzie
# szukać. Klucz wiersza → klucz podpowiedzi; nazwy gestów czytane z katalogu przy renderze.
_PODPOWIEDZI_GESTU = {"torn_write_frames": "tasks.torn_write_tip",
                      "pending_finish_frames": "tasks.pending_finish_tip"}


class TasksView(QWidget):
    """Miejsce PORZĄDKI: strona 0 = lista zadań ze stanu, strony 1–3 = podstrony osi (te same widoki
    co dawne zakładki, opakowane w pasek „← Porządki"). Klik w zadanie prowadzi do powierzchni:
    podstrona osi albo Zbiory z ustawioną perspektywą (sygnał `open_collection` — duplikatów NIE
    wyraża drzewo filtra, to flaga `only_dups` presetu, R#14). Wiersze akcyjne klikalne ZAWSZE
    (także n=0 — podstrona to jedyna droga do osi po przemontowaniu nawigacji)."""

    open_collection = Signal(str)   # nazwa perspektywy Zbiorów (gospodarz przełącza widok)
    open_intake = Signal()          # klik w wiersz „?" - robota czeka w Dostawie (AR-28 (b))
    counts_changed = Signal(int)    # badge sidebara: liczba pozycji AKCYJNYCH z n>0

    def __init__(self, con, now_fn=_utc_now_iso, parent=None):
        super().__init__(parent)
        self.con = con
        self._niewiadome = set()    # klucze wierszy w stanie „?" z ostatniego `refresh_counts`
        # pod-widoki osi z FORWARDOWANYM now_fn (F5R#2) — wystawione dla aliasów MainWindow
        self.axis_view = TelescopeAxisView(con, now_fn=now_fn)
        self.observatory_view = ObservatoryAxisView(con, now_fn=now_fn)
        self.object_view = ObjectAxisView(con, now_fn=now_fn)
        self._build_ui()

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages)

        # strona 0: lista zadań
        list_page = QWidget()
        lv = QVBoxLayout(list_page)
        lv.addWidget(QLabel(i18n.t("tasks.list_title")))
        self.tasks = QListWidget()
        # NoSelection: highlight selekcji Qt byłby drugim „zaznaczeniem" obok treści (wzorzec F4R2#3);
        # klik = WYŁĄCZNIE gest usera przez itemClicked (F4R#4 — nigdy selection-based).
        self.tasks.setSelectionMode(QListWidget.NoSelection)
        # Liczba = TREŚĆ zadania → prawa kolumna, w kolorze wiersza (`strong=True`), więc wyszarzenie
        # wiersza gasi etykietę i liczbę razem (wiz F5 #6). POGRUBIENIE zdejmuje z wiersza bez roboty
        # rola `rows.STRONG`, ustawiana per wiersz w `refresh_counts` (wiz P1 #6).
        self.tasks.setItemDelegate(TwoPartDelegate(self.tasks, strong=True))
        self.tasks.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)   # elizja zamiast scrolla
        self.tasks.setMaximumWidth(_LIST_MAX_W)
        self.tasks.itemClicked.connect(self._on_task_clicked)
        for key, label, action in _TASKS:
            it = QListWidgetItem(i18n.t(label))
            if action is None:
                # informacyjna (wzorzec app.py — pozycje info): wyszarzona, żeby afordancja nie
                # kłamała w obie strony (wizytator F5 #2 — „wygląda jednakowo, działa różnie")
                it.setFlags(Qt.ItemIsEnabled)
                it.setForeground(_DIM["fg"])
            else:
                it.setData(Qt.UserRole, key)           # akcyjna — handler mapuje klucz → akcja
            self.tasks.addItem(it)
        lv.addWidget(self.tasks)
        # Lista HUGGUJE treść, reszta pionu zostaje pusta BEZ ramki (wizytator P1 tura 2): przy oknie
        # 1400×900 ramka miała 807 px na 60 px treści — ~750 px obramowanej pustki czyta się jako
        # „coś tu miało być". Wysokość z `_fit_task_list` (pomiar, nie stała); stretch trzyma listę
        # przy GÓRZE — centrowanie zerwałoby lewą oś czytania (sidebar + nagłówek na x≈185)
        # i wyglądałoby jak strona www, nie okno Qt.
        lv.addStretch(1)
        self._fit_task_list()
        self.pages.addWidget(list_page)                # _PAGE_LIST

        # strony 1–3: podstrony osi (kolejność MUSI zgadzać się ze stałymi _PAGE_*)
        self.pages.addWidget(self._wrap(i18n.t("tasks.telescope_axis"), self.axis_view))          # _PAGE_TELESCOPE
        self.pages.addWidget(self._wrap(i18n.t("tasks.observatory_axis"), self.observatory_view))   # _PAGE_OBSERVATORY
        self.pages.addWidget(self._wrap(i18n.t("tasks.object_review"), self.object_view))   # _PAGE_OBJECTS

    def _fit_task_list(self):
        """Zetnij wysokość listy zadań do jej treści (suma wysokości wierszy przez delegata + ramka).
        Wołane DWA razy: w budowie (żeby pierwszy paint nie mignął pełną ramką) i w `refresh_counts`
        — dopiero po `show()` metryki fontu są prawdziwe (`sizeHintForRow` przed pokazaniem potrafi
        oddać wartość zastępczą), a `refresh_counts` woła gospodarz właśnie na wejściu w Porządki.
        Idempotentne: ten sam pomiar daje tę samą liczbę, więc powtórne wołanie nic nie rusza.

        WIZ #14: `sizeHintForRow(0) × n` KŁAMAŁO, bo wiersze maluje `TwoPartDelegate` i realna
        wysokość jest większa niż podpowiedź widoku (zmierzone: podpowiedź 13 px przy wierszu
        wyraźnie wyższym) — lista dostawała pasek przewijania przy PIĘCIU pozycjach, mając pod sobą
        ~700 px wolnego pionu. Sumujemy więc wysokości WSZYSTKICH wierszy przez delegata
        (`sizeHintForIndex`), zamiast mnożyć jedną podpowiedź: wiersze nie muszą być równe."""
        n = self.tasks.count()
        if not n:
            return
        model = self.tasks.model()
        wys = sum(self.tasks.sizeHintForIndex(model.index(i, 0)).height() for i in range(n))
        self.tasks.setFixedHeight(wys + 2 * self.tasks.frameWidth())

    def _wrap(self, title, view):
        """Podstrona osi: pasek powrotu + tytuł + widok. Powrót odświeża listę (stan mógł się
        zmienić — user nazwał teleskopy/scalił stanowiska w podstronie)."""
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        back = QPushButton(i18n.t("tasks.back"))
        back.clicked.connect(self._on_back)
        bar.addWidget(back)
        lbl = QLabel(title)
        _f = lbl.font()
        _f.setBold(True)                # tytuł podstrony wybija się nad tekst treści (wizytator #9)
        lbl.setFont(_f)
        bar.addWidget(lbl)
        bar.addStretch(1)
        pv.addLayout(bar)
        pv.addWidget(view, 1)
        return page

    # ---------------------------------------------------------------- odczyt → widok

    def refresh_counts(self):
        """Przeładuj liczniki zadań ze stanu (`queries.tasks_state`) i wyemituj badge
        (`counts_changed` = liczba pozycji akcyjnych z n>0). Woła gospodarz (montaż / po przebiegu
        Dostawy / wejście w Porządki / sygnał stanu Porządków z gestu Zbiorów) i powrót z podstrony."""
        state = queries.tasks_state(self.con)
        state.update(_liczniki_osi(self.con))       # AR-59/AR-41 - od właścicieli predykatów
        # Kopie czekające na fakty, które mogą zmienić te wiersze - WOŁANE, nie powielane: predykat
        # ma jednego właściciela (ten sam SELECT steruje etapem Dostawy), tryb `porownywalne`
        # odcina kandydatów, których fakty żadnego porównania kopii nie ruszą.
        kandydaci = scan.copy_facts_candidates(self.con, porownywalne=True)
        czeka = len(kandydaci)
        badge = 0
        self._niewiadome = set()
        for row, (key, label, action) in enumerate(_TASKS):
            n = state[key]
            # Robota wiersza: ta sama liczba albo jej podzbiór (`_ROBOTA_Z_PODZBIORU`, AR-10).
            robota = state[_ROBOTA_Z_PODZBIORU[key]] if key in _ROBOTA_Z_PODZBIORU else n
            it = self.tasks.item(row)
            czesciowe = czeka > 0 and key in _CZEKA_NA_FAKTY_KOPII
            niewiadome = czesciowe and n == 0
            if niewiadome:
                self._niewiadome.add(key)
            # akcyjne z chevronem „›" — wiersz ZAPRASZA klik; informacyjne bez (wizytator F5 #2).
            # Liczba idzie w CZŁON DRUGI (prawa kolumna, `rows.SECONDARY`), nie w tekst etykiety —
            # inaczej liczby nie ustawiają się w kolumnę i nie da się ich skanować (wiz F5 #6).
            it.setText(i18n.t(label))
            # Człony liczby SKŁADAJĄ SIĘ, nie wykluczają: „robota z liczby" i dolna granica przy
            # kopiach bez faktów mówią o różnych rzeczach. Gdy gałąź „N+" stała przed „z", wiersz
            # po decyzji ręki był szary (robota 0), a liczba mówiła „1+", jakby robota czekała.
            calosc = i18n.t("tasks.of_total", open=robota, total=n) if robota != n else str(n)
            if niewiadome:
                liczba = i18n.t_plural("tasks.copies_unread", czeka)
            elif czesciowe:                 # dolna granica: kopie bez faktów nie są w porównaniu
                liczba = i18n.t_plural("tasks.copies_partial", czeka, m=calosc)
            else:
                liczba = calosc
            it.setData(rows.SECONDARY, f"{liczba}  ›" if action is not None else liczba)
            # Drogi do liczby niesie PODPOWIEDŹ, nie wiersz: wszystkie są warunkowe (plik jest /
            # kopia jest stosem / pliku nie ma), a zdanie z nimi nie mieści się w członie drugim
            # listy 400 px. Zdania składają się w kolejności: gdzie gest, która część liczby ma
            # decyzję ręki, co z kopiami bez faktów; ostatnie mówi, dokąd prowadzi klik („?" -
            # Dostawa, „N+" - Zbiory).
            tip = ""
            if key in _PODPOWIEDZI_GESTU and n > 0:     # przy zerze zdanie o pliku byłoby fałszem
                tip = i18n.t(_PODPOWIEDZI_GESTU[key], finish=i18n.t("grid.inplace.finish"),
                             restore=i18n.t("grid.inplace.restore"),
                             release=i18n.t("grid.inplace.release"))
            elif key in _PODPOWIEDZI_OSI and n > 0:     # ta sama reguła zera co wyżej
                klucz, nazwy = _PODPOWIEDZI_OSI[key]
                tip = i18n.t(klucz, **{k: i18n.t(v) for k, v in nazwy.items()})
            if robota != n:                             # część liczby z decyzją - nie robota
                tip += _zdanie_podzbioru(key, n - robota)
            if czesciowe:
                kopie = zdanie_kopii_bez_zeznania(
                    kandydaci, dest=i18n.t("nav.dostawa" if niewiadome else "nav.zbiory"))
                tip = f"{tip}\n{kopie}" if tip else kopie
            it.setToolTip(tip)
            # Pogrubienie liczby = „TU JEST ROBOTA", więc jest rolą WIERSZA, nie całej listy
            # (wiz P1 #6): wiersz wyszarzony — informacyjny albo akcyjny z n=0 — dostawał
            # pogrubione „0" mimo wyszarzenia, czyli krzyczał dokładnie tam, gdzie nie ma nic
            # do zrobienia. Kolor drugiego członu zostaje bez zmian (jawny `ForegroundRole`
            # dalej obejmuje oba człony — `TwoPartDelegate._own_color`).
            live = action is not None and robota > 0 and key not in _BEZ_ROBOTY
            it.setData(rows.STRONG, live)
            if action is not None:
                # n=0 → wyszarzone, wciąż klikalne. TO SAMO dla wierszy HISTORII (`_BEZ_ROBOTY`)
                # niezależnie od liczby: samo zdjęcie pogrubienia ich nie odróżnia, a „Brakujące
                # kopie 128" stoi obok „Zniknięte z dysku 3" i jest największą liczbą na liście —
                # wzrok czyta większą liczbę jako większy problem, czyli dokładnie odwrotnie do
                # tego, po co ten stan powstał. Szare = „nie ma tu roboty", nie „nie da się kliknąć".
                # „?" NIE jest szare: szarość znaczy „nic do zrobienia", a tu jest - Dostawa.
                it.setForeground(QBrush() if (robota > 0 or niewiadome) and key not in _BEZ_ROBOTY
                                 else _DIM["fg"])
            if live:
                badge += 1
        self._fit_task_list()          # metryki fontu są prawdziwe dopiero po `show()`
        self.counts_changed.emit(badge)
        return badge

    # ---------------------------------------------------------------- akcje

    def _on_task_clicked(self, item):
        key = item.data(Qt.UserRole)
        if key is None:                                # pozycja informacyjna — nie prowadzi nigdzie
            return
        if key in self._niewiadome:                    # „?": robota czeka w Dostawie (AR-28 (b))
            self.open_intake.emit()
            return
        action = next(a for k, _, a in _TASKS if k == key)
        if isinstance(action, int):
            self.pages.setCurrentIndex(action)         # podstrona osi
            if key in _KUBELEK_PODSTRONY:
                self._zaznacz_kubelek(_KUBELEK_PODSTRONY[key])
        else:
            self.open_collection.emit(action)          # Zbiory z perspektywą (np. Duplikaty)

    def otworz_stanowiska(self):
        """Podstrona osi obserwatorium - wejście gospodarza (pusty stan planera „bez stanowiska”)."""
        self.pages.setCurrentIndex(_PAGE_OBSERVATORY)

    def _zaznacz_kubelek(self, tag):
        """Zaznacz kubełek kolejki przeglądu o tagu `tag` - zaznaczenie drąży jego klatki i zapala
        gest (`ObjectAxisView._on_review_selected`). Kubełek pusty nie ma tagu (wiersz informacyjny),
        więc wtedy nic się nie zaznacza: podstrona i jej zdanie „brak klatek" mówią resztę.

        KOLEJKA PRZEŁADOWANA PRZED SZUKANIEM: licznik wiersza jest świeży (`refresh_counts`), a kolejka
        podstrony pamięta stan z ostatniego odświeżenia osi - bez przeładowania klik w „1" szukał
        tagu, którego kolejka jeszcze nie miała. Zaznaczenie jest zdejmowane przed ustawieniem, żeby
        drążenie poszło także wtedy, gdy kubełek był już zaznaczony (lista klatek i gest ze stanu)."""
        self.object_view.refresh()
        lista = self.object_view.review
        for i in range(lista.count()):
            if lista.item(i).data(_REVIEW_TAG) == tag:
                lista.clearSelection()
                lista.setCurrentRow(i)
                return

    def _on_back(self):
        self.pages.setCurrentIndex(_PAGE_LIST)
        self.refresh_counts()                          # stan mógł się zmienić w podstronie
