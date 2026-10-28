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

Świadomy cykl odświeżania: licznik NIE odświeża się na żywo w trakcie pracy w podstronie - liczy go
gospodarz przy montażu, po przebiegu Dostawy, po gestach Zbiorów i na wejściu w Porządki
(`odswiez_przy_wejsciu`), a sam widok przy powrocie „← Porządki" (user mógł nazwać teleskopy w podstronie).
W trybie wątków tła gospodarza KAŻDA z tych dróg liczy w `_LicznikiWorker`; wejście i powrót przy zmienionej
bazie pokazują do wyniku listę NIEAKTUALNĄ (AR-337, rachunek wejścia w tle, `_wygas_wiersze`).

Przy montażu (start GUI, zmiana bazy) i przy każdym wejściu w Porządki widok zleca PRZEGLĄD PLIKÓW OBOK
ŚCIEŻKI w wątku Pythona, na który zamknięcie nie czeka (jeden przegląd na bazę, AR-252): ślady cofnięcia bez
werdyktu (AR-231, `writeback.przejrzyj_slady_cofniecia`) - resztka martwej próby trafia do wiersza „Kopie
zostawione do oka” bez dotyku lokacji - i odczyt obecności kopii zostawionych (`_sprawdz_kopie`, pamięć
`queries.zapamietaj_obecnosc`). To JEDYNY `stat` archiwum Porządków (AR-246): rachunek liczników czyta pamięć
obecności bez I/O. Przegląd ponad limit, porażka i „nie wiem” mówią w wierszu pasywnym z ponowieniem."""
import dataclasses
import os
import sqlite3
import threading
import time

from PySide6.QtCore import QEvent, QItemSelectionModel, QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QStackedWidget, QVBoxLayout,
    QWidget,
)

from horreum import db, repo, resolver, scan, supersede, writeback
from horreum.gui import i18n, queries, rows, theme
from horreum.gui import dostawa_bramka   # napis gestu Dostawy bez modułu Dostawy (AR-337) - moduł bez Qt
from horreum.gui.app import (
    _REVIEW_TAG, ROLA_RODZAJU_KOLORU, ObjectAxisView, ObservatoryAxisView, TelescopeAxisView,
    _utc_now_iso,
)
from horreum.gui.grid import (PRESET_COPY_CONFLICT, PRESET_DUPS, PRESET_F_RATIO_MISMATCH,
                              PRESET_FILE_OBJECT_MISMATCH,
                              PRESET_LINEAGE, PRESET_MISSING_COPY, PRESET_ORPHAN_TESTIMONY,
                              PRESET_PATH_HEADER_CONFLICT, PRESET_PENDING_FINISH, PRESET_RETIRED,
                              PRESET_TORN_WRITE, PRESET_RETIRED_CONFLICT, PRESET_STACK_VERSIONS,
                              PRESET_SUPERSEDED, PRESET_VANISHED, PRESET_WITHHELD_TESTIMONY,
                              PRESET_KEPT_COPIES,
                              zdanie_kopii_bez_zeznania)
from horreum.gui.grid_model import PRESET_LINEAGE_NEWER, PRESET_XREF_RECONCILE
from horreum.gui.grid_model import PRESET_HEADER_NONPRINTABLE   # bajt spoza ASCII (AR-299)
from horreum.gui.rows import TwoPartDelegate
from horreum.gui.wb_worker import EtykietaBledu, tekst_powodu, wiersz_systemu   # zdanie + szczegół (AR-198)
from horreum.item_reasons import powod_bazy, powod_okna

# Definicja listy zadań: (klucz stanu z `tasks_state`, etykieta, akcja). Akcja: numer podstrony
# wewnętrznego stacku (int), nazwa perspektywy Zbiorów (str — sygnał `open_collection`) albo None
# (pozycja INFORMACYJNA — bez powierzchni akcji). Wiersze AKCYJNE (akcja ≠ None) z n>0 liczą się do
# badge'a sidebara — informacja nie jest zadaniem. „Zniknięte" AWANSOWAŁY z informacji na akcję wraz
# z passem obecności (P5/#7): dopóki nie było przebiegu wykrywającego, liczba była martwa i nie było
# jej gdzie rozwinąć — teraz prowadzi do perspektywy z listą klatek bez ani jednej obecnej kopii.
# Wiersz „XISF (nagłówki tylko do odczytu)" ZNIKNĄŁ w P6c: pisarz XISF istnieje, więc zdanie było
# już nieprawdą, a sam licznik plików danego formatu nie jest robotą do zrobienia (facet formatu
# w Zbiorach mówi to samo, w miejscu, gdzie się o to pyta).
# Wiersz „Rodowód do potwierdzenia" (nazwa perspektywy, którą otwiera - jeden zbiór, jedna nazwa)
# DOSZEDŁ 0808 i celuje w PERSPEKTYWĘ, nie w podstronę - bo gest
# (potwierdź / odrzuć wejście / wskaż odniesienie czasu) mieszka w panelu „Rodowód" w Zbiorach
# i działa z zaznaczenia jednej klatki. Do tej zmiany liczba istniała wyłącznie w raporcie etapu
# Dostawy, a droga od niej do konkretnego obrazu wiodła przez przeklikanie całego archiwum stosów.
_PAGE_LIST, _PAGE_TELESCOPE, _PAGE_OBSERVATORY, _PAGE_OBJECTS = range(4)
# Cel wiersza, który nie jest ani podstroną (int), ani perspektywą (nazwa presetu): okno na
# przebiegu gestu zmiany obiektu - sygnał `open_object_change_run` z `run_id` (AR-121).
_OKNO_PRZEBIEGU = ("okno", "object_change_run")
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
# RODZAJ KOLORU WIERSZA (AR-175), zapisany przy budowie i przy każdym rachunku w roli
# `app.ROLA_RODZAJU_KOLORU`: zmiana motywu przemalowuje listę z tej roli (`odswiez_motyw`) zamiast
# liczyć stan bazy od nowa (1,4-2,6 s na kopii pf4). Rola `rows.STRONG` tego nie niesie: „?” i zero
# mają ją obie `False`, a pierwszy jest w kolorze tekstu, drugie - szare.
_RODZAJ_ZYWY, _RODZAJ_NIEWIADOME = "zywy", "niewiadome"           # kolor tekstu
_RODZAJ_ZERO, _RODZAJ_HISTORIA, _RODZAJ_INFORMACYJNY = "zero", "historia", "informacyjny"   # szare
_RODZAJE_SZARE = frozenset({_RODZAJ_ZERO, _RODZAJ_HISTORIA, _RODZAJ_INFORMACYJNY})
# Szerokość listy zadań. Prawe wyrównanie liczb SKANUJE się w wąskim pasie i ROZJEŻDŻA na szerokim:
# przy oknie 1200 px etykieta lądowała na x≈185, a liczba na x≈1180 — ~900 px pustki między nimi
# (wizytator P1 #2, dług delegata przeniesionego z listwy 220 px na pełną szerokość okna).
# Liczba z POMIARU TREŚCI, nie z oka: najdłuższa etykieta ≈ 172 px (pomiar na „XISF (nagłówki tylko
# do odczytu)", wiersz zdjęty w P6c — po nim etykiety są KRÓTSZE, więc zapas tylko urósł)
# + najszerszy człon drugi („381  ›") = 35 px + `_GAP`/`_PAD` ≈ 230 px. 400 px daje oddech bez
# rozjeżdżania; przy 520 px wzrok znów gubi drogę etykieta→liczba (wizytator P1 tura 2).
_LIST_MAX_W = 400
# PODŁOGA LISTY ZADAŃ W WIERSZACH (AR-188), nie w pikselach - wiersz maluje delegat, jego wysokość
# zależy od fontu i DPI. Lista ponad tę liczbę przewija się, gdy okno jest niskie; przy wolnym pionie
# pokazuje całą treść (sufit = treść). LICZBA Z POMIARU (natywnie, 100 %, wiersz 18 px): podłogę okna
# wyznaczała dotąd ta lista (27 wierszy: strona 530 px, okno 608 px); przy podłodze do 21 wierszy
# strona listy schodzi poniżej podstron osi Porządków (439 px) i Planera (440 px), a okno - do 518 px
# niezależnie od liczby wierszy. 18 zostawia zapas 4 wierszy (72 px), żeby inny font albo skala nie
# przywróciły zależności; przy oknie na podłodze lista i tak dostaje ~22 wiersze (stretch do treści).
# Ta sama liczba co `app._KOLEJKA_SUFIT_WIERSZY`, ale inny fakt (tam sufit, tu podłoga).
_LISTA_ZADAN_MIN_WIERSZY = 18
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
    # Wiersz AKCYJNY i ROBOTA (AR-17 krok 3) - ta sama oś, trzeci stan: klatka MA obiekt, a jej
    # plik leży w folderze innego obiektu albo karta `OBJECT` mówi inną formą (E5-1: folderami
    # zarządza Horreum). Gest „Uzgodnij pliki…" mieszka w menu prawego kliku perspektywy, więc
    # wiersz prowadzi do niej, a podpowiedź mówi, gdzie gest. Liczba i lista czytają jeden predykat
    # (`queries.file_object_mismatch_frame_ids`, licznik w `_liczniki_osi`).
    ("file_object_mismatch_frames", "tasks.file_object_mismatch_frames",
     PRESET_FILE_OBJECT_MISMATCH),
    # Wiersz AKCYJNY i ROBOTA (AR-135) - ta sama oś, czwarty stan: klatka MA obiekt, ale para
    # `catalog_xref` dopisana po fakcie mówi, że jej obiekt to stara tożsamość celu pary (`M33`
    # obok `NGC598`). Gest „Zmień obiekt…” na klatkach z perspektywy; cel podaje podpowiedź.
    # Liczba, lista i zdanie czytają jeden predykat (`queries.xref_reconcile_rows`).
    ("xref_reconcile_frames", "tasks.xref_reconcile_frames", PRESET_XREF_RECONCILE),
    # Wiersz AKCYJNY i ROBOTA (AR-121) - liczy PRZEBIEGI, nie klatki: gest „Zmień obiekt…” albo
    # „Uzgodnij pliki…”, który nie doszedł do końca (przerwanie, awaria procesu, pozycja w stanie
    # częściowym). Do tego wiersza drogą powrotu po zamknięciu okna było wyłącznie CLI z numerem
    # przebiegu ze zdania wyniku. Klik otwiera okno na najstarszym przebiegu (`_OKNO_PRZEBIEGU`
    # - gospodarz woła Zbiory, które trzymają mutex zapisu); liczba i wejście czytają jeden
    # predykat (`queries.interrupted_object_change_runs`, licznik w `_liczniki_osi`).
    ("object_change_interrupted", "tasks.object_change_interrupted", _OKNO_PRZEBIEGU),
    # Wiersz AKCYJNY i ROBOTA (AR-318) - ta sama rodzina „gest nie doszedł do końca”: liczy COMMITY
    # kart, których cofnięcie się zaczęło i nie skończyło (zamknięcie okna w biegu, awaria procesu,
    # plik zablokowany). Recepta paska „Cofnij zapis (commit N)” ginie z programem; ten wiersz czyta
    # STAN (`queries.niedokonczone_cofniecia_kart`, licznik w `_liczniki_osi`), a klik prowadzi na
    # podstronę osi obiektu z receptą „Dokończ cofnięcie (commit N)” najstarszego commitu.
    ("undo_unfinished", "tasks.undo_unfinished", _PAGE_OBJECTS),
    ("stacks_lineage_pending", "tasks.stacks_lineage", PRESET_LINEAGE),
    # Wiersz AKCYJNY i ROBOTA (AR-153, `D-1016-1`) - liczy OBRAZY, których werdykt ręki potwierdził
    # klatki zrobione po zapisie stosu (nie mogły do niego wejść). Gest „Odrzuć nowsze niż obraz"
    # mieszka w panelu „Rodowód" w Zbiorach i działa z zaznaczenia jednego obrazu, więc wiersz prowadzi
    # do perspektywy tych obrazów; podpowiedź mówi, ile wejść czeka i gdzie gest. Liczba i lista czytają
    # jeden predykat (`queries.lineage_newer_inputs`, licznik w `_liczniki_osi`).
    ("lineage_newer", "tasks.lineage_newer", PRESET_LINEAGE_NEWER),
    # Dwa wiersze AKCYJNE i ROBOTA (AR-59) - liczą KLATKI, które czekają na gest ręki na osi
    # sprzętu i na osi stanowiska. Do tej zmiany gesty istniały, ale prowadziły do nich wiersze
    # liczące co innego (teleskopy bez etykiety, stanowiska bez nazwy) - szare „0" mówiło „nie ma
    # roboty" przy 423 klatkach bez zestawu i 1223 bez stanowiska. Liczba czyta predykat jedynego
    # właściciela (`_liczniki_osi`), a klik prowadzi do podstrony z gestem.
    ("config_review_frames", "tasks.config_review_frames", _PAGE_OBJECTS),
    # Dwa wiersze AKCYJNE i ROBOTA optyki teleskopu (AR-128 `Q8`, AR-129), pod kubełkiem sprzętu,
    # bo to ta sama oś. „Ogniskowa niezgodna" prowadzi do podstrony z gestem „Przypisz zestaw…"
    # (wybór z teleskopów w tolerancji albo nowy - program sam teleskopu nie zakłada, D-1012-2),
    # „f/ niezgodna" do perspektywy z gestem naprawy pliku w menu prawego kliku. Liczby czytają
    # jeden predykat (`resolver.optics_mismatch_frame_ids`).
    ("focal_mismatch_frames", "tasks.focal_mismatch_frames", _PAGE_OBJECTS),
    ("f_ratio_mismatch_frames", "tasks.f_ratio_mismatch_frames", PRESET_F_RATIO_MISMATCH),
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
    # Wiersz AKCYJNY i ROBOTA (AR-82) - ta sama rodzina pytań o kopię wiodącą, trzeci stan: plik
    # kopii ZAPISANY (karta albo cofnięcie), a zeznanie klatki nie przyjęło jego nagłówka, bo głosem
    # mówi inna obecna kopia. Kopie bywają zgodne w polach, które porównują dwa wiersze wyżej, więc
    # bez tego wiersza zapis czekałby niewidoczny. Gest „Ta kopia prowadzi" na zapisanej kopii
    # dokańcza zapis (wpisy, nagrobek, pozycja gestu). Liczba, lista i dostępność gestu czytają
    # jeden predykat (`queries.withheld_testimony_frame_ids`).
    ("withheld_testimony_frames", "tasks.withheld_testimony_frames", PRESET_WITHHELD_TESTIMONY),
    # Wiersz AKCYJNY i ROBOTA (AR-64): rekoncyliacja przerwanej podmiany nie mogła dowieść stanu
    # plików pełnym sha1 i zostawiła kopie obok ścieżki - człowiek porównuje je z plikiem i usuwa
    # zbędne; wiersz pustoszeje sam, gdy plików nie ma. Skan tych kopii nie widzi (sufiks), więc
    # bez wiersza zostawałyby niewidoczne. Liczba i lista czytają jeden predykat
    # (`queries.kept_copy_frame_ids`).
    ("kept_copy_frames", "tasks.kept_copy_frames", PRESET_KEPT_COPIES),
    # Wiersz AKCYJNY (0022, Q8): kopia po przerwanym zapisie nagłówka w miejscu, izolowana od skanu.
    # Robota człowieka: odzysk z dziennika operacji albo zwolnienie po własnym rozstrzygnięciu.
    ("torn_write_frames", "tasks.torn_write_frames", PRESET_TORN_WRITE),
    # Wiersz AKCYJNY i ROBOTA (AR-17 (1)): zapis w miejscu zweryfikowany, a baza jeszcze go nie
    # wciągnęła - kopia izolowana od skanu tak samo jak po przerwanym zapisie, ale robotą jest
    # dokończenie („Dokończ zapis" w Zbiorach). Bez tego wiersza taka lokacja była niewidoczna,
    # a skan ją pomijał. Stoi pod sąsiadem, bo to druga połowa tej samej izolacji.
    ("pending_finish_frames", "tasks.pending_finish_frames", PRESET_PENDING_FINISH),
    # Wiersz AKCYJNY i ROBOTA (AR-299) - ta sama rodzina co dwa wyżej (zapis nagłówka), inna przyczyna:
    # kopia FITS ma w surowym nagłówku bajt spoza drukowalnego ASCII, więc pisarz odmawia zapisu
    # i cofnięcia. Naprawa jest poza Horreum (program, który zapisał plik) - podpowiedź mówi to wprost.
    # Liczba i perspektywa czytają jeden predykat (`resolver.nonprintable_frame_ids`). Kopie, których
    # surowych bajtów jeszcze nie zbadano (0046 - stare kopie do pierwszej Dostawy), wiersz mówi „?”
    # / „N+”, nie zero (`_NIEZBADANE_WIERSZA`).
    ("header_nonprintable_frames", "tasks.header_nonprintable_frames", PRESET_HEADER_NONPRINTABLE),
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
    # jeden predykat grupy (`queries._zbiory_wersji`, także grupy z werdyktem - tam się go widzi
    # i cofa), a robotą jest podzbiór grup BEZ werdyktu (`_ROBOTA_Z_PODZBIORU`). Liczba mówi GRUPY,
    # lista pod klikiem ich stosy (odbiór 0.19.0 PO13, `_LICZBA_GRUP`). Do 0026 wiersz stał
    # w `_BEZ_ROBOTY`, bo bez werdyktu świeciłby wiecznie po prawowitej decyzji.
    ("stack_versions", "tasks.stack_versions", PRESET_STACK_VERSIONS),
]

# WIERSZE, KTÓRYCH ROBOTA JEST PODZBIOREM LICZBY (AR-10): klucz wiersza → klucz licznika roboty
# w `queries.tasks_state`. Liczba i lista pod klikiem czytają jeden predykat; plakietkę,
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

# WIERSZE, KTÓRYCH LICZBA MÓWI W INNEJ JEDNOSTCE NIŻ LISTA POD KLIKIEM (odbiór 0.19.0 PO13): klucz
# wiersza → (zdanie całości, zdanie „robota z całości"), oba w odmianie przez całość. „Wersje stosów"
# liczą grupy (decyzja zapada o grupie), a perspektywa pokazuje ich stosy - goła liczba „12" obok
# listy 53 stosów wyglądałaby na błąd, więc człon liczby nazywa jednostkę. Przy robocie równej całości
# zostaje sama całość z jednostką („12 grup"), jak goła liczba reszty listy: „12 z 12" udawałoby
# podział, którego nie ma.
_LICZBA_GRUP = {"stack_versions": ("tasks.stack_versions_groups", "tasks.stack_versions_groups_of")}


def _czlon_calosci(key, robota, n):
    """Człon liczby wiersza `key`: całość albo „robota z całości" (`_ROBOTA_Z_PODZBIORU`), z jednostką
    tam, gdzie lista pod klikiem liczy co innego (`_LICZBA_GRUP`)."""
    if key in _LICZBA_GRUP:
        calosc, z_calosci = _LICZBA_GRUP[key]
        return (i18n.t_plural(z_calosci, n, open=robota) if robota != n
                else i18n.t_plural(calosc, n))
    return i18n.t("tasks.of_total", open=robota, total=n) if robota != n else str(n)

# TRZECI STAN WIERSZA: KLIKALNY, ALE NIE ROBOTA. Do 0809 lista znała dwa — informacyjny (cel `None`,
# nie prowadzi nigdzie) i akcyjny (cel jest, liczba > 0 znaczy „tu jest robota"). Wiersz „Zastąpione"
# nie mieści się w żadnym: MA dokąd prowadzić, ale jego liczba nigdy nie jest zadaniem.
# Bez tego zbioru wpadał do odznaki sidebara i dostawał pogrubienie „TU JEST ROBOTA" — czyli tylnymi
# drzwiami odtwarzał dokładnie ten defekt, który pakiet kolejki wyleczył w kubełkach (bramka 3a
# 0809, zarzut `kimi` #4). Klucz, nie flaga w krotce: krotka opisuje POZYCJĘ, a to jest fakt o jej
# NATURZE, i tak samo czyta go badge, jak i pogrubienie.
_BEZ_ROBOTY = frozenset({"superseded_frames", "retired_frames", "missing_copy_frames",
                         "object_kept_frames"})


def _liczniki_osi(con, *, niezbadane=None):
    """Liczniki wierszy AR-59/AR-41, których `queries.tasks_state` nie niesie - WOŁANE od jedynych
    właścicieli predykatów, nie powielane (ten plik nie wykonuje SQL):

      * `config_review_frames` = `resolver.review_state(con).no_config` - właściciel kubełka sprzętu
        kolejki przeglądu (kind-aware: dark/bias z `grouper.NO_TELESCOPE_KINDS` nie mają zestawu
        z definicji; klatka bez zeznania i zastąpiona/wycofana poza). Lista pod klikiem
        (`queries.config_review_frames`) jest jego lustrem pinowanym testem.
      * `observatory_review_frames` = długość wejścia gestu „Wskaż stanowisko…"
        (`queries.observatory_review_frames`) - dokładnie tyle, ile okno gestu pokaże. Dark i bias
        z masterami (`grouper.NO_TELESCOPE_KINDS`) są poza liczbą i poza oknem (AR-80): nie widzą
        nieba, więc stanowisko nie jest dla nich robotą; ten sam predykat liczy licznik na
        przycisku gestu (`ObservatoryAxisView`), więc trzy liczby nie mogą się rozjechać.
      * `object_kept_frames` = `supersede.kept_object_facts` (AR-41).
      * `copy_conflict_open` = klatki „Kopii niezgodnych" BEZ decyzji ręki (AR-23) - robota
        wiersza (`_ROBOTA_Z_PODZBIORU`). Decyzję czyta `queries.hand_testimony_frame_ids` (jeden
        właściciel pytania „czyj głos niesie `header`"): gest „Ta kopia prowadzi" zostawia
        `header.adopted` z aktorem `user:local`. Zapis nagłówka w miejscu odmawia przy kilku
        obecnych kopiach (`macro`, D-W1), więc ręka na klatce z rozjazdem kopii to ten gest.
      * `file_object_mismatch_frames` = `queries.file_object_mismatch_frame_ids` (AR-17 krok 3) -
        ten sam predykat, który przycina perspektywę pod klikiem (lista = liczba).
      * `object_change_interrupted` = przebiegi z `queries.interrupted_object_change_runs`
        (AR-121) - ta sama lista, z której klik bierze przebieg do okna.
      * `undo_unfinished` = commity z `queries.niedokonczone_cofniecia_kart` (AR-318) - ta sama
        lista, z której klik bierze commit do recepty „Dokończ cofnięcie”.
      * `xref_reconcile_frames` = klatki pozycji `queries.xref_reconcile_rows` (AR-135), a obok
        pary „nazwa → cel” do zdania podpowiedzi (`xref_reconcile_pairs`) - jeden odczyt.
      * `lineage_newer` = obrazy z `queries.lineage_newer_inputs` (AR-153) - ten sam zbiór, co trim
        perspektywy pod klikiem; obok liczba ich wejść do odrzucenia (`lineage_newer_inputs`) do
        zdania podpowiedzi - jeden odczyt.

    `niezbadane` - wiersze `resolver.nonprintable_unread_locations` przeczytane już przez wołającego
    (`_stan_licznikow`, AR-352); bez nich `review_state` czyta je sam.

    Pomiar 2026-10-06 na kopii żywej bazy: 423 bez zestawu (422 light RAW bez TELESCOP w EXIF,
    1 `unknown` XISF), 1223 bez stanowiska, 0 zatrzymanych faktów. Po AR-80 (kopia v36,
    2026-10-13): 1185 bez stanowiska - z 1223 zeszło 38 `master_dark`."""
    niezgodne = queries.copy_conflict_frame_ids(con)
    stan = resolver.review_state(con, niezbadane=niezbadane)
    xref = queries.xref_reconcile_rows(con)
    nowsze = queries.lineage_newer_inputs(con)
    return {
        # AR-153: obrazy i ich wejścia do odrzucenia - jeden odczyt predykatu.
        "lineage_newer": len(nowsze),
        "lineage_newer_inputs": sum(len(w) for w in nowsze.values()),
        # AR-135: liczba klatek i pary „nazwa → cel” do zdania podpowiedzi - jeden odczyt predykatu.
        "xref_reconcile_frames": len(set().union(*(f for _n, _c, _t, f in xref))),
        "xref_reconcile_pairs": tuple(dict.fromkeys(f"{n} → {t}" for n, _c, t, _f in xref)),
        "config_review_frames": stan.no_config,
        # AR-128/AR-129: dwa kubełki optyki - właściciel predykatu `resolver.optics_mismatch_frame_ids`
        # (lista pod klikiem czyta TEN SAM zbiór; poza `total` kolejki przeglądu).
        "focal_mismatch_frames": stan.focal_mismatch,
        "f_ratio_mismatch_frames": stan.f_ratio_mismatch,
        # AR-299: klatki z bajtem i kopie niezbadane - właściciel `resolver`, ta sama migawka.
        "header_nonprintable_frames": stan.header_nonprintable,
        "header_nonprintable_unread": stan.header_nonprintable_unread,
        "observatory_review_frames": len(queries.observatory_review_frames(con)),
        "object_kept_frames": len(supersede.kept_object_facts(con)),
        "copy_conflict_open": len(niezgodne - queries.hand_testimony_frame_ids(con, niezgodne)),
        "file_object_mismatch_frames": len(queries.file_object_mismatch_frame_ids(con)),
        "object_change_interrupted": len(queries.interrupted_object_change_runs(con)),
        "undo_unfinished": len(queries.niedokonczone_cofniecia_kart(con)),
    }


def _stan_licznikow(con):
    """Komplet faktów listy zadań ze STANU bazy: `(liczniki, kandydaci)` - liczniki `tasks_state`
    z licznikami osi (`_liczniki_osi`) i kopie czekające na fakty, które mogą zmienić wiersze
    `_CZEKA_NA_FAKTY_KOPII`. Bez widżetów: ten sam kod liczy wątek GUI (`refresh_counts`) i wątek
    tła (`_LicznikiWorker`) na własnym połączeniu. Predykat kopii ma jednego właściciela (ten sam
    SELECT steruje etapem Dostawy), tryb `porownywalne` odcina kandydatów, których fakty żadnego
    porównania kopii nie ruszą.

    Kopie niezbadane wiersza bajtów (AR-327): podpowiedź nazywa gest Dostawy jego napisem
    (`dostawa_bramka.etykieta_gestu_kopii` - moduł bez Qt, lista Porządków nie importuje modułu Dostawy, AR-337),
    a napis zależy od obu robót - `scan.copy_facts_waiting` liczy się tylko, gdy wiersz ma kopie niezbadane.
    Zmierzone natywnie na kopii pf4 zaraz po migracji 0046: 59-143 ms z 964-1271 ms całego rachunku (7 %); napis
    zastępczy z samego licznika niezbadanych kłamałby przy faktach i bajtach naraz (test AR-327
    `test_podpowiedz_wiersza_bajtow_nazywa_przycisk_dostawy`), więc ten rachunek zostaje w obu trybach.

    JEDEN ODCZYT KOPII NIEZBADANYCH (AR-352): licznik wiersza bajtów (`resolver.review_state`) i napis gestu
    (`scan.copy_facts_waiting`) biorą TE SAME wiersze `resolver.nonprintable_unread_locations`, przeczytane raz i podane
    obu właścicielom parametrem - dawniej każdy czytał je sam (2 odczyty po 70-95 ms na kopii pf4 v47 przy 15 598
    kopiach niezbadanych), więc liczba i napis mogły pochodzić z dwóch chwil. Złożenie robót zostaje w `scan`.

    Gdzie biegnie: w trybie wątków tła gospodarza KAŻDA droga (montaż, gesty, koniec Dostawy, wejście i powrót - AR-337
    `M`) liczy w `_LicznikiWorker`, w jednej migawce; na wątku GUI liczy wyłącznie tryb bez wątków (widok samodzielny,
    seam testów) i rachunek awaryjny `refresh_counts`."""
    niezbadane = resolver.nonprintable_unread_locations(con)
    state = queries.tasks_state(con)
    state.update(_liczniki_osi(con, niezbadane=niezbadane))       # AR-59/AR-41 - od właścicieli predykatów
    if state.get("header_nonprintable_unread"):
        state["copy_facts_waiting"] = scan.copy_facts_waiting(con, niezbadane=niezbadane)
    return state, scan.copy_facts_candidates(con, porownywalne=True)


class _LicznikiWorker(QObject):
    """Liczniki Porządków POZA wątkiem GUI (AR-84) - bliźniak `home.TeczkiWorker`, ten sam cykl.

    Zmierzone przed tą zmianą: ogon gestu kopii w Zbiorach stał w `refresh_counts` 557 ms
    (wizytator, kopia pf4), bo plakietka sidebara liczy się po KAŻDYM geście gridu
    (`stan_porzadkow_changed`). Tu `_stan_licznikow` idzie na WŁASNYM połączeniu otwartym w tym
    wątku (sqlite `check_same_thread`), a slot widoku tylko przykłada wynik do listy.

    ANULOWANIE PRZERYWA SAMO ZAPYTANIE (AR-175, wzór `grid_workers.PolaWorker`): rachunek to kilka
    zapytań po ~0,2-0,3 s na kopii pf4, a przełączenie bazy i zamknięcie okna czekały na jego koniec.
    `request_cancel` (wątek GUI) stawia flagę i woła `Connection.interrupt` pod zamkiem, który pilnuje
    publikacji i zamknięcia połączenia; flaga sprawdzana PO otwarciu połączenia łapie anulowanie
    sprzed jego powstania. Przerwanie leci jako `failed` ze starą generacją - odbiorca je odrzuca.

    JEDNA MIGAWKA (AR-337): rachunek to kilkadziesiąt SELECT-ów, a `db.connect` transakcji nie otwiera (każdy SELECT
    w autocommit) - liczba wiersza i jej podpowiedź mogły pochodzić z różnych chwil bazy. `BEGIN` przed rachunkiem (wzór
    `grid_workers.PolaWorker`) daje wszystkim odczytom jedną migawkę WAL, a zamknięcie połączenia zwalnia ją każdą drogą
    (wynik, wyjątek, przerwanie). Koszt: czytelnik przez czas rachunku (~1 s na kopii pf4) wstrzymuje postęp checkpointu
    WAL ponad swoją migawkę - zapis Dostawy idzie dalej, plik WAL rośnie do końca rachunku."""

    done = Signal(int, object)     # generacja, `(liczniki, kandydaci)`
    failed = Signal(int, object)   # generacja, powód (`powod_okna`: klasa bazy/systemu albo błąd programu)
    finished = Signal()            # run() wrócił KAŻDĄ drogą → quit wątku

    def __init__(self, gen, db_path):
        super().__init__()
        self._gen = gen
        self._db_path = db_path
        self._con = None
        self._zamek = threading.Lock()
        self._cancel = threading.Event()

    def request_cancel(self):
        """Wołane z wątku GUI: flaga + przerwanie zapytania w locie (patrz docstring klasy)."""
        self._cancel.set()
        with self._zamek:
            if self._con is not None:
                self._con.interrupt()

    @Slot()
    def run(self):
        try:
            with self._zamek:
                self._con = db.connect(self._db_path)
            try:
                if self._cancel.is_set():
                    raise sqlite3.OperationalError("interrupted")
                self._con.execute("BEGIN")        # jedna migawka WAL na cały rachunek (docstring klasy)
                wynik = _stan_licznikow(self._con)
            finally:
                with self._zamek:
                    self._con.close()      # PRZED emisją - wątek GUI czyta przez swoje połączenie
                    self._con = None
            self.done.emit(self._gen, wynik)
        except Exception as exc:           # szczerze do widoku, nie cicha śmierć wątku
            # Jedna reguła wyjątku okna (`powod_okna`, AR-264): klasa bazy albo systemu, inaczej
            # błąd programu z miejscem w kodzie - liczony tu, w wątku, póki ślad jest pełny.
            self.failed.emit(self._gen, powod_okna(exc))
        finally:
            self.finished.emit()


# Okres odczytu wyniku przeglądu plików obok ścieżki (AR-231) w wątku GUI.
_PRZEGLAD_TAKT_MS = 250
# PRZEGLĄD DŁUŻSZY NIŻ PRÓG mówi w wierszu pasywnym „trwa” (AR-252), zamiast milczeć jak „brak śladów”.
# Zdrowy przegląd to SQL + jeden `stat` na nazwę (0,03 ms na `R:`, komentarz `writeback._rekoncyliuj_slady`),
# więc 3 s jest o rzędy nad zdrowym biegiem, a pod limitem sesji klienta SMB, na który czeka `stat` zerwanego
# udziału - przy dysku sprawnym wiersz nie mignie.
_PRZEGLAD_LIMIT_S = 3.0


@dataclasses.dataclass(eq=False)
class _Przeglad:
    """Jedno zlecenie przeglądu (`_przeglad_slady`): wątek, chwila startu (`time.monotonic`), bilet startu
    (`queries.bilet_obecnosci` - próg zaufania czytelnika, gdy zlecenie wisi), `pelny` - czy przegląda też ślady
    cofnięcia (montaż, ponowienie) czy wyłącznie kopie zostawione (wejście w Porządki), zdarzenie końca i wynik -
    `(PrzegladSladow, {nazwa kopii: odczyt path_gone}, czy pamięć obecności zmieniła wartość)` albo powód
    porażki. Wynik pisze wątek PRZED `gotowe.set()`, czyta wątek GUI po nim."""
    watek: threading.Thread | None = None
    start: float = 0.0
    bilet: int = 0
    pelny: bool = True
    gotowe: threading.Event = dataclasses.field(default_factory=threading.Event)
    wynik: object = None


# JEDEN PRZEGLĄD NA BAZĘ (AR-252): `stat` zerwanego udziału zawiesza wątek przeglądu do końca procesu (nie da
# się go przerwać), więc kolejny montaż, wejście w Porządki albo ponowienie PODPINA się pod żywy wpis zamiast
# zakładać drugi wątek z własnym połączeniem. Klucz = ścieżka bazy (`queries.klucz_bazy`). Wpisów nikt nie
# sprząta: gotowy zastępuje następne zlecenie, a widok trzyma SWÓJ wpis, więc zastąpienie w rejestrze nie odbiera
# mu wyniku. Plik bazy skasowany i założony od nowa pod tą samą ścieżką dostałby wiszący przegląd starego pliku -
# na Windows otwarte połączenie wątku blokuje skasowanie, więc skutek kończy się na jednym wiszącym przeglądzie.
_PRZEGLADY: dict = {}


def _sprawdz_kopie(con):
    """Odczyt obecności kopii zostawionych do oka (AR-246): każda nazwa `queries.kept_copy_names` raz
    `scan.path_gone`, z biletem wziętym PRZED odczytem, do pamięci obecności (`queries.zapamietaj_obecnosc` -
    nowszy odczyt wygrywa). Zapis odczyt po odczycie: zawieszenie na N-tej nazwie zostawia w pamięci
    poprzednie. Zwraca `({nazwa: True | False | None}, czy pamięć zmieniła wartość)` tego przeglądu."""
    wyniki, zmiana = {}, False
    for _fid, sciezki in queries.kept_copy_names(con):
        for s in sciezki:
            if s in wyniki:
                continue
            bilet = queries.bilet_obecnosci()
            wyniki[s] = scan.path_gone(s)
            zmiana = queries.zapamietaj_obecnosc(s, bilet, wyniki[s]) or zmiana
    return wyniki, zmiana


def _przeglad_slady(db_path, now, zlecenie):
    """PRZEGLĄD PLIKÓW OBOK ŚCIEŻKI w WĄTKU PYTHONA: własne połączenie (`db.connect`), przy zleceniu `pelny`
    ślady cofnięcia bez werdyktu (`writeback.przejrzyj_slady_cofniecia`, AR-231) i - po nich, więc ślad, który
    przegląd właśnie postawił w `kept`, już się liczy - odczyt obecności kopii zostawionych (`_sprawdz_kopie`).
    Zlecenie z wejścia w Porządki (`pelny=False`) śladów NIE przegląda: obserwator przy wejściu widziałby ślad
    żywego cofnięcia tego procesu (nawigacja nie gaśnie przy zapisie) i odbierałby właścicielowi `clean`.
    Wynik albo powód porażki (`powod_okna` - klasa błędu systemu albo bazy, błąd programu) do zlecenia,
    połączenie zamknięte, próg zaufania tego zlecenia zdjęty, potem `gotowe` - KAŻDĄ drogą (`finally`), żeby
    zlecenie nie wisiało w „trwa” po błędzie samego sprzątania. Nie dotyka obiektów Qt - widok czyta zlecenie
    timerem w wątku GUI. Wątek, nie `QThread`: zamknięcie okna i zmiana bazy NIE czekają na przegląd (`stat`
    na zerwanym udziale potrafi wisieć), a `QThread` skasowany z widokiem w biegu to twardy abort aplikacji."""
    wynik = None
    try:
        con = None
        try:
            con = db.connect(db_path)
            slady = (writeback.przejrzyj_slady_cofniecia(con, now=now) if zlecenie.pelny
                     else writeback.PrzegladSladow())
            wynik = (slady, *_sprawdz_kopie(con))
        except Exception as exc:  # noqa: BLE001 - porażka idzie do widoku powodem, nie cicho
            wynik = powod_okna(exc)
        finally:
            if con is not None:
                con.close()
    finally:
        queries.zdejmij_prog_obecnosci(db_path, zlecenie.bilet)
        zlecenie.wynik = wynik
        zlecenie.gotowe.set()


# Wiersz, którego podstrona ma kilka kubełków: klik ZAZNACZA właściwy, żeby lista klatek i gest
# stały gotowe (klucz wiersza → tag kubełka kolejki przeglądu `ObjectAxisView`).
_KUBELEK_PODSTRONY = {"config_review_frames": "config_review",
                      "focal_mismatch_frames": "config_focal"}

# Podpowiedzi wierszy AR-59/AR-41 - mówią, gdzie mieszka gest (nazwy z katalogu przy renderze).
_PODPOWIEDZI_OSI = {
    "config_review_frames": ("tasks.config_review_tip", {"assign": "object.set_config_btn"}),
    "focal_mismatch_frames": ("tasks.focal_mismatch_tip", {"assign": "object.set_config_btn"}),
    "f_ratio_mismatch_frames": ("tasks.f_ratio_mismatch_tip", {"fix": "grid.optics.fix_action"}),
    "observatory_review_frames": ("tasks.observatory_review_tip",
                                  {"assign": "obshand.btn_assign"}),
    "object_kept_frames": ("tasks.object_kept_tip", {"persp": "perspective.superseded"}),
    # AR-23: gest „Ta kopia prowadzi" mieszka w menu prawego kliku w Zbiorach - wiersz mówi, gdzie.
    "copy_conflict_frames": ("tasks.copy_conflict_tip", {"lead": "grid.lead.menu"}),
    "orphan_testimony_frames": ("tasks.orphan_testimony_tip", {"lead": "grid.lead.menu"}),
    "withheld_testimony_frames": ("tasks.withheld_testimony_tip", {"lead": "grid.lead.menu"}),
    "kept_copy_frames": ("tasks.kept_copy_tip", {}),
    # AR-17 krok 3: „Uzgodnij pliki…" mieszka w menu prawego kliku perspektywy.
    "file_object_mismatch_frames": ("tasks.file_object_mismatch_tip",
                                    {"align": "grid.sel.object_change_align"}),
    # AR-121: klik otwiera okno przebiegu - podpowiedź mówi, co tam czeka.
    "object_change_interrupted": ("tasks.object_change_interrupted_tip", {}),
    # AR-318: klik stawia receptę dokończenia na pasku - podpowiedź mówi, co ona zrobi.
    "undo_unfinished": ("tasks.undo_unfinished_tip", {}),
    # AR-157: droga od klatki z kilkoma obecnymi kopiami do jednej - JEDNA recepta; okno zmiany
    # obiektu przywołuje ten sam wpis przy pominięciu `many_copies` (`object_change_dialog`).
    "dup_frames": ("tasks.dup_frames_tip", {"persp": "perspective.dups", "place": "nav.dostawa",
                                            "check": "pipeline.btn.presence",
                                            "mark": "pipeline.btn.mark_vanished"}),
    # AR-299: naprawa poza Horreum - podpowiedź mówi, gdzie i kiedy skan zobaczy plik ponownie.
    "header_nonprintable_frames": ("tasks.header_nonprintable_tip", {}),
}

# WIERSZE Z KOPIAMI NIEZBADANYMI (AR-299, 0046): klucz wiersza → klucz licznika kopii, których surowych
# nagłówków jeszcze nie zbadano (`resolver.nonprintable_unread_locations`). Ta sama zasada co
# `_CZEKA_NA_FAKTY_KOPII` niżej - zero przy kopiach niezbadanych mówi „?”, liczba niezerowa „N+”, klik
# w „?” prowadzi do Dostawy (etap uzupełnień bada je tym samym odczytem nagłówka) - ale z WŁASNYM
# licznikiem i zdaniem: to kopie FITS bez zbadania bajtu, nie kopie bez faktów.
_NIEZBADANE_WIERSZA = {"header_nonprintable_frames": "header_nonprintable_unread"}

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


class _PrzyciskPowrotu(QPushButton):
    """„← Porządki” podstrony: Enter (`Key_Return`, `Key_Enter`) na przycisku z fokusem = klik (AR-415). Fokus stawia tu
    klawiatura (Enter na „Porządki” przy podstronie), a zwykły `QPushButton` poza oknem dialogowym reaguje wyłącznie na
    Spację. NIE `setAutoDefault(True)`: przy fokusie robi z przycisku domyślny i Fusion maluje go inaczej (zmierzone -
    2-3 tys. pikseli różnych w obu motywach). Auto-powtórzenie zjedzone bez akcji, jak w filtrze Entera listy
    (`TasksView.eventFilter`); klawisz trzymany po powrocie trafia już w listę i tam też nic nie otwiera."""

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not event.isAutoRepeat():
                self.click()
            event.accept()
            return
        super().keyPressEvent(event)


class TasksView(QWidget):
    """Miejsce PORZĄDKI: strona 0 = lista zadań ze stanu, strony 1–3 = podstrony osi (te same widoki
    co dawne zakładki, opakowane w pasek „← Porządki"). Klik w zadanie prowadzi do powierzchni:
    podstrona osi albo Zbiory z ustawioną perspektywą (sygnał `open_collection` — duplikatów NIE
    wyraża drzewo filtra, to flaga `only_dups` presetu, R#14). Wiersze akcyjne klikalne ZAWSZE
    (także n=0 - podstrona to jedyna droga do osi po przemontowaniu nawigacji) - z jednym wyjątkiem:
    lista bez rachunku, którego liczby umie obronić, jest WYGASZONA - do PIERWSZEGO przyłożonego rachunku
    (AR-175, rachunek montażu w tle) i w stanie NIEAKTUALNYM po wejściu albo powrocie przy zmienionej bazie
    (AR-337, rachunek wejścia w tle, `_wygas_wiersze`); klik w tym czasie czeka na wynik (`_klik_w_wiersz`)."""

    open_collection = Signal(str)   # nazwa perspektywy Zbiorów (gospodarz przełącza widok)
    open_intake = Signal()          # klik w wiersz „?" - robota czeka w Dostawie (AR-28 (b))
    open_object_change_run = Signal(str)   # `run_id` przerwanego przebiegu (AR-121) - okno w Zbiorach
    counts_changed = Signal(int)    # badge sidebara: liczba pozycji AKCYJNYCH z n>0
    # SERIA BIEGÓW W TLE (AR-175): `(numer serii, True)` przy starcie pierwszego biegu, `(ten sam numer,
    # False)` po ostatnim biegu łańcucha - wynik, druga porażka albo zatrzymanie widoku. Ponowienie po
    # porażce i bieg zamówiony w trakcie należą do tej samej serii. Numer pozwala gospodarzowi odrzucić
    # koniec serii, której fazy już nie pokazuje. Pierwszy człon to TOKEN MONTAŻU widoku (`montaz`, AR-326):
    # gospodarz rozpoznaje po nim widok bieżącej bazy, nie po `sender()`.
    liczenie_w_toku = Signal(object, int, bool)
    # Pierwszy rachunek padł, zanim jakikolwiek przyłożono (AR-326): `(token montażu, zdanie błędu)` - plakietka
    # i kafel mówią „!”, nie gołe „Porządki”, które czyta się jak zero. Później porażka zostawia stan poprzedni.
    rachunek_padl = Signal(object, str)

    def __init__(self, con, now_fn=_utc_now_iso, parent=None, *, leniwie=False, montaz=None, w_tle=False):
        """`leniwie=True` (gospodarz w trybie wątków tła, AR-175): osie teleskopu i obiektu nie czytają
        bazy w konstruktorze - odczyt przy pierwszym pokazaniu podstrony (wejście z wiersza i tak
        czyta bazę od nowa). Domyślnie jak dotąd - widok samodzielny czyta od razu. `montaz` - token montażu
        gospodarza (AR-326), niesiony w sygnałach `liczenie_w_toku` i `rachunek_padl`; widok samodzielny - `None`.
        `w_tle=True` (gospodarz w trybie wątków tła, AR-380): rachunek wejścia w Porządki i powrotu z podstrony
        liczy w tle z listą nieaktualną - JEDNO źródło trybu od montażu; dawniej tryb zapamiętywało dopiero pierwsze
        wejście, więc powrót przed nim liczył na wątku GUI. Domyślnie synchronicznie (widok samodzielny)."""
        super().__init__(parent)
        self.con = con
        self.montaz = montaz
        self._niewiadome = set()    # klucze wierszy w stanie „?" z ostatniego `refresh_counts`
        # Seria biegów w tle (`liczenie_w_toku`) i czy widok przyłożył już JAKIKOLWIEK rachunek - do
        # pierwszego wiersze akcyjne są wygaszone (klik w „?” bez rachunku szedłby do perspektywy).
        self._seria = 0
        self._liczy = False
        self._przylozony = False
        self._klik_czeka = None     # klucz wiersza klikniętego, gdy lista była wygaszona (`_klik_w_wiersz`)
        # STAN NIEAKTUALNY (AR-337, rachunek wejścia w tle): wejście albo powrót przy zmienionej bazie liczy w tle,
        # a lista do wyniku wygląda jak przed pierwszym rachunkiem (`_wygas_wiersze`). Tryb wejścia i powrotu
        # z podstrony zna widok od montażu (`w_tle`, AR-380). Ostatni przyłożony rachunek (`_ostatni_stan`) wraca na
        # listę, gdy rachunek wejścia padnie (`_pokaz_blad_licznikow`).
        self._nieaktualny = False
        self._w_tle = w_tle
        self._ostatni_stan = None
        # Liczniki w wątku tła (`refresh_counts(w_tle=True)`, AR-84): jeden bieg naraz, generacja
        # wyrzuca wynik wyprzedzony odczytem nowszym; `:memory:` nie ma ścieżki - liczy inline.
        self._db_path = queries.db_path_of(con)
        self._liczniki_gen = 0
        self._liczniki_worker = None
        self._liczniki_thread = None
        self._liczniki_ponow = False
        self._liczniki_stop = False
        # Bieg w tle, który jeszcze NIE oddał wyniku ani porażki (`_on_liczniki`, `_on_liczniki_failed`). Sam wątek żyje
        # dłużej - do `_sprzataj_liczniki` - i w tej przerwie wyniku już nie przyniesie: wejście na niego nie czeka
        # (gałąź „bieg w drodze” `odswiez_przy_wejsciu`).
        self._bieg_czeka_na_wynik = False
        # Odcisk bazy (`queries.odcisk_bazy`) ostatniego PRZYŁOŻONEGO rachunku i biegu w drodze -
        # wejście w Porządki pomija rachunek, gdy baza się od niego nie zmieniła (`odswiez_przy_wejsciu`).
        self._odcisk_licznikow = None
        self._odcisk_biegu = None
        # PRZEGLĄD PLIKÓW OBOK ŚCIEŻKI (AR-231, AR-246, AR-252): zlecenie, które widok obserwuje
        # (`_przeglad`, wpis rejestru `_PRZEGLADY`), jego wątek Pythona (`_przeglad_watek`, bez `join` przy
        # zatrzymaniu) i timer, który czyta zlecenie w wątku GUI (`_przeglad_timer`). Widok zatrzymany puszcza
        # zlecenie - wynik nie ma czytelnika. Stan wiersza pasywnego: `_stan_sladow`. `_prog_ustawiony` - zlecenie
        # obserwowane przez widok wisiało ponad limit i widok postawił próg zaufania czytelnika (rachunek po wyniku);
        # flaga należy do zlecenia, nie do stanu wiersza - ponowienie zaczyna w „trwa”, a próg i tak musi powstać.
        self._now_fn = now_fn
        self._przeglad = None
        self._przeglad_watek = None
        self._przeglad_timer = None
        self._stan_sladow = "schowany"
        self._prog_ustawiony = False
        # pod-widoki osi z FORWARDOWANYM now_fn (F5R#2) — wystawione dla aliasów MainWindow
        # `leniwie` (AR-175): zmierzone na kopii pf4 - oś obiektu ~0,64 s, oś teleskopu ~0,3 s montażu
        # na wątku GUI, a żadnej z podstron przy starcie nie widać.
        self.axis_view = TelescopeAxisView(con, now_fn=now_fn, leniwie=leniwie)
        self.observatory_view = ObservatoryAxisView(con, now_fn=now_fn)
        self.object_view = ObjectAxisView(con, now_fn=now_fn, leniwie=leniwie)
        # Gest zestawu zmienia oś teleskopu (liczby, wartość z plików, nowy wiersz „Dopisz nowy…") -
        # Oś teleskopu odświeża się od razu, bez ręcznego „Odśwież" (wizytacja N4).
        self.object_view.telescope_axis_changed.connect(self.axis_view.refresh)
        self._build_ui()
        # Montaż = start GUI albo zmiana bazy: ślady bez werdyktu (jeden SELECT z indeksu częściowego) i kopie
        # zostawione do oka przegląda wątek tła; bez nich - bez wątku i bez timera.
        if self._db_path and self._sa_slady_do_przegladu():
            self._przejrzyj_slady()

    def _sa_slady_do_przegladu(self):
        """Czy zlecić przegląd plików obok ścieżki (AR-231, AR-246): są ślady cofnięcia bez werdyktu albo
        kopie zostawione do oka (`queries.kept_copy_names`). Błąd BAZY klasą (`powod_bazy`: zablokowana ponad
        `busy_timeout`, niedostępna, uszkodzona) to „nie wiem, czy są” → przegląd startuje i sam zgłasza
        porażkę w wierszu pasywnym (te same zapytania na własnym połączeniu) - montaż nie pada. Błąd spoza
        klas (np. operacja na zamkniętym połączeniu) to błąd programu - leci dalej (EXPECT)."""
        try:
            return bool(repo.unsettled_atomic_undos(self.con)) or bool(queries.kept_copy_names(self.con))
        except sqlite3.Error as exc:
            if powod_bazy(exc) is None:
                raise
            return True

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages)

        # strona 0: lista zadań
        list_page = QWidget()
        lv = QVBoxLayout(list_page)
        # FAZA PRZY TYTULE LISTY (AR-327): do pierwszego wyniku rachunku w tle wiersze są wygaszone, a „Liczę
        # Porządki…” stało wyłącznie na pasku statusu - zmierzone natywnie ~1870 px od listy (okno 2560 px).
        # Ten sam stan widoku (`_sync_fazy`) mówi więc też tu; pasek gospodarza zostaje drugim nośnikiem.
        tytul = QHBoxLayout()
        tytul.setContentsMargins(0, 0, 0, 0)
        tytul.addWidget(QLabel(i18n.t("tasks.list_title")))
        self.faza_licznikow = QLabel(i18n.t("busy.counting_tasks"))
        self.faza_licznikow.setProperty("role", "secondary")
        self.faza_licznikow.setVisible(False)
        tytul.addWidget(self.faza_licznikow)
        tytul.addStretch(1)
        lv.addLayout(tytul)
        # Rachunek liczników na wątku GUI padł (każda droga `refresh_counts`, także ponowienie po
        # biegu w tle): lista zostaje przy stanie poprzednim, a ten wiersz mówi klasą błędu, ze
        # szczegółem pod kursorem (AR-198). Schowany do porażki, gaśnie przy przyłożonym rachunku.
        self.blad_licznikow = EtykietaBledu("")
        self.blad_licznikow.setProperty("role", "error")
        self.blad_licznikow.setWordWrap(True)
        self.blad_licznikow.setVisible(False)
        lv.addWidget(self.blad_licznikow)
        # Przegląd plików obok ścieżki (AR-231, AR-252): wiersz PASYWNY - zdanie ze szczegółem pod kursorem
        # i przycisk ponowienia, bez okna. Dwie etykiety o stałej roli - porażka (`blad_sladow`, `error`) oraz
        # „trwa” i „nie wiem” (`stan_sladow`, `warn`); widoczna co najwyżej jedna, stan stawia wyłącznie
        # `_ustaw_wiersz_sladow`.
        self.wiersz_sladow = QWidget()
        wsl = QHBoxLayout(self.wiersz_sladow)
        wsl.setContentsMargins(0, 0, 0, 0)
        self.stan_sladow = EtykietaBledu("")
        self.stan_sladow.setProperty("role", "warn")
        self.stan_sladow.setWordWrap(True)
        self.stan_sladow.setVisible(False)
        wsl.addWidget(self.stan_sladow, 1)
        self.blad_sladow = EtykietaBledu("")
        self.blad_sladow.setProperty("role", "error")
        self.blad_sladow.setWordWrap(True)
        self.blad_sladow.setVisible(False)
        wsl.addWidget(self.blad_sladow, 1)
        self.ponow_slady = QPushButton(i18n.t("tasks.traces_retry"))
        self.ponow_slady.clicked.connect(lambda: self._przejrzyj_slady(pelny=True))
        wsl.addWidget(self.ponow_slady, 0, Qt.AlignTop)
        self.wiersz_sladow.setVisible(False)
        lv.addWidget(self.wiersz_sladow)
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
        self.tasks.itemClicked.connect(self._klik_w_wiersz)
        # Enter na wierszu = klik (AR-377) - filtr zdarzeń, nie `itemActivated` (`eventFilter`).
        self.tasks.installEventFilter(self)
        for key, label, action in _TASKS:
            it = QListWidgetItem(i18n.t(label))
            if action is None:
                # informacyjna (wzorzec app.py — pozycje info): wyszarzona, żeby afordancja nie
                # kłamała w obie strony (wizytator F5 #2 — „wygląda jednakowo, działa różnie")
                it.setFlags(Qt.ItemIsEnabled)
                it.setForeground(_DIM["fg"])
                it.setData(ROLA_RODZAJU_KOLORU, _RODZAJ_INFORMACYJNY)
            else:
                it.setData(Qt.UserRole, key)           # akcyjna — handler mapuje klucz → akcja
                # WYGASZONA DO PIERWSZEGO RACHUNKU (AR-175): liczniki montażu liczą się w tle, a klik
                # w wiersz „?” bez rachunku szedłby do perspektywy zamiast do Dostawy (`_niewiadome`
                # puste). Wiersz wygaszony nie dostaje kliku; zapala go `_przyloz_liczniki`.
                self._wygas_wiersz(it)
            self.tasks.addItem(it)
        # Lista HUGGUJE treść, reszta pionu zostaje pusta BEZ ramki (wizytator P1 tura 2): przy oknie
        # 1400×900 ramka miała 807 px na 60 px treści - ~750 px obramowanej pustki czyta się jako
        # „coś tu miało być". Wysokość z `_fit_task_list` (pomiar, nie stała): sufit = treść,
        # podłoga = `_LISTA_ZADAN_MIN_WIERSZY` wierszy (AR-188). Lista ma stretch, więc rośnie do
        # treści, gdy pion jest; pion ponad treść bierze pusty stretch pod nią, który trzyma listę
        # przy GÓRZE - centrowanie zerwałoby lewą oś czytania (sidebar + nagłówek na x≈185)
        # i wyglądałoby jak strona www, nie okno Qt. Bez stretchu listy pion dzieliłby się z pustką
        # i lista zostawałaby na podłodze z suwakiem przy wolnym miejscu (zmierzone natywnie: 274 px
        # przy oknie 1040 px i treści 490 px).
        lv.addWidget(self.tasks, 1)
        lv.addStretch(0)
        self._fit_task_list()
        self.pages.addWidget(list_page)                # _PAGE_LIST

        # strony 1–3: podstrony osi (kolejność MUSI zgadzać się ze stałymi _PAGE_*)
        self.pages.addWidget(self._wrap(i18n.t("tasks.telescope_axis"), self.axis_view))          # _PAGE_TELESCOPE
        self.pages.addWidget(self._wrap(i18n.t("tasks.observatory_axis"), self.observatory_view))   # _PAGE_OBSERVATORY
        self.pages.addWidget(self._wrap(i18n.t("tasks.object_review"), self.object_view))   # _PAGE_OBJECTS

    def _fit_task_list(self):
        """Sufit wysokości listy zadań = jej treść (suma wysokości wierszy przez delegata + ramka),
        podłoga = pierwsze `_LISTA_ZADAN_MIN_WIERSZY` wierszy (AR-188). Wołane w budowie (żeby pierwszy
        paint nie mignął pełną ramką), przy przyłożeniu rachunku (`_przyloz_liczniki`) i na każdym wejściu
        w Porządki (`odswiez_przy_wejsciu` - także bez rachunku i przy liście nieaktualnej, AR-337) - dopiero
        po `show()` metryki fontu są prawdziwe (`sizeHintForRow` przed pokazaniem potrafi oddać wartość
        zastępczą). Idempotentne: ten sam pomiar daje tę samą liczbę, więc powtórne wołanie nic nie rusza.

        PODŁOGA NIE ZALEŻY OD LICZBY WIERSZY (AR-188): dawniej wysokość była stała na całą treść,
        a minimum okna liczy się z najwyższej strony - każdy nowy wiersz podnosił podłogę okna
        o wysokość wiersza (zmierzone natywnie: 18 px; 27 wierszy - okno 608 px, 37 - 788 px). Teraz
        lista ponad podłogę przewija się, gdy pionu brak, a przy wolnym pionie pokazuje całą treść.

        WIZ #14: `sizeHintForRow(0) × n` KŁAMAŁO, bo wiersze maluje `TwoPartDelegate` i realna
        wysokość jest większa niż podpowiedź widoku (zmierzone: podpowiedź 13 px przy wierszu
        wyraźnie wyższym) - lista dostawała pasek przewijania przy PIĘCIU pozycjach, mając pod sobą
        ~700 px wolnego pionu. Sumujemy więc wysokości WSZYSTKICH wierszy przez delegata
        (`sizeHintForIndex`), zamiast mnożyć jedną podpowiedź: wiersze nie muszą być równe."""
        n = self.tasks.count()
        # Lista NIGDY nie jest pusta: `_build_ui` wstawia wiersz na każdą pozycję `_TASKS`, a nic jej
        # nie opróżnia (`_przyloz_liczniki` przepisuje tylko tekst i role). Pusta lista = złamany
        # inwariant - podłoga 18 wierszy i sufit treści z poprzedniego stanu zostałyby zawieszone.
        assert n, "lista Porządków bez wierszy - `_TASKS` nie wszedł do listy"
        model = self.tasks.model()
        wiersze = [self.tasks.sizeHintForIndex(model.index(i, 0)).height() for i in range(n)]
        ramka = 2 * self.tasks.frameWidth()
        self.tasks.setMinimumHeight(sum(wiersze[:_LISTA_ZADAN_MIN_WIERSZY]) + ramka)
        self.tasks.setMaximumHeight(sum(wiersze) + ramka)

    def _wrap(self, title, view):
        """Podstrona osi: pasek powrotu + tytuł + widok. Powrót odświeża listę (stan mógł się
        zmienić — user nazwał teleskopy/scalił stanowiska w podstronie)."""
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        back = _PrzyciskPowrotu(i18n.t("tasks.back"))   # Enter z fokusem = klik (AR-415)
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

    def refresh_counts(self, *, w_tle=False):
        """Przeładuj liczniki zadań ze stanu (`queries.tasks_state`) i wyemituj badge
        (`counts_changed` = liczba pozycji akcyjnych z n>0). Woła gospodarz (montaż, po przebiegu
        Dostawy, sygnał stanu Porządków z gestu Zbiorów) i droga wejścia (`odswiez_przy_wejsciu`).
        Zwraca badge (tryb synchroniczny).

        `w_tle=True` (gest Zbiorów, AR-84) liczy stan w `_LicznikiWorker` i wraca od razu: lista
        i plakietka trzymają stan poprzedni do przyłożenia wyniku (`_on_liczniki`) - stan nieaktualny
        stawia wyłącznie droga wejścia (AR-337). Zlecenie w trakcie biegu zamawia jeden bieg więcej
        po nim, na stanie z TAMTEJ chwili. Odczyt synchroniczny (tryb bez wątków tła, widok samodzielny,
        odcisk nieczytelny przy starcie biegu) podbija generację, więc wynik biegu sprzed niego idzie do
        kosza - nie nadpisze nowszego stanu starszym.

        JEDYNY WŁAŚCICIEL PORAŻKI RACHUNKU (AR-198): błąd bazy albo systemu w odczycie synchronicznym
        stawia wiersz błędu nad listą (lista zostaje przy stanie poprzednim) i zwraca `None` - każda
        droga (montaż, wejście w Porządki, powrót z podstrony) mówi zdaniem klasy zamiast wyjątku ze
        slotu; druga porażka biegu w tle mówi tym samym wierszem (`_pokaz_blad_licznikow`, AR-302).
        Błąd programu (inny wyjątek) leci dalej (EXPECT)."""
        self._liczniki_gen += 1
        if w_tle and self._db_path and not self._liczniki_stop:
            if self._liczniki_thread is not None:
                self._liczniki_ponow = True
            else:
                self._start_licznikow()
            return None
        # Odcisk PRZED rachunkiem: zapis w jego trakcie zmieni odcisk, więc wejście policzy jeszcze
        # raz - odwrotna kolejność mogłaby przypisać staremu rachunkowi stan nowszy od niego.
        try:
            odcisk = queries.odcisk_bazy(self.con)
            stan = _stan_licznikow(self.con)
        except (sqlite3.Error, OSError) as exc:
            # `powod_okna` (AR-264): `ProgrammingError`/`InterfaceError` (API bazy wbrew kontraktowi)
            # mówi błędem programu z miejscem w kodzie, nie surowym angielskim tekstem SQLite.
            powod = powod_okna(exc)
            self._pokaz_blad_licznikow(powod)
            return None
        badge = self._przyloz_liczniki(*stan)
        self._odcisk_licznikow = odcisk
        return badge

    def liczy_w_tle(self):
        """Czy trwa seria biegów liczników w tle (`liczenie_w_toku`) - gospodarz stawia przy montażu
        stan „liczę” na plakietce i kaflu Domu, gdy rachunek montażu poszedł w tło."""
        return self._liczy

    def ma_rachunek(self):
        """Czy widok przyłożył już jakikolwiek rachunek liczników (wiersze akcyjne zapalone)."""
        return self._przylozony

    def _ustaw_liczenie(self, w_toku):
        """Stan serii biegów w tle i jego sygnał (`liczenie_w_toku`) - tylko przy zmianie stanu;
        nowa seria dostaje nowy numer."""
        if w_toku == self._liczy:
            return
        if w_toku:
            self._seria += 1
        self._liczy = w_toku
        self._sync_fazy()
        self.liczenie_w_toku.emit(self.montaz, self._seria, w_toku)

    def _sync_fazy(self):
        """Faza przy tytule listy (AR-327): widoczna, póki seria biegów w tle trwa, a lista nie ma rachunku, którego
        liczby umie obronić - żaden nie został przyłożony albo lista jest NIEAKTUALNA (AR-337) - i nic nie padło;
        potem mówią liczby albo wiersz błędu."""
        self.faza_licznikow.setVisible(self._liczy and (not self._przylozony or self._nieaktualny)
                                       and self.blad_licznikow.isHidden())

    def odswiez_przy_wejsciu(self):
        """Wejście w Porządki (gospodarz, `_on_nav_changed`) i powrót z podstrony (`_on_back`): liczniki ze stanu,
        ale BEZ rachunku, gdy odcisk bazy (`queries.odcisk_bazy`) nie zmienił się od ostatniego przyłożonego - lista
        mówi wtedy prawdę, a rachunek kosztował na wejściu 0,7-1,9 s na kopii pf4, choć tło po geście już go zrobiło
        (AR-84). Wysokość listy mierzy się i tak: metryki fontu są prawdziwe dopiero po pokazaniu.

        PRZY ZMIANIE - RACHUNEK W TLE, LISTA NIEAKTUALNA (AR-337; tryb wątków tła widoku `w_tle` - od montażu, AR-380):
        rachunek synchroniczny zamrażał okno przy każdym wejściu i powrocie po zmianie - natywnie 825-1091 ms od
        kliku „Porządki” do pierwszego obrotu pętli na kopii pf4 v47, w tle 3,5-5,0 ms. Do wyniku lista wygląda jak
        przed pierwszym rachunkiem (AR-175): kolumna liczb pusta, wiersze akcyjne wygaszone, faza przy tytule
        (`_wygas_wiersze`) - nie pokazuje liczby, której nie umie obronić; klik w wiersz czeka na wynik
        (`_klik_w_wiersz`). Widok bez trybu wątków (samodzielny) - rachunek synchroniczny jak dotąd.

        NOWA WIZYTA LISTY: klik odłożony w poprzedniej wizycie przepada - inaczej klik → Dom → powrót → wynik otwierał
        cel kliku bez gestu w nowej wizycie. Każdy powrót na listę idzie tędy (wejście gospodarza, „← Porządki”).

        Skrót tylko przy SCHOWANYM wierszu błędu i liście AKTUALNEJ: po porażce rachunku lista nie mówi prawdy, choćby
        odcisk się nie zmienił, a lista nieaktualna bez rachunku w drodze (AR-380) zostałaby wygaszona do zmiany bazy.
        Odcisk, którego nie da się przeczytać, też nie jest „bez zmian” - pełny rachunek powie błąd zdaniem
        (`refresh_counts`, AR-198).

        Wejście zleca też przegląd KOPII zostawionych do oka (AR-246) PRZED skrótem: człowiek usuwa albo
        przywraca je poza programem, a odcisk bazy tego nie widzi. Śladów cofnięcia wejście NIE przegląda
        (`_przeglad_slady`, `pelny=False`) - obserwator zostaje przy montażu i ponowieniu. Błąd bazy w pytaniu
        „czy są kopie” to pominięcie zlecenia - mówi o nim rachunek niżej zdaniem (AR-198), jak dotąd na
        wejściu. Nic do przeglądu (ani kopii, ani śladów bez werdyktu) i żadnego zlecenia w biegu - wiersz pasywny
        poprzedniego przeglądu gaśnie, bo nie ma już czego ponawiać.

        BIEG W TLE W DRODZE NA TYM SAMYM STANIE (AR-175): wejście w pierwszej sekundzie po montażu trafiało
        na rachunek montażu w biegu i liczyło drugi raz synchronicznie (0,76-1,5 s na wątku GUI, wynik tła
        do kosza). Gdy odcisk bazy jest ten, z którym bieg ruszył, jego wynik powie prawdę - wejście czeka
        na niego z listą NIEAKTUALNĄ (stare liczby nie stoją czynne, AR-337), zamiast liczyć. Bieg, który oddał już
        porażkę i czeka tylko na sprzątnięcie wątku, wyniku nie przyniesie (`_bieg_czeka_na_wynik`) - wejście
        liczy wtedy od nowa. Tak samo bieg WYPRZEDZONY (AR-380): rachunek synchroniczny w trakcie biegu podbił
        generację, więc wynik biegu idzie do kosza (`_on_liczniki`) - czekanie na niego zostawiało listę wygaszoną bez
        fazy i bez błędu, a klik odłożony nie wykonywał się nigdy.

        Każde wyjście sprawdza inwariant listy nieaktualnej (`_inwariant_listy_nieaktualnej`)."""
        w_tle = self._w_tle
        self._klik_czeka = None
        if self._db_path:
            try:
                kopie = bool(queries.kept_copy_names(self.con))
                slady = kopie or bool(repo.unsettled_atomic_undos(self.con))
            except sqlite3.Error:
                kopie = slady = None
            if kopie:
                self._przejrzyj_slady(pelny=False)
            elif slady is False and self._przeglad is None:
                self._ustaw_wiersz_sladow("schowany")
        if self._odcisk_licznikow is not None and self.blad_licznikow.isHidden() and not self._nieaktualny:
            try:
                bez_zmian = queries.odcisk_bazy(self.con) == self._odcisk_licznikow
            except (sqlite3.Error, OSError):
                bez_zmian = False
            if bez_zmian:
                self._fit_task_list()
                self._inwariant_listy_nieaktualnej()
                return
        if self._bieg_biezacy_w_drodze() and not self._liczniki_ponow:
            try:
                w_drodze = queries.odcisk_bazy(self.con) == self._odcisk_biegu
            except (sqlite3.Error, OSError):
                w_drodze = False
            if w_drodze:
                self._wygas_wiersze()
                self._fit_task_list()
                self._inwariant_listy_nieaktualnej()
                return
        if w_tle and self._db_path and not self._liczniki_stop:
            self._wygas_wiersze()
            self.refresh_counts(w_tle=True)
            self._fit_task_list()
            self._inwariant_listy_nieaktualnej()
            return
        self.refresh_counts()
        self._inwariant_listy_nieaktualnej()

    def _bieg_biezacy_w_drodze(self):
        """Bieg w tle, który jeszcze odda wynik (`_bieg_czeka_na_wynik`) i ten wynik zostanie PRZYŁOŻONY: jego generacja
        to bieżąca (`_LicznikiWorker._gen` wobec `_liczniki_gen`) - wynik biegu wyprzedzonego idzie do kosza
        (`_on_liczniki`, AR-380)."""
        return (self._liczniki_thread is not None and self._bieg_czeka_na_wynik
                and self._liczniki_worker._gen == self._liczniki_gen)

    def _inwariant_listy_nieaktualnej(self):
        """EXPECT (AR-380): lista NIEAKTUALNA (wygaszona do wyniku, `_wygas_wiersze`) ma w drodze bieg bieżącej
        generacji albo zamówione ponowienie (`_liczniki_ponow`) - inaczej nikt jej nie zapali: bez fazy, bez błędu, klik
        odłożony nie wykona się nigdy. Wołane na każdym wyjściu wejścia w Porządki i przy końcu biegu
        (`_sprzataj_liczniki`)."""
        assert not self._nieaktualny or self._liczniki_ponow or self._bieg_biezacy_w_drodze(), (
            "lista Porządków nieaktualna bez rachunku w drodze", self._liczniki_gen,
            self._liczniki_worker._gen if self._liczniki_worker is not None else None)

    def _start_licznikow(self):
        try:
            self._odcisk_biegu = queries.odcisk_bazy(self.con)   # przed odczytem w wątku - jak wyżej
        except (sqlite3.Error, OSError):
            # Połączenie okna nie czyta bazy - bieg w tle nie rusza, rachunek synchroniczny mówi
            # błąd zdaniem (jeden właściciel, `refresh_counts`), zamiast wyjątku z gestu Zbiorów.
            self.refresh_counts()
            return
        worker = _LicznikiWorker(self._liczniki_gen, self._db_path)
        worker.done.connect(self._on_liczniki)
        worker.failed.connect(self._on_liczniki_failed)
        self._liczniki_worker = worker
        self._liczniki_thread = QThread(self)
        worker.moveToThread(self._liczniki_thread)
        self._liczniki_thread.started.connect(worker.run)
        worker.finished.connect(self._liczniki_thread.quit)
        self._liczniki_thread.finished.connect(self._sprzataj_liczniki)
        self._bieg_czeka_na_wynik = True
        self._liczniki_thread.start()
        self._ustaw_liczenie(True)

    @Slot(int, object)
    def _on_liczniki(self, gen, wynik):
        self._bieg_czeka_na_wynik = False   # bieg oddał wynik - wątek czeka już tylko na sprzątnięcie
        if gen != self._liczniki_gen:
            return                          # wyprzedzony nowszym odczytem - do kosza
        self._przyloz_liczniki(*wynik)
        self._odcisk_licznikow = self._odcisk_biegu

    def _pokaz_blad_licznikow(self, powod):
        """Wiersz błędu nad listą (lista zostaje przy stanie poprzednim): zdanie powodu w języku UI
        i szczegół pod kursorem - JEDNO miejsce dla rachunku synchronicznego (`refresh_counts`) i drugiej
        porażki biegu w tle (`_on_liczniki_failed`). Porażka PIERWSZEGO rachunku zapala wiersze
        wygaszone do wyniku (AR-175): bez rachunku prowadzą tam, gdzie przed tą zmianą - zdanie błędu
        mówi, że liczb nie ma. Porażka bez żadnego przyłożonego rachunku mówi gospodarzowi `rachunek_padl`
        (AR-326) - plakietka bez liczby czytałaby się jak zero.

        Klik odłożony przepada razem z rachunkiem, KAŻDĄ drogą porażki (tu, nie u wołających) - inaczej
        odpaliłby się sam przy następnym udanym rachunku, bez gestu (AR-175).

        Lista NIEAKTUALNA (AR-337 - rachunek wejścia albo powrotu padł) wraca do stanu POPRZEDNIEGO
        (`_ostatni_stan`): ta sama semantyka porażki co po geście Zbiorów - liczby ostatniego przyłożonego
        rachunku, wiersze czynne, a wiersz błędu mówi, że nowego rachunku nie ma. Odcisk zostaje stary,
        więc następne wejście liczy od nowa."""
        self._klik_czeka = None
        if self._nieaktualny and self._ostatni_stan is not None:
            self._przyloz_liczniki(*self._ostatni_stan)
        self._nieaktualny = False
        zdanie = i18n.t("tasks.counts_failed", msg=tekst_powodu(powod))
        self.blad_licznikow.ustaw(zdanie, wiersz_systemu(powod))
        self.blad_licznikow.setVisible(True)
        self._sync_fazy()
        if not self._przylozony:
            self._zapal_wiersze()
            self.rachunek_padl.emit(self.montaz, zdanie)

    def eventFilter(self, obj, event):
        """ENTER NA WIERSZU LISTY = KLIK (AR-377): `Key_Return`/`Key_Enter` na liście idzie drogą kliku
        (`_klik_w_wiersz` z bieżącym wierszem - także odłożenie do wyniku rachunku) i jest ZJEDZONY, więc Qt nie emituje
        `activated` ani nie oddaje klawisza rodzicom. Filtr, nie `itemActivated`: dwuklik i style z aktywacją jednym
        klikiem doręczają `activated` OBOK `clicked` (Qt 6.9.2 `qabstractitemview.cpp`), a `_on_task_clicked` nie jest
        idempotentne - drugie doręczenie otwierałoby cel drugi raz. Auto-powtórzenie przytrzymanego klawisza zjedzone
        bez akcji z tego samego powodu (widok, który nie zmienia strony, otwierałby raz na powtórzenie). Reszta zdarzeń
        - `super()`."""
        if (obj is self.tasks and event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)):
            if not event.isAutoRepeat():
                self._klik_w_wiersz(self.tasks.currentItem())
            return True
        return super().eventFilter(obj, event)

    def _klik_w_wiersz(self, item):
        """Klik albo Enter (`eventFilter`) w wiersz listy. Wiersz WYGASZONY (do pierwszego rachunku, AR-175, i w stanie
        nieaktualnym, AR-337) nie prowadzi nigdzie od razu - Qt doręcza `itemClicked` także dla elementu bez
        `ItemIsEnabled`, więc wygaszenie samo kliku nie zatrzymuje. Reszta - `_on_task_clicked`. Enter bez bieżącego
        wiersza (`None`) nie robi nic.

        Klik w wiersz wygaszony NIE PRZEPADA: klucz czeka na wynik rachunku, a `_przyloz_liczniki`
        wykonuje go na świeżym `_niewiadome` („?” prowadzi do Dostawy), o ile lista jest wciąż na ekranie.
        Przepada z porażką rachunku (`_pokaz_blad_licznikow`) i z końcem wizyty listy (`odswiez_przy_wejsciu`).
        Wiersz odłożony staje się BIEŻĄCYM od razu (AR-377): Qt nie ustawia bieżącego przy kliku w element bez
        `ItemIsEnabled` (i `setCurrentItem` go odrzuca - stąd model zaznaczenia), a „← Porządki” po odłożonym otwarciu
        wraca na wiersz, z którego człowiek wszedł."""
        if item is None:
            return
        if item.flags() & Qt.ItemIsEnabled:
            self._on_task_clicked(item)
        elif item.data(Qt.UserRole) is not None:
            self._klik_czeka = item.data(Qt.UserRole)
            self.tasks.selectionModel().setCurrentIndex(self.tasks.indexFromItem(item),
                                                        QItemSelectionModel.SelectionFlag.NoUpdate)

    def fokus_z_klawiatury(self):
        """Fokus klawiatury tam, gdzie człowiek na Porządkach pracuje (AR-377, pętla Popraw z klawiatury) - wejście
        Enterem z paska nawigacji (`MainWindow._on_nav_wejscie`) i powrót „← Porządki” (`_on_back`): przy liście -
        lista, a bez bieżącego wiersza bieżącym zostaje PIERWSZY WIERSZ AKCYJNY (także wygaszony w stanie nieaktualnym -
        Enter na nim czeka na wynik jak klik; sam Qt przy fokusie wybiera pierwszy CZYNNY, czyli wiersz informacyjny);
        przy podstronie osi - jej „← Porządki”, bo lista jest wtedy schowana, a Enter na schowanej liście otwierałby
        wiersz, którego człowiek nie widzi."""
        if self.pages.currentIndex() != _PAGE_LIST:
            wstecz = next(b for b in self.pages.currentWidget().findChildren(
                QPushButton, options=Qt.FindChildOption.FindDirectChildrenOnly) if b.text() == i18n.t("tasks.back"))
            wstecz.setFocus(Qt.OtherFocusReason)
            return
        if self.tasks.currentRow() < 0:
            pierwszy = next(r for r, (_k, _l, akcja) in enumerate(_TASKS) if akcja is not None)
            self.tasks.selectionModel().setCurrentIndex(self.tasks.model().index(pierwszy, 0),
                                                        QItemSelectionModel.SelectionFlag.NoUpdate)
        self.tasks.setFocus(Qt.OtherFocusReason)

    def _zapal_wiersze(self):
        """Wiersze akcyjne wygaszone do pierwszego rachunku (`_build_ui`) - zapalone, bez podpowiedzi
        „liczę”; podpowiedzi wierszy stawia rachunek."""
        for row, (_key, _label, action) in enumerate(_TASKS):
            it = self.tasks.item(row)
            if action is not None and not it.flags() & Qt.ItemIsEnabled:
                it.setFlags(it.flags() | Qt.ItemIsEnabled)
                it.setToolTip("")

    def _wygas_wiersz(self, it):
        """JEDEN wygląd wiersza akcyjnego bez rachunku - przed pierwszym rachunkiem (`_build_ui`, AR-175) i w stanie
        nieaktualnym (`_wygas_wiersze`, AR-337): bez `ItemIsEnabled`, z podpowiedzią „liczę”, bez liczby,
        pogrubienia i rodzaju koloru. Kolor trzeba ZDJĄĆ, nie tylko wygasić wiersz: jawny pędzel `ForegroundRole`
        przechodzi przez wygaszenie, a szarość wiersza bez roboty (`_DIM`) wyglądałaby jak wynik „nic do zrobienia”
        - bez pędzla wiersz maluje kolor wygaszony palety (zmierzone natywnie: motyw ciemny #6e6e6e wobec #a8a8a8
        szarości `_DIM`, jasny #a6a6a6 wobec #666666)."""
        it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
        it.setToolTip(i18n.t("busy.counting_tasks"))
        for rola in (rows.SECONDARY, rows.STRONG, ROLA_RODZAJU_KOLORU, Qt.ForegroundRole):
            it.setData(rola, None)

    def _wygas_wiersze(self):
        """Lista NIEAKTUALNA (AR-337, rachunek wejścia w tle): wejście albo powrót przy zmienionej bazie czeka na
        rachunek - wygląd montażu (AR-175) w nowej chwili, bez nowego elementu (zrzut natywny: stan nieaktualny = stan
        montażu, piksel w piksel, w obu motywach). Wiersz błędu poprzedniej porażki gaśnie - nowy rachunek powie swoje:
        wynik (`_przyloz_liczniki` zdejmuje stan) albo porażka (`_pokaz_blad_licznikow`)."""
        self._nieaktualny = True
        self.blad_licznikow.clear()
        self.blad_licznikow.setVisible(False)
        for row, (_key, _label, action) in enumerate(_TASKS):
            if action is not None:
                self._wygas_wiersz(self.tasks.item(row))
        self._sync_fazy()

    # Generacja, której rachunek już raz ponowiono w tle - druga porażka mówi wierszem błędu (AR-302).
    _liczniki_ponowiony = None

    @Slot(int, object)
    def _on_liczniki_failed(self, gen, powod):
        """Bieg w tle padł (wzór `FramesView._on_zbior_failed`): pierwsza porażka generacji - drugie
        podejście w NOWYM biegu workera na tej samej generacji (`_sprzataj_liczniki` rusza go po końcu
        wątku, gałąź `_liczniki_ponow`) - przypadłość połączenia wątku znika przy ponowieniu. Druga
        porażka mówi swoim powodem w wierszu błędu (`_pokaz_blad_licznikow`) - klasa bazy albo systemu,
        a błąd programu zdaniem `prog_error` z miejscem w szczególe.

        DO AR-302 drugie podejście szło synchronicznie na wątku GUI (rachunek 557 ms na pf4, AR-84),
        a błąd programu wychodził wyjątkiem ze slotu - w wydaniu okienkowym bez śladu."""
        self._bieg_czeka_na_wynik = False   # porażka oddana - wątek czeka już tylko na sprzątnięcie
        if gen != self._liczniki_gen:
            return
        if self._liczniki_ponowiony == gen:
            self._liczniki_ponowiony = None
            self._pokaz_blad_licznikow(powod)   # klik odłożony przepada tam (jedno miejsce porażki)
            return
        self._liczniki_ponowiony = gen
        self._liczniki_ponow = True

    def _sprzataj_liczniki(self):
        """Koniec wątku liczników. ŚWIĘTA KOLEJNOŚĆ jak w `FramesView._sprzataj_pola` (deadlock AB-BA
        GIL × ~QThread): worker.deleteLater → wait → thread.deleteLater. Po decyzji o ponowieniu i po zgaszeniu
        fazy liczenia - inwariant listy nieaktualnej (AR-380): wynik albo porażka tego biegu przyszły przed tym
        slotem (kolejka zdarzeń wątku GUI), więc lista wciąż nieaktualna bez nowego biegu = droga, która ją
        porzuciła. Widok zatrzymany (`_liczniki_stop`) znika - jego lista nikogo nie obchodzi."""
        if self._liczniki_thread is None:
            return
        self._liczniki_worker.deleteLater()
        self._liczniki_thread.wait()
        self._liczniki_thread.deleteLater()
        self._liczniki_worker = None
        self._liczniki_thread = None
        if self._liczniki_ponow and not self._liczniki_stop:
            self._liczniki_ponow = False
            self._start_licznikow()          # generacja ostatniego zlecenia
        if self._liczniki_thread is None:
            self._ustaw_liczenie(False)      # ostatni bieg serii (AR-175)
        # PO końcu serii: faza i sygnał gospodarza stoją, zanim asercja przerwie slot.
        if not self._liczniki_stop:
            self._inwariant_listy_nieaktualnej()

    def zatrzymaj_pola(self):
        """Widok znika (zmiana bazy, zamknięcie okna - `MainWindow._zatrzymaj_watki_widokow` woła tę
        metodę po nazwie u każdej strony stosu): ZBIERZ wątek liczników, zanim rodzic go skasuje
        (`~QThread` w biegu to twardy abort). Generacja w górę, więc wynik, który zdążył wyjść
        z wątku, nie dotknie listy ani zamkniętego połączenia. Rachunek czyta wyłącznie bazę i pamięć
        obecności kopii, żadnego `stat` archiwum (AR-246). Idempotentne.

        RACHUNEK JEST PRZERYWANY (AR-175, wzór `FramesView.zatrzymaj_pola`): `request_cancel` przerywa
        zapytanie w locie, a ponawiamy je co 100 ms - `interrupt` trafiony między dwoma zapytaniami
        rachunku nie działa, kolejne łapie już zapytanie w locie. Przełączenie bazy w pierwszej sekundzie
        po montażu czekało dotąd na cały rachunek. Seria biegów kończy się sygnałem `liczenie_w_toku`.

        PRZEGLĄD PLIKÓW OBOK ŚCIEŻKI (AR-231) NIE JEST ZBIERANY: widok puszcza zlecenie i zatrzymuje timer -
        czas stały, bez `join`. Wątek Pythona kończy sam (zapisuje wyłącznie `kept` do bazy SWOJEGO połączenia -
        po zmianie bazy starej, werdykt dalej prawdziwy dla jej śladu - i odczyty obecności do pamięci, gdzie
        starszy odczyt nie cofnie nowszego), a jego wynik nie ma czytelnika."""
        self._zatrzymaj_przeglad()
        self._liczniki_stop = True
        self._liczniki_ponow = False
        self._bieg_czeka_na_wynik = False
        self._liczniki_gen += 1
        if self._liczniki_thread is None:
            return
        self._liczniki_worker.request_cancel()
        self._liczniki_thread.quit()
        self._liczniki_worker.deleteLater()
        while not self._liczniki_thread.wait(100):
            self._liczniki_worker.request_cancel()
        self._liczniki_thread.deleteLater()
        self._liczniki_worker = None
        self._liczniki_thread = None
        self._ustaw_liczenie(False)

    # ---------------------------------------------------------------- przegląd śladów cofnięcia (AR-231)

    def _przejrzyj_slady(self, *, pelny=True):
        """Zlecenie przeglądu plików obok ścieżki w wątku Pythona (`_przeglad_slady`) - pełnego (ślady cofnięcia
        i kopie) przy montażu (start GUI, zmiana bazy) i z przycisku ponowienia, samych kopii (`pelny=False`)
        przy wejściu w Porządki. Żywe zlecenie tej bazy (`_PRZEGLADY`) dostaje kolejnego obserwatora zamiast
        drugiego wątku (AR-252); brak albo gotowe - nowe zlecenie, wpisane do rejestru dopiero po udanym starcie
        wątku. Żądanie pełnego podpięte pod żywy przegląd samych kopii zostaje przy nim - obserwator śladów rusza
        przy następnym montażu albo ponowieniu, NIE sam po wyniku: ślad mógł w tym czasie utrwalić żywy właściciel
        cofnięcia tego procesu, a obserwator odebrałby mu `clean` (powód, dla którego wejście w Porządki nie
        przegląda śladów).
        Wiersz pasywny widoczny (porażka, „nie wiem”) przechodzi od razu w „trwa” z ponowieniem zgaszonym;
        schowany zostaje schowany do limitu (`_odbierz_przeglad`) - przy sprawnym dysku nie mignie."""
        klucz = queries.klucz_bazy(self._db_path)
        zlecenie = _PRZEGLADY.get(klucz)
        if zlecenie is None or zlecenie.gotowe.is_set():
            zlecenie = _Przeglad(start=time.monotonic(), bilet=queries.bilet_obecnosci(), pelny=pelny)
            zlecenie.watek = threading.Thread(
                target=_przeglad_slady, name="horreum-przeglad-sladow", daemon=True,
                args=(self._db_path, self._now_fn(), zlecenie))
            zlecenie.watek.start()
            _PRZEGLADY[klucz] = zlecenie
        if self._przeglad is not zlecenie:
            self._prog_ustawiony = False
        self._przeglad = zlecenie
        self._przeglad_watek = zlecenie.watek
        self._ustaw_wiersz_sladow("schowany" if self._stan_sladow == "schowany" else "trwa")
        if self._przeglad_timer is None:
            self._przeglad_timer = QTimer(self)
            self._przeglad_timer.timeout.connect(self._odbierz_przeglad)
        self._przeglad_timer.start(_PRZEGLAD_TAKT_MS)

    def _odbierz_przeglad(self):
        """Takt timera w wątku GUI. Zlecenie w biegu ponad `_PRZEGLAD_LIMIT_S` → „trwa” (AR-252) i próg zaufania
        czytelnika (`queries.ustaw_prog_obecnosci` - „nie ma” sprzed startu zlecenia nie ukrywa kopii) z rachunkiem
        liczników w tle. Zlecenie gotowe → stan wiersza z wyniku: porażka (wyjątek całego przeglądu albo śladu -
        `PrzegladSladow.padly`; zlecenie bez wyniku - błąd programu) → zdanie klasy błędu; odczyt „nie wiem”
        (`None` - kopia zostawiona albo ślad, `PrzegladSladow.nie_wiem_nazwy`) → zdanie „nie wiem” z nazwami pod
        kursorem; inaczej wiersz schowany. Ślad bez werdyktu z TRZEMA dowiedzionymi brakami wiersza nie zapala:
        obok ścieżki nic nie ma, a `clean` pisze wyłącznie właściciel (AR-247) - ostrzeżenie świeciłoby na zawsze
        bez gestu, który je gasi. Werdykt `kept`, zmieniona wartość pamięci obecności albo zdjęty próg → rachunek
        liczników w tle (wiersz „Kopie zostawione do oka” i plakietka) - bez zmiany nie ma rachunku (AR-84)."""
        zlecenie = self._przeglad
        if zlecenie is None:
            self._przeglad_timer.stop()
            return
        if not zlecenie.gotowe.is_set():
            if not self._prog_ustawiony and time.monotonic() - zlecenie.start > _PRZEGLAD_LIMIT_S:
                self._ustaw_wiersz_sladow("trwa")
                queries.ustaw_prog_obecnosci(self._db_path, zlecenie.bilet)
                self._prog_ustawiony = True
                self.refresh_counts(w_tle=True)
            return
        self._przeglad_timer.stop()
        self._przeglad = None
        self._przeglad_watek = None
        queries.zdejmij_prog_obecnosci(self._db_path, zlecenie.bilet)
        wynik = zlecenie.wynik
        if wynik is None:                  # zlecenie bez wyniku - klasyfikacja porażki sama padła
            wynik = powod_okna(RuntimeError("przegląd plików obok ścieżki skończył się bez wyniku"))
        slady, kopie, zmiana = wynik if isinstance(wynik, tuple) else (None, {}, False)
        powod = slady.powod if slady is not None else wynik
        nie_wiem = list(dict.fromkeys(
            [s for s, v in kopie.items() if v is None] + list(slady.nie_wiem_nazwy if slady else ())))
        if powod is not None:
            self._ustaw_wiersz_sladow("porazka", i18n.t("tasks.traces_failed", msg=tekst_powodu(powod)),
                                      wiersz_systemu(powod))
        elif nie_wiem:
            self._ustaw_wiersz_sladow("nie_wiem", i18n.t("tasks.traces_unknown"), "\n".join(nie_wiem))
        else:
            self._ustaw_wiersz_sladow("schowany")
        prog, self._prog_ustawiony = self._prog_ustawiony, False
        if (slady is not None and (slady.kept or zmiana)) or prog:
            self.refresh_counts(w_tle=True)

    def _ustaw_wiersz_sladow(self, stan, zdanie="", szczegol=""):
        """JEDYNY setter wiersza pasywnego przeglądu: `schowany` | `trwa` | `porazka` | `nie_wiem`. W stanie
        widocznym dokładnie jedna etykieta niesie zdanie (porażka - `blad_sladow`, reszta - `stan_sladow`),
        druga jest pusta i schowana; ponowienie zgaszone wyłącznie w „trwa” (drugi wątek tej bazy i tak by
        nie ruszył - `_PRZEGLADY`)."""
        self._stan_sladow = stan
        if stan == "trwa":
            zdanie = i18n.t("tasks.traces_pending")
        for etykieta, jej in ((self.blad_sladow, stan == "porazka"),
                              (self.stan_sladow, stan in ("trwa", "nie_wiem"))):
            if jej:
                etykieta.ustaw(zdanie, szczegol)
            else:
                etykieta.clear()
            etykieta.setVisible(jej)
        self.wiersz_sladow.setVisible(stan != "schowany")
        self.ponow_slady.setEnabled(stan != "trwa")

    def _zatrzymaj_przeglad(self):
        """Widok znika: zlecenie w biegu traci czytelnika (widok je puszcza), timer stoi - bez czekania na
        wątek (`zatrzymaj_pola`)."""
        self._przeglad = None
        self._przeglad_watek = None
        self._prog_ustawiony = False
        if self._przeglad_timer is not None:
            self._przeglad_timer.stop()

    def _przyloz_liczniki(self, state, kandydaci):
        """Fakty `_stan_licznikow` → wiersze listy, podpowiedzi i badge (wątek GUI). Przyłożony
        rachunek gasi wiersz błędu poprzedniej porażki (`_on_liczniki_failed`) i stan nieaktualny (AR-337),
        a sam zostaje stanem poprzednim na wypadek porażki następnego rachunku wejścia (`_ostatni_stan`)."""
        self.blad_licznikow.clear()
        self.blad_licznikow.setVisible(False)
        self._zapal_wiersze()          # wygaszone do pierwszego rachunku (AR-175) i w stanie nieaktualnym (AR-337)
        self._przylozony = True
        self._nieaktualny = False
        self._ostatni_stan = (state, kandydaci)
        self._sync_fazy()
        czeka = len(kandydaci)
        badge = 0
        self._niewiadome = set()
        for row, (key, label, action) in enumerate(_TASKS):
            n = state[key]
            # Robota wiersza: ta sama liczba albo jej podzbiór (`_ROBOTA_Z_PODZBIORU`, AR-10).
            robota = state[_ROBOTA_Z_PODZBIORU[key]] if key in _ROBOTA_Z_PODZBIORU else n
            it = self.tasks.item(row)
            # Kopie niezbadane wiersza z własnym licznikiem (`_NIEZBADANE_WIERSZA`, AR-299) - ta sama
            # mechanika „?” / „N+” co kopie bez faktów, inna liczba i inne zdanie.
            niezbadane = state[_NIEZBADANE_WIERSZA[key]] if key in _NIEZBADANE_WIERSZA else 0
            czesciowe = (czeka > 0 and key in _CZEKA_NA_FAKTY_KOPII) or niezbadane > 0
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
            calosc = _czlon_calosci(key, robota, n)
            if niezbadane and niewiadome:
                liczba = i18n.t_plural("tasks.header_nonprintable_unread", niezbadane)
            elif niezbadane:                # dolna granica: kopie niezbadane mogą nieść bajt
                liczba = i18n.t_plural("tasks.header_nonprintable_partial", niezbadane, m=calosc)
            elif niewiadome:
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
            elif key == "xref_reconcile_frames" and n > 0:
                # AR-135: zdanie NAZYWA cel - pary „nazwa → cel” ze stanu, gest z katalogu.
                tip = i18n.t("tasks.xref_reconcile_tip",
                             pairs=", ".join(state["xref_reconcile_pairs"]),
                             change=i18n.t("grid.sel.object_change"))
            elif key == "lineage_newer" and n > 0:
                # AR-153, AR-178: ile wejść czeka i gdzie oba gesty - przycisk panelu i pozycja menu
                # tabeli nazwane z katalogu.
                tip = i18n.t("tasks.lineage_newer_tip", n=state["lineage_newer_inputs"],
                             reject=i18n.t("grid.lin.reject_newer"),
                             all=i18n.t("grid.lin.reject_newer_all"), undo=i18n.t("grid.lin.undo"))
            if robota != n:                             # część liczby z decyzją - nie robota
                tip += _zdanie_podzbioru(key, n - robota)
            if niezbadane:
                # Podpowiedź nazywa PRZYCISK Dostawy jego napisem (AR-327) - nie etap „Fakty kopii”, którego
                # w Dostawie nikt nie widzi. Stan spoza `_stan_licznikow` (atrapy) - napis z samych bajtów. Napis
                # z modułu bez Qt (AR-337): wynik z tła nie importuje modułu Dostawy na wątku GUI.
                czekaja = state.get("copy_facts_waiting") or scan.CopyFactsWaiting(bytes=niezbadane)
                kopie = i18n.t_plural("tasks.header_nonprintable_unread_tip", niezbadane,
                                      gest=dostawa_bramka.etykieta_gestu_kopii(czekaja))
                tip = f"{tip}\n{kopie}" if tip else kopie
            elif czesciowe:
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
                # Rodzaj koloru zapisany w roli (AR-175) - `odswiez_motyw` przemalowuje z niego.
                rodzaj = (_RODZAJ_HISTORIA if key in _BEZ_ROBOTY else _RODZAJ_ZYWY if robota > 0
                          else _RODZAJ_NIEWIADOME if niewiadome else _RODZAJ_ZERO)
                it.setData(ROLA_RODZAJU_KOLORU, rodzaj)
                it.setForeground(_DIM["fg"] if rodzaj in _RODZAJE_SZARE else QBrush())
            if live:
                badge += 1
        self._fit_task_list()          # metryki fontu są prawdziwe dopiero po `show()`
        self.counts_changed.emit(badge)
        klucz, self._klik_czeka = self._klik_czeka, None
        if klucz is not None and self.isVisible() and self.pages.currentIndex() == _PAGE_LIST:
            # Klik sprzed pierwszego rachunku (`_klik_w_wiersz`) - na liczbach, które właśnie przyszły.
            self._on_task_clicked(next(self.tasks.item(r) for r, (k, _l, _a) in enumerate(_TASKS)
                                       if k == klucz))
        return badge

    def odswiez_motyw(self):
        """Zmiana motywu (gospodarz, `_on_theme`, AR-175): szarość wypalona w elementach listy idzie za
        motywem z ROLI rodzaju koloru zapisanej przy budowie i rachunku - bez rachunku stanu bazy, który
        `_on_theme` robił dotąd tylko po to, żeby wypalić nową szarość (1,4-2,6 s na kopii pf4). Wiersz
        bez rodzaju (akcyjny przed pierwszym rachunkiem) nie ma koloru do przemalowania."""
        for i in range(self.tasks.count()):
            it = self.tasks.item(i)
            rodzaj = it.data(ROLA_RODZAJU_KOLORU)
            if rodzaj in _RODZAJE_SZARE:
                it.setForeground(_DIM["fg"])
            elif rodzaj is not None:
                it.setForeground(QBrush())

    # ---------------------------------------------------------------- akcje

    def _on_task_clicked(self, item):
        key = item.data(Qt.UserRole)
        if key is None:                                # pozycja informacyjna — nie prowadzi nigdzie
            return
        if key in self._niewiadome:                    # „?": robota czeka w Dostawie (AR-28 (b))
            self.open_intake.emit()
            return
        action = next(a for k, _, a in _TASKS if k == key)
        if action == _OKNO_PRZEBIEGU:
            # Najstarszy przerwany przebieg; przy zerze klik niczego nie otwiera (okno bez
            # przebiegu nie ma czego pokazać), a wiersz jest szary.
            przebiegi = queries.interrupted_object_change_runs(self.con)
            if przebiegi:
                self.open_object_change_run.emit(przebiegi[0])
            return
        if isinstance(action, int):
            if action == _PAGE_TELESCOPE:
                self.otworz_os_teleskopu()
            else:
                self.pages.setCurrentIndex(action)     # podstrona osi
            if key in _KUBELEK_PODSTRONY:
                self._zaznacz_kubelek(_KUBELEK_PODSTRONY[key])
            elif key == "unresolved_lights":
                # Klatki bez obiektu mieszkają w kilku kubełkach kolejki - wejście zaznacza pierwszy
                # niepusty, więc lista klatek i gest stoją od razu (dwie interakcje, nie trzy).
                self.object_view.zaznacz_pierwszy_kubelek(ObjectAxisView.KUBELKI_OSI_OBIEKTU)
            elif key == "observatory_review_frames":
                # AR-74: ta sama droga dla osi stanowiska - baza od nowa i gest gotowy pod ręką.
                self.observatory_view.wejdz_po_wskazanie()
            elif key == "undo_unfinished":
                # AR-318: świeży odczyt tego samego predykatu co licznik (jak przebieg przerwany wyżej)
                # - recepta najstarszego commitu na pasku; przy zerze nic się nie podaje. Podstrona osi,
                # nie lista: po dokończeniu „← Porządki” przelicza liczniki i wiersz gaśnie.
                niedokonczone = queries.niedokonczone_cofniecia_kart(self.con)
                if niedokonczone:
                    self.object_view.podaj_dokonczenie_cofniecia(*niedokonczone[0])
        else:
            self.open_collection.emit(action)          # Zbiory z perspektywą (np. Duplikaty)

    def otworz_os_teleskopu(self):
        """Podstrona Osi teleskopu - jedna droga wejścia dla wiersza „Teleskopy bez etykiety" i dla
        gospodarza (menu „Więcej…" Domu). Wejście czyta bazę od nowa (wizytacja N4) - lustro
        `_zaznacz_kubelek`, które przeładowuje kolejkę przeglądu obiektów."""
        self.axis_view.refresh()
        self.pages.setCurrentIndex(_PAGE_TELESCOPE)

    def otworz_stanowiska(self):
        """Podstrona osi obserwatorium - wejście gospodarza (pusty stan planera „bez stanowiska”).
        Ta sama robota co wiersz Porządków, więc ta sama droga wejścia: licznik i fokus na geście."""
        self.pages.setCurrentIndex(_PAGE_OBSERVATORY)
        self.observatory_view.wejdz_po_wskazanie()

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
        # Stan mógł się zmienić w podstronie - ta sama droga co wejście w Porządki (AR-175), trybem widoku od montażu
        # (AR-337, AR-380): bez rachunku, gdy odcisk bazy bez zmian, w trybie wątków tła - rachunek w tle z listą
        # nieaktualną, a w pierwszej sekundzie po montażu czeka na bieg w drodze.
        self.odswiez_przy_wejsciu()
        # Fokus wraca na listę, na wiersz, z którego człowiek wszedł (AR-377 - pętla Popraw z klawiatury: strzałka,
        # Enter, „← Porządki”). Dotąd lista dostawała go przypadkiem łańcucha fokusu po schowaniu przycisku powrotu.
        self.fokus_z_klawiatury()
