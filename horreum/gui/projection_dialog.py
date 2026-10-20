"""Dialog „Wydaj na stół" (F2 redesignu — PLAN_ux_redesign §3; KROK 6 scalenia — warstwa widżetów).

Przebudowa wokół 1-klik: CELE ZAPAMIĘTANE (QSettings `projection/targets`, karty-radio + „+ inny
cel…", ostatnio użyty = domyślny — wchłania wiz #8), AUTO-DRY OFF-THREAD (R#6: DRY sonduje FS celu —
cel SMB/odpięty może wisieć; wyzwalany WYŁĄCZNIE zdarzeniami dyskretnymi: otwarcie dialogu, klik
karty celu, zmiana układu/przełącznika kopii) i AUTO-DECYZJA hardlink/kopia po wolumenach (R#4+R2-1:
seriale lokacji, które plan FAKTYCZNIE wybierze — pierwsza obecna per frame, D-P5 — po odrzuceniu
frame'ów bez obecnej kopii; JAKIKOLWIEK inny wolumen / `'?'` → kopia CAŁOŚCI, bo `apply` ma jedną
globalną flagę `copy`). Słownictwo per tryb (wchłania wiz #5): „skopiowano/do skopiowania" vs
„zlinkowano/do zlinkowania"; przycisk nazywa skutek i liczbę („Utwórz 131 kopii"). Rozmiar przy
kopii (R#5): suma po TEJ SAMEJ lokacji, którą wybiera plan, wyłącznie dla pozycji, które sonda
zostawiła do skopiowania (`would-link`); `size_bytes IS NULL` → „(+n plików bez rozmiaru)" zamiast
kłamliwej sumy. Sonda bez nic do zrobienia (komplet w celu) mówi to nagłówkiem raportu.

Ochrona przed stale-DRY (R2-2): licznik generacji — każde `_invalidate` inkrementuje; wynik DRY
niesie generację startu; handler przyjmuje WYŁĄCZNIE generację równą bieżącej (stale = odrzuć +
re-trigger). Sam wzorzec `_writeback_async` gridu tej ochrony NIE ma (writeback nie zmienia
parametrów w locie) — deklaracja off-thread bez licznika uzbroiłaby „Utwórz" pod starymi parametrami.

APPLY OFF-THREAD (P2/W1 — bramka pierwszego MASOWEGO wydania): `ApplyWorker` = bliźniak `DryWorker`
z paskiem determinowanym (procent + nota `done/total` i ETA — apply ZNA liczbę z planu, inaczej niż
sonda DRY) i „Przerwij wydawanie" łapiącym na granicy pliku. Na czas biegu parametry (cel/układ/
kopia/„Odśwież") są ZABLOKOWANE — `_invalidate` wyzerowałby `self._plan`, który worker właśnie
materializuje — a RAPORT jest przepisany: panel niósł tekst DRY („bez zmian na dysku") i przez cały
bieg kłamałby największą powierzchnią okna. Anulowanie (także zamknięcie okna w biegu) zostawia
CZĘŚCIOWE drzewo z manifestem (projekcja efemeryczna: undo = skasuj folder w Eksploratorze).

WYDANIE OBIEKTU (`object_id` zamiast `frame_ids`) to drugi tryb TEGO SAMEGO okna, nie drugie okno:
cele, auto-DRY, generacje, apply w tle i blokada parametrów są wspólne, różni się planista
(`projection.plan_object`), korzeń (`projection.object_root` - `<karta>/OBJECTS/<obiekt>`, liczony
raz w workerze DRY i ten sam oddany do `apply`) i manifest (`projection.object_manifest`). Decyzja
wolumenowa i rozmiar biorą klatki z POZYCJI planu, bo obiekt to lighty + mastery + surowe flaty,
a nie zbiór gridu. Wejściem jest okno teczek `ObjectPickDialog` (read-model
`queries.release_readiness`): wiersz na obiekt z kropką stanu, dwuklik prowadzi tutaj. Powrót do
obiektu, który już w całości leży w celu, kończy się od razu „Otwórz w Eksploratorze" - WBPP
wskazuje się folderem, a nie ma czego wydawać drugi raz.

NAPRAWA MANIFESTU (AR-213) to trzecia droga zapisu tego samego okna: sonda nad kompletem diagnozuje
manifest (`projection.repair_manifest` bez zapisu), a przy luce „Utwórz” staje się „Zapisz manifest”
ze złotą wagą - drugie kliknięcie, `ManifestWorker`, zero linków. Wydanie obiektu, które padło na
kroku manifestu, samo uruchamia świeżą sondę: pod głową błędu staje jej werdykt (oferta albo odmowa
z radą), nie przepowiednia. Zapis manifestu jest nieprzerywalny - zamknięcie okna w biegu czeka
na jego koniec i zamyka okno po zapisie.

Cała logika plan/link/sonda/guard w Qt-wolnej klindze `horreum.projection` (NIETKNIĘTA — §0 briefu);
tu glue widżetów + czyste pomocniki decyzji (Qt-wolne funkcje modułowe, testowane wprost). Walidacja
segmentu `_WBPP`/`_Review` przy DODAWANIU celu (raz); guard w klindze zostaje drugą linią. Plik na
whiteliście `test_gui_isolation` (warstwa widżetów — import PySide6 uprawniony)."""

from __future__ import annotations

import json
import os
import threading
import time

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import (
    QBrush, QColor, QDesktopServices, QFont, QFontDatabase, QFontMetricsF, QPalette, QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QProgressBar, QPushButton,
    QRadioButton, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
    QWidget,
)

from horreum import db, projection
from horreum.gui import facet_model, i18n, queries, theme
from horreum.gui.grid_panels import ElidedLabel
from horreum.gui.i18n_catalog import CATALOG
from horreum.gui.wb_worker import (   # błąd systemu w języku UI (AR-184), szczegół na pasek (AR-218)
    ZdanieZeSzczegolem, tekst_powodu, wiersz_systemu)
# odmowy klingi z kodem (AR-200); jedna reguła wyjątku workera okna (AR-214)
from horreum.item_reasons import powod_okna, powod_wyjatku
from horreum.volumes import volume_serial

_TREE_CAP = 30                        # ile folderów kategorii pokazać w raporcie dialogu
# Zawinięty wiersz raportu ciągnie się o tyle znaków GŁĘBIEJ niż jego własne wcięcie: kontynuacja
# od kolumny 0 (np. „2023-05-07)" po „(noce:") czytała się jak nowy wiersz najwyższego poziomu
# i łamała słupek, a wcięcie równe wierszom podrzędnym (4) myliłoby ją z nimi.
_REPORT_HANG = 4
_GOLD_HEIGHT = 34                     # wysokość złotej akcji - jak „Przyjmij nowe" Dostawy

# Kolory semantyczne raportu (nagłówek i wiersze luk) - z motywu (SPOT), wzorzec `grid._COLORS`.
# Raport jest QTextEdit, więc QSS ról (`theme.qss`) tu nie sięga: kolor bloku nakłada
# `QTextCharFormat`, a ten chce QColor.
_COLORS: dict[str, QColor] = {}


def use_theme(name):
    """Przeładuj kolory nagłówka raportu z motywu. Wołane przy imporcie oraz przez
    `app.apply_theme`; dialog jest modalny i krótkotrwały, więc bierze kolor przy każdym pisaniu."""
    a = theme.accents(name)
    _COLORS.update({"ok": QColor(a["ok_green"]), "warn": QColor(a["warn"]),
                    "error": QColor(a["exclusion_red"])})


use_theme(theme.DEFAULT)


# ---------------------------------------------------------------- cele wydania (QSettings)

def _settings():
    return QSettings("Horreum", "Horreum")


def _canon_path(path):
    """Jedna postać zapisu celu: ścieżka bezwzględna, `normpath` (separatory systemowe, bez `..`
    i podwójnych separatorów). Wielkość liter ZOSTAJE - karta trafia do manifestów i do nazw
    katalogów zakładanych przy wydaniu, więc zapis małymi literami przemianowałby `X:\\Praca_WBPP`
    na dysku; wielkość liter nie rozróżnia wyłącznie klucz porównania (`_target_key`)."""
    return os.path.normpath(os.path.abspath(str(path)))


def _target_key(path):
    """Klucz porównania celów: ta sama karta zapisana z `/` albo `\\`, z inną wielkością liter
    albo z końcowym separatorem to jeden cel."""
    return os.path.normcase(_canon_path(path))


def _load_targets():
    raw = _settings().value("projection/targets", "[]")
    try:
        targets = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(targets, list):
        return []
    return [t for t in targets if isinstance(t, dict) and t.get("path")]


def remember_target(name, path, *, select=True):
    """Zapamiętaj kartę celu wydania (`projection/targets`) - JEDYNA droga zapisu: dialog wydania
    i menu „Folder roboczy WBPP…” składają kartę tą samą funkcją, więc nie rozjadą się w postaci
    ścieżki. Dedup po `_target_key` (ten sam cel → nowa nazwa, karta na końcu listy); zapisana
    jest postać kanoniczna. `select=True` ustawia ją też jako ostatnio użytą
    (`projection/last_target`), czyli domyślnie zaznaczoną przy następnym otwarciu okna wydania.
    Zero dysku. Zwraca zapisaną ścieżkę."""
    canon = _canon_path(path)
    klucz = os.path.normcase(canon)
    cele = [t for t in _load_targets() if _target_key(t["path"]) != klucz]
    cele.append({"name": name, "path": canon})
    ustawienia = _settings()
    ustawienia.setValue("projection/targets", json.dumps(cele, ensure_ascii=False))
    if select:
        ustawienia.setValue("projection/last_target", canon)
    return canon


def card_name(name):
    """Nazwa karty na ekran (Qt-wolne). Karta folderu roboczego dostaje nazwę z katalogu w języku
    CHWILI ZAPISU (`app._on_work_root` składa ją `i18n.t("proj.work_card")`), więc karta założona
    po polsku mówiła „Folder roboczy" w UI angielskim. Nazwę, która jest którymkolwiek tłumaczeniem
    tego klucza, pokazujemy w bieżącym języku; zapis w ustawieniach zostaje bez zmian, a nazwa
    nadana przez człowieka - jak ją nadał."""
    if name in CATALOG["proj.work_card"].values():
        return i18n.t("proj.work_card")
    return name


def target_roots():
    """Korzenie zapamiętanych kart w postaci kanonicznej, bez powtórzeń (kolejność zapisu) - lista
    wydań okna żniw szuka wyników WBPP pod każdą z nich."""
    widziane, korzenie = set(), []
    for t in _load_targets():
        canon = _canon_path(t["path"])
        klucz = os.path.normcase(canon)
        if klucz not in widziane:
            widziane.add(klucz)
            korzenie.append(canon)
    return korzenie


# ---------------------------------------------------------------- pomocniki Qt-WOLNE (testowane wprost)

def chosen_present(rows):
    """LUSTRO wyboru źródła `projection.plan` (D-P5): pierwsza OBECNA location per frame, w porządku
    zapytania (`ORDER BY frame_id, location_id`). Frame BEZ obecnej kopii (location_id NULL z LEFT
    JOIN) ODPADA — idzie do `skipped` planu i NIE uczestniczy w decyzji wolumenowej (R2-1: inaczej
    jedna zniknięta klatka fałszywie przełączałaby całość na kopię). `PlanItem` nie niesie volume,
    stąd powtórzona selekcja na `present_locations`, nie `plan.items` (brief §3)."""
    by_frame = {}
    for r in rows:
        if r["location_id"] is None:
            continue
        by_frame.setdefault(int(r["frame_id"]), r)
    return list(by_frame.values())


def volume_decision(chosen, target_serial):
    """Auto hardlink/kopia (R#4): True = KOPIA. WSZYSTKIE wybrane lokacje na wolumenie celu →
    hardlink; JAKIKOLWIEK inny / `'?'` (placeholder skanu = wolumen nieznany) / nieustalony serial
    celu (None) → kopia CAŁOŚCI (konserwatywnie — `apply` ma jedną globalną flagę `copy`).
    `location.volume` jest NOT NULL w schemacie, więc „None-serial" źródła nie istnieje."""
    if target_serial is None:
        return True
    vols = {r["volume"] for r in chosen}
    return bool(vols - {target_serial}) or "?" in vols


def size_summary(chosen):
    """Suma rozmiaru kopii po WYBRANYCH lokacjach (TYCH SAMYCH, które wybiera plan — R#5; nie po
    wszystkich obecnych: frame w >1 kopii zawyżyłby sumę o duplikaty). `size_bytes IS NULL` liczony
    OSOBNO — „(+n plików bez rozmiaru)" zamiast kłamliwej sumy. Zwraca (total_bytes, n_bez_rozmiaru)."""
    total = 0
    missing = 0
    for r in chosen:
        sb = r["size_bytes"]
        if sb is None:
            missing += 1
        else:
            total += int(sb)
    return total, missing


def format_bytes(n):
    """Rozmiar czytelnie: 999 B → 1.2 MB → 3.4 GB (dziesiętnie po jednostkach 1024)."""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024


def eta_text(done_n, total, elapsed_s, warmup=5):
    """Pozostały czas z zaobserwowanego tempa — „ · pozostało ~14 min" albo PUSTY łańcuch (Qt-wolne).
    Kopia bajtów przez SMB idzie godzinami: sam licznik „12345/15890" nie mówi, czy zostało 5 minut
    czy 3 godziny (wiz #5). Pierwsze `warmup` plików pomijane — tempo z 1–2 próbek potrafi kłamać
    o rząd wielkości, a cofająca się prognoza jest gorsza niż jej brak."""
    if done_n < warmup or done_n >= total or elapsed_s <= 0:
        return ""
    remaining = (total - done_n) * (elapsed_s / done_n)
    if remaining < 90:
        return i18n.t("proj.eta_s", n=int(remaining))
    if remaining < 5400:
        return i18n.t("proj.eta_min", n=int(round(remaining / 60)))
    return i18n.t("proj.eta_h", h=remaining / 3600)


def report_head_key(res, *, partial):
    """Wynik wydania → KLUCZ nagłówka raportu (Qt-WOLNE, testowane wprost). JEDEN właściciel dla
    tekstu i koloru: `report_outcome` czyta ten sam rozbiór, więc czasownik i akcent nie mogą się
    rozjechać.

    Czwarty stan `head_nothing_new` wszedł po wizytacji P-C #1: powtórne wydanie na ten sam cel
    dawało „**Utworzono** … zlinkowano: 0 istniało: 4" — czasownik obiecywał czynność, której nie
    było, a nowy zielony akcent tę nieprawdę POGŁOŚNIŁ. Kolor wzmacnia komunikat, więc komunikat
    musi być prawdziwy wcześniej. „Komplet już w celu" to nie porażka — stąd rola nadal `ok`."""
    if res.cancelled:
        return "proj.head_cancelled"
    if partial:
        return "proj.head_partial"
    return "proj.head_created" if res.counts.get("linked", 0) else "proj.head_nothing_new"


def dry_complete(res):
    """Sonda zastała KOMPLET w celu (Qt-WOLNE, testowane wprost): nic do utworzenia, coś już leży,
    żadnego konfliktu ani błędu. Bez tego stanu powrót do wydanego obiektu kończył się nagłówkiem
    „DRY" nad zerem do zrobienia i wygaszonym „Utwórz 0 kopii" - prawdziwym, ale bez odpowiedzi na
    jedyne pytanie, z którym user wraca: czy folder jest gotowy pod WBPP. Błąd sondy wyklucza
    komplet, bo pozycja, której nie dało się odczytać, nie jest „już w celu"; `skipped` nie
    wyklucza - tych klatek żadne wydanie nie położy, a liczba stoi w słupku pod nagłówkiem."""
    c = res.counts
    return (not res.cancelled and not c.get("would-link", 0) and c.get("exists", 0) > 0
            and not c.get("conflict", 0) and not c.get("error", 0))


def manifest_offer_lines(naprawa):
    """Wiersze oferty „Zapisz manifest” (Qt-WOLNE, testowane wprost) z diagnozy `would-write`
    (`projection.repair_manifest`, AR-213): CZYM zapis różni się od manifestu w folderze (brak go;
    listy id albo zestawy - zdanie neutralne, bo zapis bywa samym zapominaniem; same nazwy plików;
    sam czas - próby wydania albo data z drzewa nad manifestem bez daty), ile par id zapis dopisze
    (`dodane`, AR-245), ile id wcześniejszych wydań zostaje i ile schodzi, ile klatek planu bez kopii
    i id bez dowodu manifest wymieni jak wydanie (`bez_kopii`, `niepewne`, AR-240), skąd data
    wydania (z drzewa) albo że jej nie będzie (żniwa: bez „czeka na WBPP”) i których folderów
    korzenia nie opisze. Dawniej każda luka mówiła „dopisze brakujące” - także sam brak nazw i samo
    zapominanie - a zapis, który usuwa id, nie podawał ich liczby przed kliknięciem."""
    z_drzewa = naprawa.payload.get("ts_source") == projection.TS_SOURCE_TREE
    if naprawa.stan == "missing":
        linie = [i18n.t("proj.obj.manifest_missing")]
    elif set(naprawa.roznice) & {"sets", "ids", "cancelled"}:
        linie = [i18n.t("proj.obj.manifest_stale")]
    elif "names" in naprawa.roznice:
        linie = [i18n.t("proj.obj.manifest_stale_names")]
    elif z_drzewa:
        linie = [i18n.t("proj.obj.manifest_stale_ts_tree")]
    else:
        linie = [i18n.t("proj.obj.manifest_stale_ts")]
    if naprawa.dodane:
        linie.append(i18n.t("proj.obj.manifest_will_add", n=naprawa.dodane))
    if naprawa.kept or naprawa.dropped:
        linie.append(i18n.t("proj.obj.manifest_will_keep", kept=naprawa.kept, dropped=naprawa.dropped))
    return linie + manifest_fact_lines(naprawa)


def manifest_fact_lines(naprawa, *, foldery=True):
    """Wiersze faktów o treści zapisu naprawy manifestu - wspólne dla oferty (`manifest_offer_lines`)
    i raportu po zapisie (Qt-WOLNE): klatki planu bez obecnej kopii i id wcześniejszych wydań bez
    dowodu w drzewie, które manifest wymienia jak wydanie (AR-240), data wydania z drzewa albo jej
    brak i - w ofercie (`foldery`) - foldery korzenia, których manifest nie opisze."""
    linie = []
    if naprawa.bez_kopii:
        linie.append(i18n.t("proj.obj.manifest_no_copy", n=naprawa.bez_kopii))
    if naprawa.niepewne:
        linie.append(i18n.t("proj.obj.manifest_unproven_kept", n=naprawa.niepewne))
    if naprawa.payload.get("ts_source") == projection.TS_SOURCE_TREE:
        linie.append(i18n.t("proj.obj.manifest_ts_tree"))
    elif naprawa.payload.get("ts") is None:
        linie.append(i18n.t("proj.obj.manifest_no_ts"))
    if foldery and naprawa.obce_foldery:
        linie.append(i18n.t("proj.obj.manifest_only_sets", sets=", ".join(naprawa.payload["zestawy"]),
                            other=", ".join(naprawa.obce_foldery)))
    return linie


# Kody odmów i błędów kroku manifestu, których szczegół bez tekstu systemu to ścieżka pliku manifestu
# (`szczegol_powodu`, AR-262): zdanie mówi, co z manifestem, a plik do sprawdzenia stoi pod kursorem.
_KODY_PLIKU_MANIFESTU = frozenset({"proj_manifest_damaged", "proj_manifest_foreign",
                                   "proj_manifest_changed", "proj_manifest_failed",
                                   "proj_manifest_unreadable"})


def szczegol_powodu(powod, *, root):
    """Podpowiedź raportu i paska przy błędzie zapisu (Qt-WOLNE): szczegół systemu (`wiersz_systemu`),
    a bez niego przy kroku manifestu - plik, którego dotyczy zdanie: drzewo niekompletne
    (`proj_manifest_incomplete`) - folder wydania, w którym brakuje plików; cudzy plik roboczy
    (`proj_manifest_busy`) - ten plik; manifest uszkodzony, obcy, zmieniony w trakcie albo niezapisany
    tekstem spoza klas - plik manifestu (ścieżka z powodu albo `root/_PROJEKCJA.json` korzenia biegu).
    `root` OBOWIĄZKOWY: pominięty po cichu dawał pusty szczegół czterem kodom, a z nim zdanie paska
    gasnące po 5 s - wołający (biegi zapisu) znają korzeń zawsze (`_on_apply` stawia `_apply_root`).
    PO ZAMKNIĘCIU OKNA (AR-262): zdanie paska gospodarza ze szczegółem nie gaśnie zegarem (`_flash`),
    więc każda odmowa kroku manifestu niesie szczegół - bez niego gasła po 5 s, a okno, z którego
    przyszła, bywa już zamknięte (Esc w biegu zapisu)."""
    wiersz = wiersz_systemu(powod)
    kod = getattr(powod, "code", None)
    if wiersz:
        return wiersz
    params = dict(getattr(powod, "params", ()))
    if kod == "proj_manifest_incomplete":
        return i18n.t("proj.manifest_folder_tip", dir=params["dir"]) if params.get("dir") else ""
    if kod == "proj_manifest_busy":
        return i18n.t("proj.manifest_part_tip", path=params["path"]) if params.get("path") else ""
    if kod in _KODY_PLIKU_MANIFESTU:
        sciezka = params.get("path") or (os.path.join(root, projection.MANIFEST_NAME) if root else None)
        return i18n.t("proj.manifest_path_tip", path=sciezka) if sciezka else ""
    return ""


def zdanie_odmowy(powod):
    """Zdanie powodu w ŻYWYM oknie wydania (Qt-WOLNE, AR-251): `tekst_powodu`, a za odmową kroku
    manifestu, którą da się ponowić z okna - gest okna (`proj_manifest_damaged`/`_foreign`: „Odśwież
    podgląd” i „Zapisz manifest”, `proj_manifest_busy`: ponowienie wydania albo „Odśwież podgląd”).
    Zdanie rdzenia mówi fakt i radę wspólną dla każdej powierzchni (CLI drukuje je z własnym gestem);
    pasek gospodarza po zamknięciu okna mówi samym `tekst_powodu` - przycisku zamkniętego okna nie ma."""
    kod = getattr(powod, "code", None)
    if kod in ("proj_manifest_damaged", "proj_manifest_foreign"):
        return i18n.t("proj.manifest_retry", msg=tekst_powodu(powod))
    if kod == "proj_manifest_busy":
        return i18n.t("proj.manifest_busy_retry", msg=tekst_powodu(powod))
    return tekst_powodu(powod)


def czas_proby_dla(po_awarii, root):
    """Czas nieudanej próby wydania (`po_awarii` = `(korzeń, czas)`, `ProjectionDialog._ts_po_awarii`)
    dla korzenia `root` albo None (Qt-WOLNE) - JEDNO źródło `ts` naprawy manifestu dla oferty sondy
    (`DryWorker`) i zapisu (`_zapisz_manifest`), AR-245: oferta mówi o tym samym czasie, który zapis
    postawi (dawniej sonda liczyła bez niego i zapowiadała datę z drzewa albo brak daty)."""
    if po_awarii is None or _target_key(po_awarii[0]) != _target_key(root):
        return None
    return po_awarii[1]


def report_outcome(res, *, partial):
    """Wynik wydania → rola koloru nagłówka raportu: `ok` | `warn` (Qt-WOLNE, testowane wprost).

    ZIELONO znaczy PEŁNY sukces i nic poza tym. Anulowanie, wynik częściowy oraz KAŻDY niezerowy
    licznik kłopotu (`conflict`/`error`/`verify_bad`/`skipped`) schodzą na bursztyn — inaczej
    „Utworzono" świeciłoby na zielono nad słupkiem mówiącym „konflikt: 40", a wizytacja P2 zgłosiła
    właśnie to: jednolity szary nie odróżniał wydania czystego od wydania z dziurami. Błąd wydania
    (`proj.apply_error`) nie przechodzi tędy — tam koloru nie ma czego wyliczać, jest wprost."""
    c = res.counts
    if res.cancelled or partial:
        return "warn"
    return "warn" if any(c.get(k, 0) for k in ("conflict", "error", "verify_bad", "skipped")) else "ok"


def _elide_path(path, cap=64):
    """Elizja długiej ścieżki celu ŚRODKIEM (wiz K3: pełna ścieżka na karcie dyktowała minimum
    szerokości dialogu). Pełna wersja idzie w tooltip karty."""
    if len(path) <= cap:
        return path
    half = (cap - 1) // 2
    return path[:half] + "…" + path[-half:]


# Układ wydania (token klingi `projection.LAYOUTS` / `OBJECT_LAYOUT`) → nazwa w raporcie. Mapa
# literałów, nie klucz składany w locie: kolektor kluczy `test_i18n` widzi tylko literały, parytet
# tokenów z katalogiem pilnuje test tego okna. Token to nazwa DYSKOWA (manifest, CLI) - na ekranie
# „układ wbpp-obiekt" był surowym tokenem, w UI angielskim do tego polskim.
_LAYOUT_KEYS = {
    "po-obiektach": "proj.layout_name.by_object",
    "wbpp-feed": "proj.layout_name.wbpp_feed",
    projection.OBJECT_LAYOUT: "proj.layout_name.object",
}


def layout_text(token):
    """Nazwa układu do raportu (Qt-wolne). Token spoza mapy zostaje sobą - nowy układ klingi ma być
    widoczny, nie zamieniony w pustkę ani w klucz katalogu."""
    key = _LAYOUT_KEYS.get(token)
    return i18n.t(key) if key else token


# Poziom kształtu drzewa (nazwa kolumny układu kolumnowego albo segmentu wydania obiektu, z historią:
# manifest niesie kształt z dnia wydania - `telescope_label` sprzed coalesce P2) → słowo katalogu.
# Mapa literałów jak `_LAYOUT_KEYS`; parytet z `projection.LAYOUTS`/`OBJECT_SEGMENTS` pilnuje test.
_SHAPE_LEVEL_KEYS = {
    "object_canon": "proj.shape.object_canon",
    "filter_canon": "proj.shape.filter_canon",
    "telescope_label": "proj.shape.telescope_label",
    "telescop_canon": "proj.shape.telescop_canon",
    "zestaw": "proj.shape.zestaw",
    "rola": "proj.shape.rola",
    "filtr": "proj.shape.filtr",
    "relacja": "proj.shape.relacja",
}


def _shape_text(layout, levels):
    """Kształt drzewa słowami (Qt-wolne): „obiekt do WBPP (zestaw / rodzaj klatki / filtr albo
    rodzaj kalibracji)”. `levels` - poziomy od góry, każdy krotką możliwości.

    Manifest historyczny, ręcznie zmieniony albo z nowszej wersji niesie dowolne `segments`
    (`projection.manifest_drift`), więc to, czego mapy nie znają, mówi słowem katalogu, nie surową
    wartością (bramka odbioru 0.19.0, Z10): poziom spoza mapy - „nieznany poziom”, układ spoza
    `_LAYOUT_KEYS` - „nieznany układ”, brak poziomów - „poziomy nieopisane”. Powtórzone słowo
    w jednym poziomie stoi raz („nieznany poziom albo nieznany poziom” niczego nie mówi). Surowa
    wartość zostaje w `_PROJEKCJA.json`."""
    lub = i18n.t("proj.shape_or")
    poziomy = []
    for mozliwe in levels:
        slowa = [i18n.t(_SHAPE_LEVEL_KEYS[c]) if c in _SHAPE_LEVEL_KEYS else i18n.t("proj.shape_unknown")
                 for c in mozliwe]
        poziomy.append(lub.join(dict.fromkeys(slowa)))
    nazwa = layout_text(layout) if layout in _LAYOUT_KEYS else i18n.t("proj.shape_unknown_layout")
    if not poziomy:
        return i18n.t("proj.shape_no_levels", layout=nazwa)
    return i18n.t("proj.shape", layout=nazwa, levels=" / ".join(poziomy))


def drift_text(was, layout):
    """Zdanie rozjazdu układu (Qt-wolne, odbiór 0.19.0 WY7): co zastano w folderze i czego Horreum
    oczekuje - słowami, nie maszynowym zapisem `projection._shape` („wbpp-obiekt: zestaw/rola/
    filtr|relacja”, format rdzenia dla powierzchni). `was` - `ApplyResult.drift`, rozbiór odwrotny
    do `_shape`; oczekiwane z `projection.layout_segments(layout)`, bez przejścia przez napis."""
    stary_uklad, _, poziomy = was.partition(": ")
    zastane = [tuple(p.split("|")) for p in poziomy.split("/") if p] if poziomy else []
    oczekiwane = [s if isinstance(s, tuple) else (s,) for s in projection.layout_segments(layout)]
    return i18n.t("proj.drift", was=_shape_text(stary_uklad, zastane),
                  now=_shape_text(layout, oczekiwane))


def tree_folder_text(segments):
    """Folder drzewa planu do raportu (Qt-wolne): segmenty złączone `/`, segment `_UNSET` (folder
    bez wartości - na dysku zostaje, kontrakt drzewa) jako „(brak danych)” (odbiór 0.19.0 WY5)."""
    return "/".join(i18n.t("proj.tree_unset") if s == projection._UNSET else s for s in segments)


def zestaw_name(seg):
    """Nazwa zestawu w wierszu raportu (Qt-wolne): „zestaw RC8_ASI2600MM” albo - lighty bez configu
    (folder `_UNSET`) - „bez zestawu (teleskop × kamera nieprzypisane)” (odbiór 0.19.0 WY5)."""
    if seg == projection._UNSET:
        return i18n.t("proj.obj.zestaw_unset")
    return i18n.t("proj.obj.zestaw_name", seg=seg)


# Luki flatu z `lineage.raw_flats_for` → zdanie katalogu. Mapa, nie klucz składany w locie: kolektor
# kluczy (`test_i18n`) widzi tylko literały w `t(...)`, a parytet tokenów z katalogiem pilnuje test
# tego okna. `pending` ma tu zdanie, choć do `flat_gaps` planu nie trafia (osobna lista) - linia
# „do przeliczenia w Dostawie" tłumaczy się nim, żeby powód stał przy liczbie.
_FLAT_GAP_KEYS = {
    "incomplete_recipe": "proj.obj.gap.incomplete_recipe",
    "no_profile": "proj.obj.gap.no_profile",
    "pending": "proj.obj.gap.pending",
    "no_raw": "proj.obj.gap.no_raw",
    "out_of_window": "proj.obj.gap.out_of_window",
    "no_time": "proj.obj.gap.no_time",
}


def flat_gap_text(token, window_days):
    """Zdanie dla tokenu luki flatu (Qt-wolne). `window_days` wchodzi do zdania `out_of_window` -
    „poza oknem" bez liczby nie pozwala zdecydować, czy poszerzyć okno, czy dokupić flaty. Token
    spoza mapy renderuje klucz (fallback katalogu), nie pustkę: nowy token rdzenia ma być widoczny."""
    return i18n.t(_FLAT_GAP_KEYS.get(token, f"proj.obj.gap.{token}"), days=window_days)


def object_totals(info):
    """Liczby nagłówka wydania obiektu z `Projection.info` (Qt-wolne, testowane wprost). Lighty
    sumą zestawów (light należy do jednego); mastery i surowe flaty jako DISTINCT klatek - master
    wspólny dwóch zestawów to dwie pozycje planu, ale JEDEN master, a nagłówek mówi o archiwum,
    nie o folderach. `pending` osobno: „do przeliczenia w Dostawie" to nie brak flatu."""
    zestawy = info["zestawy"].values()
    return {
        "lights": sum(len(z["lights"]) for z in zestawy),
        "masters": len({m for z in zestawy for ids in z["masters"].values() for m in ids}),
        "raw": len({f for z in zestawy for f in z["flat_raw"]}),
        "bez_flatu": sum(len(z["bez_flatu"]) for z in zestawy),
        "bez_darka": sum(len(z["bez_darka"]) for z in zestawy),
        "pending": sum(len(z["pending"]) for z in zestawy),
    }


def object_gaps_text(totals):
    """Luki nagłówka wydania obiektu - „bez flatu 311 · bez darka 556" - wyłącznie części niezerowe,
    pusty łańcuch przy komplecie (Qt-wolne). Osobny wiersz w roli `warn`: w jednym zdaniu z liczbami
    tego, co JEST, luki miały ich wagę i kolor, a zero luki pod rolą ostrzeżenia ostrzegałoby przed
    niczym. `pending` ma własną linię (`proj.obj.pending_head`) - to inna robota niż brak klatek."""
    czesci = []
    if totals["bez_flatu"]:
        czesci.append(i18n.t("proj.obj.head_no_flat", n=totals["bez_flatu"]))
    if totals["bez_darka"]:
        czesci.append(i18n.t("proj.obj.head_no_dark", n=totals["bez_darka"]))
    return " · ".join(czesci)


def object_report_lines(info):
    """Sekcja raportu wydania obiektu: wiersz na zestaw (lighty, godziny, mastery per relacja,
    surowe flaty z nocami), pod nim - tylko gdy niezerowe - bez flatu z rozbiciem na powody, bez
    darka i do przeliczenia w Dostawie (Qt-wolne). Powody stoją przy liczbie, bo „bez flatu: 311"
    nie mówi, czy trzeba dokupić klatki, poszerzyć okno, czy poprawić nagłówek. Nazwy relacji
    (`flat`, `dark`) to wartości domenowe - zostają nietłumaczone (D-L3).

    Zwraca pary `(wiersz, rola)`: wiersze luk niosą rolę `warn` (raport maluje je kolorem roli,
    jak nagłówek okna), wiersz zestawu - `None`."""
    lines = []
    okno = info["window_days"]
    for seg, z in info["zestawy"].items():
        mastery = ", ".join(f"{rel} {len(ids)}" for rel, ids in z["masters"].items()) or "0"
        surowe = i18n.t_plural("proj.obj.n_raw_flats", len(z["flat_raw"]))
        if z["flat_raw_nights"]:
            surowe += i18n.t("proj.obj.nights", nights=", ".join(z["flat_raw_nights"]))
        lines.append((i18n.t("proj.obj.zestaw_line", name=zestaw_name(seg),
                             lights=i18n.t_plural("proj.obj.n_lights", len(z["lights"])),
                             hours=z["hours"], masters=mastery, raw=surowe), None))
        if z["bez_flatu"]:
            powody = "; ".join(f"{flat_gap_text(tok, okno)}: {n}" for tok, n in
                               sorted(z["flat_gaps"].items(), key=lambda kv: (-kv[1], kv[0])))
            lines.append((i18n.t("proj.obj.no_flat_line", n=len(z["bez_flatu"]), why=powody), "warn"))
        if z["bez_darka"]:
            lines.append((i18n.t("proj.obj.no_dark_line", n=len(z["bez_darka"])), "warn"))
        if z["pending"]:
            lines.append((i18n.t("proj.obj.pending_line", n=len(z["pending"]),
                                 why=flat_gap_text("pending", okno)), "warn"))
    return lines


# ---------------------------------------------------------------- worker auto-DRY (wątek tła)

class DryWorker(QObject):
    """Auto-DRY poza wątkiem GUI (R#6). Otwiera WŁASNE połączenie po `db_path` (con nie przechodzi
    między wątkami — check_same_thread); tryb inline (testy / `:memory:`) dostaje żywe `con`
    wołającego i działa synchronicznie. Wynik niesie GENERACJĘ startu (R2-2) — handler dialogu
    odrzuca stale. `request_cancel` łapie na granicy pliku (kontrakt `should_cancel` klingi).

    `object_id` przełącza planistę na wydanie obiektu (`plan_object`, opcjonalnie jeden zestaw
    `config_id`); wtedy `root` to KARTA celu, a sondowany korzeń `<karta>/OBJECTS/<obiekt>` składa
    `projection.object_root` TUTAJ i oddaje w payloadzie - apply bierze dokładnie ten, który
    sondował DRY, zamiast składać go drugi raz."""

    done = Signal(int, object)        # (generacja, payload: plan/res/decyzja/rozmiar/korzeń)
    # (generacja, powód) - `object`: `Signal(str)` zgubiłby kod błędu systemu klasą (AR-184)
    failed = Signal(int, object)
    finished = Signal()

    def __init__(self, db_path, frame_ids, layout, root, force_copy, now, gen, con=None,
                 object_id=None, config_id=None, po_awarii=None):
        super().__init__()
        self._db_path = db_path
        self._con = con
        self._frame_ids = list(frame_ids)
        self._layout = layout
        self._root = root
        self._force_copy = force_copy
        self._now = now
        self._gen = gen
        self._object_id = object_id
        self._config_id = config_id
        self._po_awarii = po_awarii      # (korzeń, czas) nieudanej próby wydania - `czas_proby_dla`
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    @Slot()
    def run(self):
        try:
            self.done.emit(self._gen, self._compute())
        except Exception as exc:
            # Szczerze, nie cicha śmierć wątku - jedna reguła wyjątku okna (`powod_okna`): odmowa
            # strażnika korzenia z kodem (AR-200), błąd systemu sondy FS albo bazy klasą, a goły
            # `ValueError` rdzenia (EXPECT, np. „nieznany obiekt”) - błąd programu w języku UI
            # z prozą rdzenia w szczególe (AR-214).
            self.failed.emit(self._gen, powod_okna(exc))
        finally:
            self.finished.emit()

    def _compute(self):
        own = bool(self._db_path)
        con = db.connect(self._db_path) if own else self._con
        try:
            if self._object_id is not None:
                plan = projection.plan_object(con, self._object_id, config_id=self._config_id)
                rows = queries.present_locations(con, sorted({it.frame_id for it in plan.items}))
            else:
                plan = projection.plan(con, self._frame_ids, self._layout)
                rows = queries.present_locations(con, self._frame_ids)
            root = projection.object_root(self._root, plan) if self._object_id is not None else self._root
            chosen = chosen_present(rows)
            target_serial = volume_serial(root)
            auto_copy = volume_decision(chosen, target_serial)
            eff_copy = bool(self._force_copy) or auto_copy
            res = projection.apply(plan, root, do_apply=False, copy=eff_copy, now=self._now,
                                   should_cancel=lambda: self._cancel)
            # Wydanie obiektu (AR-213): świadkowie scalenia manifestu bez utraty dla `apply` i - gdy
            # komplet leży w celu bez rozjazdu układu - diagnoza manifestu (bez zapisu, na tej sondzie).
            # Obie słuchają anulowania (AR-245): zamknięcie okna w trakcie sondy nie czeka ani na
            # odczyt świadków z bazy i manifestu, ani na świadka drzewa - wyniku nikt nie odbierze.
            naprawa, zrodla = None, None
            if self._object_id is not None and not self._cancel:
                zrodla = projection.manifest_sources(con, root)
                if dry_complete(res) and res.drift is None and not self._cancel:
                    # Ten sam czas próby co zapis (`czas_proby_dla`, AR-245): oferta mówi o dacie,
                    # którą zapis postawi.
                    naprawa = projection.repair_manifest(
                        con, plan, root, copy=eff_copy, now=self._now,
                        manifest=projection.object_manifest(plan),
                        ts=czas_proby_dla(self._po_awarii, root), sonda=res,
                        should_cancel=lambda: self._cancel)
                    if naprawa.status == "cancelled":
                        naprawa = None
        finally:
            if own:
                con.close()
        # Rozmiar kopii to bajty, które wydanie NAPRAWDĘ skopiuje: wyłącznie pozycje `would-link`
        # sondy. Liczony po całym planie obiecywał przy ponownym wydaniu gigabajty plików, które już
        # leżą w celu (`exists`). Pozycja, nie klatka: master wspólny dwóch zestawów to dwie kopie
        # na dysku, a lokacja każdej to ta sama pierwsza obecna, którą wybiera plan (`chosen_present`).
        by_frame = {int(r["frame_id"]): r for r in chosen}
        total, missing = size_summary(
            [by_frame[r.frame_id] for r in res.results if r.status == "would-link"])
        # Folder korzenia na dysku (odbiór 0.19.0 WY6): „Otwórz w Eksploratorze" przy powrocie do
        # obiektu wydanego wcześniej, także gdy sonda nie zastała kompletu. Odczyt w wątku tła, jak
        # reszta sondy - korzeń bywa na udziale SMB.
        return {"plan": plan, "res": res, "auto_copy": auto_copy, "copy": eff_copy,
                "target_serial": target_serial, "size_total": total, "size_missing": missing,
                "root": root, "manifest": naprawa, "extra_sources": zrodla,
                "root_exists": os.path.isdir(root)}


# ---------------------------------------------------------------- worker apply (wątek tła)

class ApplyWorker(QObject):
    """REALNE wydanie (linki/kopie) poza wątkiem GUI — bliźniak `DryWorker` (P2/W1). DB nie tyka:
    plan jest już policzony, `projection.apply` czyta WYŁĄCZNIE filesystem — stąd, inaczej niż
    `WritebackWorker` gridu, żadnego własnego połączenia. `progress` per plik (rdzeń woła Qt-wolny
    callback synchronicznie w TYM wątku); `request_cancel` przez `threading.Event` (jak
    `WritebackWorker` — flaga stawiana w wątku głównym, czytana tu) łapie na GRANICY PLIKU.
    `ProjectionAbort` (sonda pierwszego linku) idzie OSOBNYM sygnałem z wynikiem częściowym — to
    werdykt o wolumenie, nie awaria. Krok wydania przerwany błędem systemu (AR-197) wraca `done`
    z wynikiem niosącym powód (`ApplyResult.error`) - liczby tego, co zaszło, zostają w raporcie."""

    progress = Signal(int, int, str, str)   # done, total, dst, status — MID-apply
    done = Signal(object)                   # ApplyResult (może nieść cancelled=True albo error)
    # powód z kodem (`ProjectionAbort.powod`, AR-200), CZĘŚCIOWY ApplyResult (sonda hardlinka)
    aborted = Signal(object, object)
    failed = Signal(object)                 # powód wyjątku → sygnał, NIE crash apki (kod: AR-184)
    finished = Signal()                     # run() wrócił KAŻDĄ drogą → quit wątku

    def __init__(self, plan, root, copy, now, manifest, extra_sources=None):
        super().__init__()
        self._plan = plan
        self._root = root
        self._copy = copy
        self._now = now
        self._manifest = manifest
        self._extra_sources = extra_sources   # świadkowie scalenia manifestu bez utraty (AR-213)
        self._cancel = threading.Event()

    def request_cancel(self):
        self._cancel.set()

    @Slot()
    def run(self):
        try:
            res = projection.apply(self._plan, self._root, do_apply=True, copy=self._copy,
                                   now=self._now, manifest=self._manifest,
                                   extra_sources=self._extra_sources,
                                   progress=self._emit_progress, should_cancel=self._cancel.is_set)
        except projection.ProjectionAbort as exc:
            self.aborted.emit(powod_wyjatku(exc), exc.result)
        except Exception as exc:
            # Strażnik korzenia (druga linia), `OSError` spoza kroków wydania, EXPECT rdzenia -
            # szczerze, nie cicha śmierć wątku, jedną regułą wyjątku okna (`powod_okna`, AR-214).
            self.failed.emit(powod_okna(exc))
        else:
            self.done.emit(res)
        finally:
            self.finished.emit()

    def _emit_progress(self, done, total, dst, status):
        self.progress.emit(done, total, dst, status)


class ManifestWorker(QObject):
    """Zapis manifestu wydania nad kompletem, który JUŻ leży w celu (AR-213) - drugie kliknięcie po
    świeżej sondzie, poza wątkiem GUI (cel bywa udziałem SMB). Woła `projection.repair_manifest`
    z zapisem: sonda kompletu, scalenie bez utraty i CAS liczą się od nowa, bo między sondą a
    kliknięciem drzewo i manifest mogły się zmienić. Własne połączenie po `db_path` (świadkowie
    drzewa czytają obecne kopie z bazy); tryb inline dostaje `con` wołającego. Linków nie zakłada,
    więc nie ma czego przerywać - `request_cancel` jest pusty; zamknięcie okna w biegu
    (`ProjectionDialog.done`) czeka na koniec zapisu i zamyka okno po sprzątnięciu wątku."""

    done = Signal(object)                   # projection.ManifestRepair
    failed = Signal(object)                 # powód wyjątku (`powod_okna`, AR-214)
    finished = Signal()

    def __init__(self, db_path, plan, root, copy, now, manifest, ts, con=None):
        super().__init__()
        self._db_path = db_path
        self._con = con
        self._plan = plan
        self._root = root
        self._copy = copy
        self._now = now
        self._manifest = manifest
        self._ts = ts

    def request_cancel(self):
        """Zapis jednego pliku - przerwanie na granicy pliku nie ma czego dzielić."""

    @Slot()
    def run(self):
        try:
            own = bool(self._db_path)
            con = db.connect(self._db_path) if own else self._con
            try:
                res = projection.repair_manifest(con, self._plan, self._root, copy=self._copy,
                                                 now=self._now, manifest=self._manifest, ts=self._ts,
                                                 do_write=True)
            finally:
                if own:
                    con.close()
        except Exception as exc:
            self.failed.emit(powod_okna(exc))
        else:
            self.done.emit(res)
        finally:
            self.finished.emit()


class _MiddleElidedLabel(ElidedLabel):
    """`ElidedLabel` elidowany ŚRODKIEM: ścieżka wyjścia WBPP niesie sens na obu końcach (dysk
    i karta z przodu, obiekt i `out` na końcu). Zawijana etykieta nie miała gdzie złamać ścieżki
    bez spacji i dyktowała minimum okna (do 1578 px). Pełna ścieżka w tooltipie i w przycisku
    „Kopiuj ścieżkę"; zaznaczanie myszą zdjęte, bo skopiowałoby wersję z wielokropkiem.

    `keep` pierwszych znaków (przedrostek „Wyjście WBPP: ") zostaje całe - środek CAŁEGO napisu
    przy wąskim miejscu ciął właśnie przedrostek; dopiero gdy nie mieści się nawet on, elizja
    obejmuje cały napis."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keep = 0

    def set_full_text(self, text, keep=0):
        self._keep = keep
        super().set_full_text(text)

    def _update_elide(self):
        fm = self.fontMetrics()
        szer = max(0, self.width() - 4)
        glowa, ogon = self._full[:self._keep], self._full[self._keep:]
        miejsce = szer - fm.horizontalAdvance(glowa)
        if fm.horizontalAdvance(self._full) <= szer or miejsce <= 0:
            self.setText(fm.elidedText(self._full, Qt.ElideMiddle, szer))
        else:
            self.setText(glowa + fm.elidedText(ogon, Qt.ElideMiddle, miejsce))


# ---------------------------------------------------------------- dialog

class ProjectionDialog(QDialog):
    """Wydanie perspektywy na stół: karty celów z pamięci + auto-DRY + „Utwórz N kopii/linków".
    `frame_ids` = klatki gridu (cel); `now_fn` = zegar (ts manifestu); `perspektywa` = etykieta do
    manifestu `_PROJEKCJA.json`; `off_thread=False` = OBA workery (DRY i apply) inline (seam
    testowy, wzorzec `_writeback_async` gridu - sygnały direct = synchronicznie).

    `object_id` ZAMIAST `frame_ids` = wydanie obiektu (docstring modułu): układ stały, combo
    „Zestaw" w miejscu układu, nagłówek z liczbami planu, „Otwórz w Eksploratorze" po wydaniu.
    Dokładnie jedno z dwojga - oba albo żadne to błąd wołającego (`ValueError`), nie tryb do
    zgadywania; nieznany obiekt też (nagłówek nie ma czego nazwać)."""

    def __init__(self, con, frame_ids=None, *, object_id=None, now_fn, perspektywa="perspektywa",
                 off_thread=True, parent=None):
        if (frame_ids is None) == (object_id is None):
            raise ValueError("ProjectionDialog: podaj frame_ids ALBO object_id (dokładnie jedno)")
        canon = None
        if object_id is not None:
            canon = queries.object_canon(con, object_id)
            if canon is None:
                raise ValueError(f"ProjectionDialog: nieznany obiekt {object_id!r}")
        super().__init__(parent)
        self.con = con
        self._db_path = queries.db_path_of(con)
        self._frame_ids = list(frame_ids) if frame_ids is not None else []
        self._object_id = object_id
        self._canon = canon
        self._released_root = None       # folder „Otwórz w Eksploratorze" - zmienia go wyłącznie `_arm_open`
        self._raport_teraz = ("", ())    # bieżący raport (`_show_report`) - tło zdania znikniętego folderu
        self._out_dir = None             # wyjście WBPP tego folderu (`_arm_open`), źródło schowka
        self._now = now_fn
        self._perspektywa = perspektywa
        self._off_thread = off_thread
        self._gen = 0                    # licznik generacji DRY (R2-2)
        self._dry_thread = None
        self._dry_worker = None
        self._dry_pending = False        # stale przyszło, worker jeszcze żył → re-trigger po sprzątnięciu
        self._plan = None                # plan z ZAAKCEPTOWANEGO (bieżąca generacja) DRY
        self._dry = None                 # payload zaakceptowanego DRY (copy/rozmiar/serial)
        self._cards = []                 # [{name, path, radio, note}]
        # Apply OFF-THREAD (P2/W1): worker+wątek per-wydanie; korzeń NIE jest kopiowany do pola —
        # karty są zamrożone w biegu, więc `_current_root()` pozostaje prawdą do końca wydania.
        self._apply_thread = None
        self._apply_worker = None
        self._apply_root = None          # korzeń bieżącego/ostatniego apply (obiekt: `object_root`)
        self._apply_now = None           # `now` ostatniego wydania - czas manifestu, którego nie zapisano
        # (korzeń, czas) wydania, które padło na kroku manifestu (AR-213): naprawa w tej sesji okna
        # stempluje manifest czasem tamtej próby, nie chwilą naprawy (żniwa liczą z niego datę wydania).
        self._ts_po_awarii = None
        self._zapis_manifestu = False    # świeża sonda zastała komplet z luką manifestu - „Zapisz manifest”
        # (głowa błędu, szczegół pod kursorem) wydania obiektu, które padło na kroku manifestu - stoi
        # nad raportem świeżej sondy uruchomionej po awarii, do zmiany parametru albo nowego biegu.
        self._po_awarii = None
        self._zamknij_po_zapisie = None  # wynik `done(r)` z Esc w biegu zapisu manifestu - zamknięcie po nim
        self._raport_biegu = None        # raport biegu z `_apply_begin` - Esc w zapisie manifestu dopisuje notkę
        self.summary = None              # zdanie o wydaniu dla statusbara wołającego (wiz P-C #4)
        self.setWindowTitle(i18n.t("proj.title" if object_id is None else "proj.obj.title"))
        self.setModal(True)
        self.resize(640, 520)
        self._build_ui()
        self._reload_targets()           # zaznaczenie domyślnego celu ODPALA auto-DRY (otwarcie dialogu)

    # ---- budowa ----
    def _build_ui(self):
        v = QVBoxLayout(self)
        self.combo_zestaw = None
        if self._object_id is None:
            v.addWidget(QLabel(i18n.t("proj.frames_in_perspective", n=len(self._frame_ids))))
        else:
            # Nagłówek mówi CO wyjeżdża, zanim user spojrzy w słupek DRY: do pierwszego planu sama
            # nazwa obiektu (plan czeka na cel), potem liczby planu - `_show_object_head`.
            self.head_label = QLabel(self._canon)
            _fh = self.head_label.font(); _fh.setBold(True); self.head_label.setFont(_fh)
            self.head_label.setWordWrap(True)
            v.addWidget(self.head_label)
            # Luki (bez flatu / bez darka) w roli ostrzeżenia, osobno od liczb tego, co JEST
            # (`object_gaps_text`); przy komplecie wiersz znika jak `pending`.
            self.gaps_label = QLabel("")
            self.gaps_label.setProperty("role", "warn")
            self.gaps_label.setVisible(False)
            v.addWidget(self.gaps_label)
            # `pending` OSOBNYM zdaniem, nigdy w „bez flatu": master jest, brakuje kliknięcia
            # w Dostawie - inna robota niż dokupienie klatek, więc inna linia i inny kolor.
            self.pending_label = QLabel("")
            self.pending_label.setProperty("role", "warn")
            self.pending_label.setVisible(False)
            v.addWidget(self.pending_label)

        v.addWidget(QLabel(i18n.t("proj.target_label")))
        self._targets_box = QVBoxLayout()
        v.addLayout(self._targets_box)
        self._btn_group = QButtonGroup(self)         # karty w osobnych wierszach → jawna ekskluzywność
        row_add = QHBoxLayout()
        self.btn_add = QPushButton(i18n.t("proj.add_target"))   # atrybut: blokowany na czas apply (W1)
        btn_add = self.btn_add
        btn_add.setAutoDefault(False)
        btn_add.clicked.connect(self._on_add_target)
        row_add.addWidget(btn_add)
        row_add.addStretch(1)
        v.addLayout(row_add)

        hint = QLabel(i18n.t("proj.segment_hint"))
        hint.setProperty("role", "secondary")        # trwała reguła celu (dyskoverowalna przed błędem, #2); tekst drugorzędny z motywu (F6 §7)
        v.addWidget(hint)

        row_l = QHBoxLayout()
        layout_label = QLabel(i18n.t("proj.layout_label"))
        row_l.addWidget(layout_label)
        self.combo_layout = QComboBox()
        self.combo_layout.addItem(i18n.t("proj.layout_by_object"), "po-obiektach")
        self.combo_layout.addItem(i18n.t("proj.layout_wbpp"), "wbpp-feed")
        self.combo_layout.currentIndexChanged.connect(self._on_param_changed)
        row_l.addWidget(self.combo_layout)
        if self._object_id is not None:
            # Układ wydania obiektu jest STAŁY (`wbpp-obiekt`): combo, które niczego nie zmienia,
            # obiecywałoby wybór. W jego miejscu jedyny realny parametr planu - zestaw. Pozycje
            # zestawów dochodzą z pierwszego planu (`_fill_zestawy`), bo dopiero on je zna.
            layout_label.setVisible(False)
            self.combo_layout.setVisible(False)
            row_l.addWidget(QLabel(i18n.t("proj.obj.zestaw_label")))
            self.combo_zestaw = QComboBox()
            # Szerokość za treścią przy KAŻDEJ zmianie listy, nie raz przy pierwszym pokazaniu
            # (domyślna polityka): pozycje dochodzą z pierwszego planu, często już po pokazaniu
            # okna, a szerokość „Wszystkie" ucinała „A140R_ASI2600MC/MD/MM" do „A140R_AS" - trzy
            # zestawy jednego obiektu nie do odróżnienia.
            self.combo_zestaw.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            self.combo_zestaw.addItem(i18n.t("proj.obj.zestaw_all"), None)
            self.combo_zestaw.currentIndexChanged.connect(self._on_param_changed)
            row_l.addWidget(self.combo_zestaw)
        row_l.addStretch(1)
        v.addLayout(row_l)

        self.chk_copy = QCheckBox(i18n.t("proj.force_copy"))
        self.chk_copy.toggled.connect(self._on_param_changed)
        v.addWidget(self.chk_copy)

        # QTextEdit, nie QPlainTextEdit: tylko on układa wcięcie wiszące (`QTextBlockFormat`
        # `leftMargin`/`textIndent`), którym `_show_report` trzyma zawinięte wiersze w słupku.
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.report.setAcceptRichText(False)
        self.report.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))   # monospace: słupki liczb (#7)
        self.report.setPlaceholderText(i18n.t("proj.placeholder"))
        v.addWidget(self.report, 1)

        # Wyjście WBPP wydania obiektu: pokazane razem z „Otwórz w Eksploratorze" (`_arm_open`),
        # bo dotyczy tego samego folderu i tych samych parametrów. Wydanie perspektywy go nie ma -
        # WBPP wskazuje się tylko folderem obiektu.
        self.out_box = None
        if self._object_id is not None:
            self.out_box = QWidget()
            ob = QVBoxLayout(self.out_box)
            ob.setContentsMargins(0, 0, 0, 0)
            row_out = QHBoxLayout()
            self.out_label = _MiddleElidedLabel()
            self.btn_out_copy = QPushButton(i18n.t("proj.obj.out_copy"))
            self.btn_out_copy.setAutoDefault(False)
            self.btn_out_copy.clicked.connect(self._copy_out_dir)
            row_out.addWidget(self.out_label, 1)
            row_out.addWidget(self.btn_out_copy)
            ob.addLayout(row_out)
            out_hint = QLabel(i18n.t("proj.obj.out_hint"))
            out_hint.setWordWrap(True)
            out_hint.setProperty("role", "secondary")
            ob.addWidget(out_hint)
            self.out_box.setVisible(False)
            v.addWidget(self.out_box)

        act = QHBoxLayout()
        # JEDEN pasek dwóch biegów (SPOT): DRY = nieokreślony (sonda nie zna liczby z góry, wiz W2),
        # apply = determinowany `done/total` z planu. Przełącza `_apply_begin`/`_apply_end`.
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        # Szerokość USTALONA raz: `setMaximumWidth` nie poszerza (sizeHint słupka to ~83 px, więc limit
        # 220 px był NO-OP i tekst „12345 / 15890" rozjeżdżał się na krawędzi wypełnienia — wiz #3);
        # ustawianie jej dopiero na czas biegu przesuwałoby notę o ~137 px przy każdym wejściu/wyjściu.
        self.busy.setMinimumWidth(220)
        self.busy.setTextVisible(False)
        self.busy.setVisible(False)
        act.addWidget(self.busy)
        # „12/131 · plik.fits" - postęp NAZWANY, nie sam słupek. Elizja w prawo z pełną notą
        # w tooltipie: nazwa pliku archiwum (do 79 znaków na kopii `pf4`) rozpychała okno z 701
        # do 1011 px i zostawiała je takie po biegu. Współczynnik 1 i ŻADNEGO osobnego stretchu
        # w rzędzie (wzorzec `harvest_dialog`): nota bierze całe wolne miejsce i spycha przyciski
        # do prawej krawędzi. Obok `addStretch(1)` dostawała tylko minimum 40 px - „1/3 · …".
        self.progress_note = ElidedLabel()
        self.progress_note.setProperty("role", "secondary")
        act.addWidget(self.progress_note, 1)
        self.btn_dry = QPushButton(i18n.t("proj.btn_refresh"))
        self.btn_dry.setAutoDefault(False)           # ręczny re-DRY (np. po zmianie na dysku poza apką)
        self.btn_dry.setEnabled(False)               # bez celu nie ma czego sondować (wiz K5)
        self.btn_dry.clicked.connect(self._on_manual_dry)
        self.btn_apply = QPushButton(i18n.t("proj.btn_create"))
        self.btn_apply.setEnabled(False)             # uzbraja WYŁĄCZNIE zakończony świeży DRY
        # Złota akcja wydania (F2: 1-klik) - waga i Enter przez `_set_gold` na końcu budowy.
        self.btn_apply.clicked.connect(self._on_apply)
        # NAZYWA skutek - „Anuluj" obok „Zamknij" czytało się jak bliźniak (wiz #9). Tryb obiektu
        # ma własny klucz: EN „Stop serving" to słownik stołu, nie wydania obiektu.
        self.btn_cancel = QPushButton(i18n.t("proj.btn_cancel_apply" if self._object_id is None
                                             else "proj.obj.btn_cancel_apply"))
        # wchodzi W MIEJSCE „Utwórz" na czas biegu (wzorzec szuflady gridu)
        self.btn_cancel.setAutoDefault(False)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._on_cancel_apply)
        # Wydanie obiektu kończy się w Eksploratorze (WBPP wskazuje się folderem), więc droga tam
        # pojawia się, gdy folder obiektu jest na dysku: po udanym wydaniu albo przy powrocie do
        # obiektu wydanego wcześniej (odbiór 0.19.0 WY6); przed pierwszym wydaniem - schowana.
        self.btn_open = QPushButton(i18n.t("proj.obj.open_explorer"))
        self.btn_open.setAutoDefault(False)
        self.btn_open.setVisible(False)
        self.btn_open.clicked.connect(self._open_in_explorer)
        btn_close = QPushButton(i18n.t("proj.btn_close"))
        btn_close.setAutoDefault(False)
        btn_close.clicked.connect(self.reject)
        act.addWidget(self.btn_dry)
        act.addWidget(self.btn_apply)
        act.addWidget(self.btn_cancel)
        act.addWidget(self.btn_open)
        act.addWidget(btn_close)
        v.addLayout(act)
        self._waga_akcji()

    def _waga_akcji(self):
        """JEDYNE miejsce, które wybiera przycisk złotej wagi - ze stanu okna, nie z wołającego:
        AKTYWNY `btn_apply` - oferta zapisu manifestu (Eksplorator otworzy folder i bez manifestu,
        ale żniwa bez niego wydania nie zobaczą) albo „Utwórz” z klatkami do dołożenia do folderu
        wydanego wcześniej (odbiór 0.19.0 WY6: Eksplorator stoi wtedy obok, ale następnym krokiem
        jest wydanie); inaczej uzbrojony folder (`_released_root`) → „Otwórz w Eksploratorze”;
        inaczej ŻADEN (AR-245) - złoto i Enter na wygaszonym „Przerwane błędem”,
        „Przerwano” albo „Utworzono ✓” wskazywały martwy przycisk. Dwóch pisarzy wagi (`_arm_open`
        i sonda nadpisująca ją po nim) zostawiało złoto obok uzbrojonego Eksploratora. Wołają ją
        drogi, które zmieniają stan przycisków: `_arm_open`, koniec sondy, wejście w bieg, koniec
        wydania i ogon błędu. W biegu zapisu (`btn_apply` schowany, `_apply_begin`) - żaden."""
        if self.btn_apply.isHidden():
            self._set_gold(None)
        elif self.btn_apply.isEnabled():
            self._set_gold(self.btn_apply)
        elif self._released_root is not None:
            self._set_gold(self.btn_open)
        else:
            self._set_gold(None)

    def _set_gold(self, btn):
        """Waga złotej akcji - bold, wysokość jak „Przyjmij nowe" Dostawy i domyślny Enter - na
        JEDNYM przycisku: `btn_apply` (wydanie) albo `btn_open` (folder gotowy pod WBPP). Wiz F3 #3:
        terminalna akcja ma się odróżniać od pomocniczych. Po wydaniu waga zostawała na wygaszonym
        „Utworzono ✓", a następny krok - Eksplorator - stał bez niej. Przycisk wybiera `_waga_akcji`;
        `None` - żaden (nie ma akcji, którą Enter mógłby wykonać)."""
        for b in (self.btn_apply, self.btn_open):
            gold = b is btn
            f = b.font(); f.setBold(gold); b.setFont(f)
            b.setMinimumHeight(_GOLD_HEIGHT if gold else 0)
            b.setDefault(gold)

    # ---- cele (QSettings) ----
    def _reload_targets(self, select_path=None):
        """Przebuduj karty-radio z QSettings; zaznacz `select_path` albo ostatnio użyty cel. Zaznaczenie
        (o ile jest) ODPALA auto-DRY - to zdarzenie dyskretne „otwarcie dialogu / nowy cel".
        Cel wskazuje się kluczem porównania, nie napisem: karta zapisana dawniej z `/` jest tym samym
        celem co `last_target` zapisany z `\\`.

        Okno trzyma kartę w postaci KANONICZNEJ (`_canon_path`), zapis w ustawieniach zostaje bez
        zmian: karta sprzed kanonizacji (`F:/ASTRO_WORK/_WBPP`) stała na liście obok `C:\\…\\_WBPP`
        dwoma stylami separatora, a złożony z niej folder obiektu i „Wyjście WBPP" mieszały oba
        w jednej ścieżce. Ten sam cel zapisany dawniej dwiema pisowniami to po kanonizacji dwa
        identyczne wiersze - zostaje jeden, z nazwą późniejszego zapisu (reguła `remember_target`).
        Nazwa karty folderu roboczego - w bieżącym języku (`card_name`)."""
        for c in self._cards:
            self._btn_group.removeButton(c["radio"])
            c["holder"].setParent(None)
        self._cards = []
        po_kluczu = {}
        for t in _load_targets():
            po_kluczu.pop(_target_key(t["path"]), None)          # późniejszy zapis na koniec listy
            po_kluczu[_target_key(t["path"])] = {**t, "path": _canon_path(t["path"])}
        targets = list(po_kluczu.values())
        chciany = select_path or _settings().value("projection/last_target", "")
        klucz = _target_key(chciany) if chciany else None
        pick = next((t["path"] for t in targets if _target_key(t["path"]) == klucz), None)
        if pick is None and targets:
            pick = targets[-1]["path"]               # brak pamięci → ostatnio dodany
        for t in targets:
            row = QHBoxLayout()
            radio = QRadioButton(f"{card_name(t['name'])}  -  {_elide_path(t['path'])}")
            radio.setToolTip(t["path"])              # pełna ścieżka pod kursorem (wiz K3)
            self._btn_group.addButton(radio)
            note = QLabel("")
            note.setProperty("role", "secondary")   # tekst drugorzędny z motywu (F6 §7)
            row.addWidget(radio)
            row.addWidget(note)
            row.addStretch(1)
            holder = QWidget()
            holder.setLayout(row)
            self._targets_box.addWidget(holder)
            radio.toggled.connect(self._on_target_toggled)
            self._cards.append({"name": t["name"], "path": t["path"], "radio": radio,
                                "note": note, "holder": holder})
        self.btn_dry.setEnabled(False)               # uzbroi je dopiero zaznaczony cel (wiz K5)
        if pick is not None:
            for c in self._cards:
                if c["path"] == pick:
                    c["radio"].setChecked(True)      # → toggled → _invalidate + auto-DRY
                    break

    def _current_root(self):
        for c in self._cards:
            if c["radio"].isChecked():
                return c["path"]
        return None

    def _on_add_target(self):
        path = QFileDialog.getExistingDirectory(self, i18n.t("proj.dlg.pick_target"))
        if not path:
            return
        name, ok = QInputDialog.getText(self, i18n.t("proj.dlg.name_title"),
                                        i18n.t("proj.dlg.name_label"),
                                        text=os.path.basename(path) or path)
        if not ok or not name.strip():
            return
        self._add_target_path(path, name.strip())

    def _add_target_path(self, path, name):
        """Dodanie celu z WALIDACJĄ segmentu wykluczonego (raz, przy dodawaniu — brief §3; guard
        w klindze zostaje drugą linią). Zwraca True gdy dodano (seam testowy — bez QFileDialog)."""
        try:
            projection._assert_excluded_segment(path)
        except ValueError as exc:                    # odmowa strażnika z kodem - w języku UI (AR-200)
            self._show_report(i18n.t("proj.add_failed", e=tekst_powodu(powod_wyjatku(exc))), "error")
            return False
        canon = remember_target(name, path)
        self._reload_targets(select_path=canon)      # nowa karta zaznaczona → auto-DRY
        return True

    # ---- stan / auto-DRY ----
    def _invalidate(self):
        """Zmiana parametru (cel/układ/kopia) unieważnia DRY: generacja ++ (R2-2), „Utwórz" gaśnie —
        uzbroi je wyłącznie ZAKOŃCZONY świeży DRY pod dokładnie bieżące parametry.

        Nagłówek trybu obiektu wraca do samej nazwy z tego samego powodu: liczby należą do planu,
        który właśnie przestał obowiązywać - po zmianie zestawu mówiłyby przez cały bieg sondy
        o poprzednim zestawie. „Otwórz w Eksploratorze" gaśnie razem z nimi (`_arm_open`)."""
        self._gen += 1
        self._plan = None
        self._dry = None
        self._zapis_manifestu = False
        self._po_awarii = None                       # głowa awarii mówiła o parametrach, które odeszły
        self.btn_apply.setEnabled(False)
        self.btn_apply.setText(i18n.t("proj.btn_create"))
        self._arm_open(None)
        if self._object_id is not None:
            self._show_object_head(None)

    def _on_target_toggled(self, checked):
        if not checked:
            return                                   # reaguj raz, na kartę ZAZNACZANĄ
        root = self._current_root()
        _settings().setValue("projection/last_target", _canon_path(root) if root else "")
        self._invalidate()
        self._trigger_dry()

    def _on_param_changed(self, *_):
        self._invalidate()
        self._trigger_dry()

    def _on_manual_dry(self):
        self._invalidate()                           # ręczny re-DRY = świeża generacja (stale w biegu odpadnie)
        self._trigger_dry()

    def _trigger_dry(self):
        """Start auto-DRY pod BIEŻĄCE parametry. Jeden worker naraz — gdy DRY w biegu, jego wynik
        przyjdzie ze STARĄ generacją, zostanie odrzucony i re-triggernie świeży (R2-2)."""
        root = self._current_root()
        if not root:
            self._show_report(i18n.t("proj.pick_or_add"))
            return
        if self._dry_worker is not None or self._apply_worker is not None:
            return                                   # w biegu apply DRY nie startuje (plan jest materializowany)
        self._dry_pending = False                    # flagę gasi UDANY start — odbity re-trigger nie przepada
        self._pokaz_sonde(i18n.t("proj.probing"))
        self.busy.setVisible(True)                   # bieg widoczny, nie tylko tekstem (wiz W2)
        self.btn_dry.setEnabled(False)               # jeden DRY naraz — „Odśwież" gaśnie na czas biegu
        worker = DryWorker(self._db_path, self._frame_ids, self.combo_layout.currentData(),
                           root, self.chk_copy.isChecked(), self._now(), self._gen,
                           con=None if self._db_path else self.con, object_id=self._object_id,
                           config_id=(self.combo_zestaw.currentData()
                                      if self.combo_zestaw is not None else None),
                           po_awarii=self._ts_po_awarii)
        worker.done.connect(self._on_dry_done)
        worker.failed.connect(self._on_dry_failed)
        self._dry_worker = worker
        if self._off_thread and self._db_path:
            self._dry_thread = QThread(self)
            worker.moveToThread(self._dry_thread)
            self._dry_thread.started.connect(worker.run)
            worker.finished.connect(self._dry_thread.quit)
            self._dry_thread.finished.connect(self._cleanup_dry_thread)
            self._dry_thread.start()
        else:
            try:
                worker.run()                         # inline: done/failed lecą direct = synchronicznie
            finally:
                self._dry_worker = None
            if self._dry_pending:
                self._trigger_dry()

    def _cleanup_dry_thread(self):
        # KOLEJNOŚĆ (deadlock GIL × ~QThread, native dump 2026-07-20): worker.deleteLater() doręcza
        # się w TEARDOWN wątku (Shiboken::Object::destroy → PyGILState_Ensure). Bez wait() poniższy
        # thread.deleteLater() mógłby doręczyć się na main, zanim wątek umrze: ~QThread czekałby na
        # wątek TRZYMAJĄC GIL (destrukcja wrappera), a wątek na GIL — AB-BA na stałe. wait() zwalnia
        # GIL, więc wątek dokańcza destrukcję workera i umiera; ~QThread trafia na martwy handle.
        self._dry_worker.deleteLater()
        self._dry_thread.wait()
        self._dry_thread.deleteLater()
        self._dry_worker = None
        self._dry_thread = None
        if self._dry_pending:                        # stale odrzucone w locie → świeży DRY pod bieżące parametry
            self._trigger_dry()                      # flagę gasi DOPIERO udany start (apply w biegu odbija _trigger_dry)

    @Slot(int, object)
    def _on_dry_done(self, gen, payload):
        if gen != self._gen:                         # stale (R2-2): odrzuć + re-trigger
            self._dry_pending = True
            return
        self.busy.setVisible(False)                  # świeży wynik przyjęty — bieg skończony (W2)
        self.btn_dry.setEnabled(True)
        self._plan = payload["plan"]
        self._dry = payload
        text, warn = self._format(payload["res"], payload["plan"], dry=True, payload=payload)
        self._pokaz_sonde(text, warn=warn)
        n = payload["res"].counts.get("would-link", 0)
        # Komplet w celu z luką manifestu (AR-213): „Utwórz” staje się „Zapisz manifest” - drugie
        # kliknięcie po świeżej sondzie, osobną operacją manifestową (`ManifestWorker`).
        naprawa = payload["manifest"]
        self._zapis_manifestu = naprawa is not None and naprawa.status == "would-write"
        if self._zapis_manifestu:
            self.btn_apply.setText(i18n.t("proj.obj.btn_write_manifest"))
            self.btn_apply.setEnabled(True)
        else:
            key = "proj.create_copies" if payload["copy"] else "proj.create_links"
            self.btn_apply.setText(i18n.t_plural(key, n))
            self.btn_apply.setEnabled(n > 0)         # zero do utworzenia → szczery disabled
        self._update_card_note(payload)
        if self._object_id is not None:
            self._fill_zestawy(payload["plan"].info)
            self._show_object_head(payload["plan"].info)
            # Folder obiektu zastany na dysku (odbiór 0.19.0 WY6) - wydany wcześniej, w komplecie
            # albo z nowymi klatkami do dołożenia - to folder, do którego droga ma być od razu, bez
            # „wydania" tylko po to, żeby przycisk się pojawił. Folderu nie ma - przycisk schowany,
            # jak przed pierwszym wydaniem (nie ma czego otwierać). Złotą wagę wybiera `_waga_akcji`.
            self._sync_open(payload["root"], istnieje=payload["root_exists"])
        self._waga_akcji()                           # przycisk właśnie się uzbroił albo zgasł (AR-245)

    @Slot(int, object)
    def _on_dry_failed(self, gen, msg):
        if gen != self._gen:
            self._dry_pending = True
            return
        self.busy.setVisible(False)
        self.btn_dry.setEnabled(True)
        self._plan = None
        self._dry = None
        self._zapis_manifestu = False                # oferta należała do sondy, która właśnie padła
        self.btn_apply.setEnabled(False)
        self._arm_open(None)                         # sonda bieżących parametrów padła - folderu nie znamy
        # Błąd systemu klasą w języku UI, surowy tekst systemu pod kursorem raportu (AR-184).
        self._pokaz_sonde(i18n.t("proj.dry_failed", msg=tekst_powodu(msg)), "error",
                          tip=wiersz_systemu(msg))
        if self._object_id is not None:
            self._show_object_head(None)             # liczby poprzedniego planu kłamałyby o bieżącym

    def _pokaz_sonde(self, text, outcome=None, warn=(), tip=""):
        """Raport sondy (bieg, wynik, porażka) - JEDNA droga dla `_trigger_dry`, `_on_dry_done`
        i `_on_dry_failed`. Po awarii kroku manifestu wydania obiektu (`_po_awarii`, AR-213) raport
        stoi pod głową tamtego błędu w roli błędu, a pod kursorem zostaje szczegół awarii (albo
        porażki sondy, gdy ta go ma) - werdykt świeżej sondy zamiast przepowiedni."""
        if self._po_awarii is None:
            self._show_report(text, outcome, warn=warn, tip=tip)
            return
        glowa, szczegol = self._po_awarii
        self._show_report(glowa + text, "error", warn=warn, tip=tip or szczegol)

    # ---- tryb obiektu: zestawy, nagłówek, Eksplorator ----
    def _fill_zestawy(self, info):
        """Pozycje combo „Zestaw" z PIERWSZEGO planu całego obiektu (raz - później plan bywa
        zawężony do jednego zestawu i nie zna reszty). Bez emisji: to budowa listy, nie wybór.

        Zestaw bez configu (`_UNSET`) nie dostaje pozycji: `plan_object(config_id=None)` znaczy
        „wszystkie", więc takiego zestawu nie da się wydać osobno - jego lighty jadą we
        „Wszystkich", a raport pokazuje je własnym wierszem."""
        if self.combo_zestaw.count() > 1 or info["config_id"] is not None:
            return
        self.combo_zestaw.blockSignals(True)
        for seg, z in info["zestawy"].items():
            if z["config_id"] is None:
                continue
            self.combo_zestaw.addItem(
                i18n.t_plural("proj.obj.zestaw_item", len(z["lights"]), seg=seg), z["config_id"])
        self.combo_zestaw.blockSignals(False)

    def _show_object_head(self, info):
        """Nagłówek wydania obiektu: liczby BIEŻĄCEGO planu albo sama nazwa (`info=None` - planu
        nie ma albo właśnie padł). `pending` ma własną linię i znika przy zerze. Przy wydaniu
        jednego zestawu nagłówek nazywa go (`_release_label`) - liczby bez nazwy nie mówią,
        o którym z kilku zestawów obiektu jest mowa, a combo bywa zwinięte."""
        if info is None:
            self.head_label.setText(self._canon)
            self.gaps_label.setVisible(False)
            self.pending_label.setVisible(False)
            return
        s = object_totals(info)
        self.head_label.setText(i18n.t(
            "proj.obj.head", canon=self._release_label(info),
            lights=i18n.t_plural("proj.obj.n_lights", s["lights"]),
            masters=i18n.t_plural("proj.obj.n_masters", s["masters"]),
            raw=i18n.t_plural("proj.obj.n_raw_flats", s["raw"])))
        luki = object_gaps_text(s)
        self.gaps_label.setText(luki)
        self.gaps_label.setVisible(bool(luki))
        self.pending_label.setText(i18n.t("proj.obj.pending_head", n=s["pending"]))
        self.pending_label.setVisible(s["pending"] > 0)

    def _arm_open(self, root):
        """Uzbrój „Otwórz w Eksploratorze" (i wiersz „Wyjście WBPP" wydania obiektu) na folderze
        `root` albo zgaś je (`None`) - JEDYNE miejsce, gdzie przycisk i jego folder zmieniają się razem.

        Przycisk żyje wyłącznie przy parametrach, dla których go uzbrojono: koniec sondy albo
        biegu zapisu, który zastał folder obiektu na dysku (`_sync_open`, odbiór 0.19.0 WY6 i Z8 -
        wcześniej tylko komplet albo udane wydanie, więc powrót do obiektu z nowymi klatkami
        i wydanie anulowane nie miały drogi do folderu). Każda zmiana parametru (`_invalidate`) i padnięta sonda go gaszą. Folder
        sprzed zmiany karty, zestawu czy trybu kopii to odpowiedź na pytanie, którego user już nie
        zadaje: po przejściu na kartę
        B z „do skopiowania: N" przycisk otwierałby folder z karty A. Samo wydanie niczego nie
        unieważnia, więc zaraz po nim przycisk stoi na właśnie wydanym folderze.

        Waga złotej akcji idzie za stanem (`_waga_akcji`): aktywne „Utwórz” (klatki do dołożenia,
        oferta zapisu manifestu) jest następnym krokiem, inaczej uzbrojony folder."""
        self._released_root = root
        self.btn_open.setVisible(root is not None)
        self._waga_akcji()
        # Wiersz „Wyjście WBPP" żyje i gaśnie razem z przyciskiem: ten sam folder, te same parametry.
        if self.out_box is not None:
            self._out_dir = os.path.join(root, projection.OUTPUT_DIR) if root else None
            wiersz = i18n.t("proj.obj.out_line", path=self._out_dir) if root else ""
            przedrostek = i18n.t("proj.obj.out_line", path="")
            self.out_label.set_full_text(
                wiersz, keep=len(przedrostek) if wiersz.startswith(przedrostek) else 0)
            self.out_box.setVisible(root is not None)

    def _copy_out_dir(self):
        """Ścieżka wyjścia WBPP do schowka - człowiek wkleja ją w Output Directory programu."""
        if self._out_dir:
            QApplication.clipboard().setText(self._out_dir)

    def _sync_open(self, root, istnieje=None):
        """Przycisk Eksploratora za STANEM DYSKU korzenia `root` wydania obiektu (bramka odbioru
        0.19.0, Z8) - JEDNA droga dla końca sondy i KAŻDEGO końca biegu zapisu (sukces, anulowanie,
        błąd, zapis manifestu): folder jest - uzbrojony, nie ma - schowany (`_arm_open`). Bieg zakłada
        korzeń i `out` przed pierwszym plikiem, więc wydanie anulowane albo przerwane zostawia folder
        z częściowym drzewem - a jego cofnięcie to skasowanie folderu w Eksploratorze, do którego
        przycisk właśnie prowadzi. `istnieje` - odczyt z wątku sondy (`root_exists`); bez niego
        jeden `isdir` tutaj, po biegu, który i tak dotykał dysku. Wydanie perspektywy przycisku
        nie ma - no-op."""
        if self._object_id is None:
            return
        if istnieje is None:
            istnieje = bool(root) and os.path.isdir(root)
        self._arm_open(root if istnieje else None)

    def _open_in_explorer(self):
        """Folder uzbrojony przez `_arm_open` - korzeń, który dostał `apply` albo sondował DRY,
        a nie przeliczony z bieżących kart. Stan przycisku to odczyt z końca sondy albo biegu, więc
        klik sprawdza folder od nowa (Z8): skasowany w międzyczasie - przycisk znika, a nad raportem
        staje zdanie, że folderu nie ma i że „Odśwież podgląd” policzy wydanie od nowa (Eksplorator
        z nieistniejącą ścieżką otwierałby pusty widok albo błąd systemu)."""
        root = self._released_root
        if not root:
            return
        if os.path.isdir(root):
            QDesktopServices.openUrl(QUrl.fromLocalFile(root))
            return
        tekst, warn = self._raport_teraz
        self._arm_open(None)
        self._show_report(i18n.t("proj.obj.folder_gone", path=root) + "\n\n" + tekst, "error",
                          warn=warn, tip=root)

    def _release_label(self, info):
        """Nazwa wydania: obiekt, a przy jednym zestawie także zestaw (`NGC6992 / RC8_ASI2600MM`).
        JEDNO źródło dla nagłówka okna i etykiety manifestu - człowiek czytający `_PROJEKCJA.json`
        i człowiek patrzący na okno mają zobaczyć to samo imię. Wartość domenowa - bez tłumaczenia."""
        if info["config_id"] is not None and info["zestawy"]:
            return f"{self._canon} / {next(iter(info['zestawy']))}"
        return self._canon

    def _object_manifest(self):
        """Manifest wydania obiektu: treść `projection.object_manifest` (jedno źródło z CLI) plus
        `etykieta` - nazwa wydania dla człowieka czytającego `_PROJEKCJA.json` (`_release_label`)."""
        manifest = projection.object_manifest(self._plan)
        manifest["etykieta"] = self._release_label(self._plan.info)
        return manifest

    def _update_card_note(self, payload):
        """Szczera nota trybu na ZAZNACZONEJ karcie celu (brief §3): skąd decyzja hardlink/kopia."""
        if self.chk_copy.isChecked():
            note = i18n.t("proj.note_forced_copy")
        elif payload["auto_copy"]:
            note = i18n.t("proj.note_other_vol")
        else:
            note = i18n.t("proj.note_same_vol")
        for c in self._cards:
            c["note"].setText(note if c["radio"].isChecked() else "")

    # ---- akcje: apply OFF-THREAD (P2/W1) ----
    def _on_apply(self):
        """Wydaj plan na dysk w wątku tła (bramka pierwszego MASOWEGO wydania z GUI): pasek
        `done/total` + „Anuluj" na granicy pliku. Parametry blokowane na czas biegu — inaczej klik
        w kartę/układ zawołałby `_invalidate` i wyzerował `self._plan`, który worker właśnie
        materializuje."""
        root = self._current_root()
        if self._plan is None or self._dry is None or not root or self._apply_worker is not None:
            return
        if self._object_id is not None:
            root = self._dry["root"]                 # `object_root` karty - ten sam, który sondował DRY
            manifest = self._object_manifest()
        else:
            manifest = {"perspektywa": self._perspektywa, "n_frames": len(self._frame_ids)}
        self._apply_root = root
        self._po_awarii = None                       # nowy bieg mówi własnym raportem
        if self._zapis_manifestu:
            self._zapisz_manifest(root, manifest)
            return
        self._apply_now = self._now()
        self._apply_begin(len(self._plan.items), root)
        worker = ApplyWorker(self._plan, root, self._dry["copy"], self._apply_now, manifest,
                             extra_sources=self._dry["extra_sources"])
        worker.progress.connect(self._on_apply_progress)
        worker.done.connect(self._on_apply_done)
        worker.aborted.connect(self._on_apply_aborted)
        worker.failed.connect(self._on_apply_failed)
        self._uruchom_bieg(worker, watek=self._off_thread)

    def _zapisz_manifest(self, root, manifest):
        """Drugie kliknięcie naprawy manifestu (AR-213): `ManifestWorker` zamiast `ApplyWorker` - zero
        linków i katalogów, sonda kompletu, scalenie bez utraty i CAS od nowa w rdzeniu. Czas
        manifestu: nieudanej próby wydania z tej sesji na tym samym korzeniu (`czas_proby_dla` - to samo
        źródło co oferta sondy), inaczej rozstrzyga rdzeń (`ts` starego manifestu, data z drzewa albo
        brak daty z `repaired_at`). Wątek wymaga ścieżki bazy - połączenie nie przechodzi między wątkami."""
        ts = czas_proby_dla(self._ts_po_awarii, root)
        self._apply_begin(0, root, raport=i18n.t("proj.obj.writing_manifest", root=root))
        worker = ManifestWorker(self._db_path, self._plan, root, self._dry["copy"], self._now(),
                                manifest, ts, con=None if self._db_path else self.con)
        worker.done.connect(self._on_manifest_done)
        worker.failed.connect(self._on_manifest_failed)
        self._uruchom_bieg(worker, watek=self._off_thread and bool(self._db_path))

    def _uruchom_bieg(self, worker, *, watek):
        """Bieg zapisu (`ApplyWorker`, `ManifestWorker`) w wątku tła albo inline (seam testowy,
        sygnały direct = synchronicznie) - jedno miejsce sprzątania (`_cleanup_apply_thread`)."""
        self._apply_worker = worker
        if watek:
            self._apply_thread = QThread(self)
            worker.moveToThread(self._apply_thread)
            self._apply_thread.started.connect(worker.run)
            worker.finished.connect(self._apply_thread.quit)
            self._apply_thread.finished.connect(self._cleanup_apply_thread)
            self._apply_thread.start()
        else:
            try:
                worker.run()                         # inline: sloty lecą direct = synchronicznie
            finally:
                self._apply_worker = None
            self._po_biegu()

    def _cleanup_apply_thread(self):
        # wait() przed thread.deleteLater() — ten sam deadlock GIL × ~QThread co w _cleanup_dry_thread
        # (komentarz tam); wait() zwalnia GIL, więc teardown wątku dokończy destrukcję workera.
        self._apply_worker.deleteLater()
        self._apply_thread.wait()
        self._apply_thread.deleteLater()
        self._apply_worker = None
        self._apply_thread = None
        self._po_biegu()

    def _po_biegu(self):
        """Ogon biegu zapisu PO sprzątnięciu workera (oba tryby `_uruchom_bieg`): sonda czekająca na
        koniec biegu (`_dry_pending` - świeża sonda po awarii kroku manifestu; w biegu DRY nie
        startuje) i zamknięcie okna odłożone z Esc w biegu zapisu manifestu (`_zamknij_po_zapisie`).
        Dopiero tu, nie w slocie wyniku: wątek jeszcze żyje, gdy wynik dolatuje, a okno zamknięte nad
        żywym QThread to twardy abort apki."""
        if self._zamknij_po_zapisie is not None:
            r, self._zamknij_po_zapisie = self._zamknij_po_zapisie, None
            self.done(r)
            return
        if self._dry_pending:
            self._trigger_dry()

    def _apply_begin(self, total, root, raport=None):
        """Wejście w tryb wydania: pasek determinowany (PROCENT — liczby niesie nota, żeby licznik nie
        stał w oknie dwa razy), „Anuluj" w miejscu „Utwórz", parametry zamrożone, RAPORT PRZEPISANY.

        Przepisanie raportu jest obowiązkowe: panel niósł tekst DRY („bez zmian na dysku, do
        zlinkowania: N") i przez CAŁY bieg twierdziłby to samo, mutując dysk — największa powierzchnia
        okna kłamałaby najgłośniej (wiz P1 #1). Przy okazji jest to jedyne miejsce, gdzie w biegu widać
        DOKĄD lecą pliki (karty celu są wygaszone, wiz #8).

        `raport` - zapis manifestu (AR-213): jeden plik, pasek nieokreślony bez noty postępu i bez
        „Przerwij” (przerywać nie ma czego), raport mówi, co się pisze."""
        self._apply_started = time.monotonic()       # baza ETA (zegar wydania ≠ `now_fn` manifestu)
        self._apply_seen = (0, total)                # ostatni postęp — raport błędu mówi, ile już powstało
        self.summary = None                          # pasek mówi o TYM biegu - koniec biegu stawia zdanie (AR-245)
        self._raport_biegu = raport
        self.busy.setRange(0, total if total > 0 else 0)
        self.busy.setValue(0)
        self.busy.setFormat("%p%")
        self.busy.setTextVisible(raport is None)
        self.busy.setVisible(True)
        self.progress_note.set_full_text(f"0/{total}" if raport is None else "")
        # Tryb obiektu mówi swoim słownikiem - „Wydaję na stół" to wydanie perspektywy gridu.
        self._show_report(raport if raport is not None else i18n.t(
            "proj.applying" if self._object_id is None else "proj.obj.applying", root=root))
        self.btn_apply.setVisible(False)
        self.btn_apply.setEnabled(False)             # WPROST, nie tylko przez ukrycie (default-button łapie Enter)
        self.btn_cancel.setVisible(raport is None)
        self.btn_cancel.setEnabled(raport is None)
        self._set_params_enabled(False)
        self._waga_akcji()                           # w biegu nie ma akcji ze złotem (AR-245)

    def _apply_end(self):
        """Wyjście z trybu wydania (sukces / abort / błąd / anulowanie): pasek wraca do postaci
        DRY-owej, parametry odmrożone."""
        self.busy.setVisible(False)
        self.busy.setTextVisible(False)
        self.busy.setFormat("")
        self.busy.setRange(0, 0)                     # z powrotem nieokreślony (tryb DRY)
        self.progress_note.set_full_text("")
        self.btn_cancel.setVisible(False)
        self.btn_apply.setVisible(True)
        self._set_params_enabled(True)

    def _zakoncz_bledem(self, glowa, powod, przycisk, res=None, pasek=None):
        """Ogon zakończenia biegu zapisu błędem - JEDEN dla pięciu dróg (AR-215, AR-213): krok
        wydania z błędem systemu albo zajętym manifestem (`_on_apply_done`, `res.error`), werdykt
        sondy pierwszego linku (`_on_apply_aborted`), wyjątek całej operacji wydania
        (`_on_apply_failed`), odmowa albo błąd zapisu manifestu (`_on_manifest_done`) i wyjątek
        zapisu manifestu (`_on_manifest_failed`). Wyjście z trybu wydania, raport w roli `error`:
        `glowa` (zdanie błędu z odstępem) nad raportem wyniku częściowego `res` (`_format` - liczby
        tego, co zaszło, i nietknięte; drogi bez wyniku - `None`), szczegół systemu `powod` pod
        kursorem; „Utwórz” wygaszone z etykietą `przycisk` (gotowy tekst - wołający podaje
        `i18n.t(<literał>)`, bramka kluczy katalogu widzi wyłącznie literały), bo dysk mógł się
        zmienić częściowo - kolejne wydanie idzie przez świeżą sondę. Oferta zapisu manifestu
        gaśnie razem z przyciskiem, więc złota waga idzie za stanem (`_waga_akcji`). Szczegół pod
        kursorem - `szczegol_powodu` (system, ścieżka manifestu uszkodzonego albo folder wydania, AR-234).
        Zdanie paska gospodarza (`summary` ze szczegółem, AR-245) stawia KAŻDA droga: domyślnie „wydanie
        przerwane błędem” w słowniku trybu (`_zdanie_przerwania`), `pasek` - zdanie drogi zapisu
        manifestu; bez niego pasek po zamknięciu okna milczał albo mówił o poprzednim biegu."""
        self._apply_end()
        text, warn = ("", ()) if res is None else self._format(res, self._plan, dry=False, partial=True)
        szczegol = szczegol_powodu(powod, root=self._apply_root)
        self._show_report(glowa + text, "error", warn=warn, tip=szczegol)
        self.btn_apply.setEnabled(False)
        self.btn_apply.setText(przycisk)
        self._zapis_manifestu = False
        self.summary = ZdanieZeSzczegolem(pasek if pasek is not None else self._zdanie_przerwania(powod),
                                          szczegol)
        self._sync_open(self._apply_root)            # częściowe drzewo leży - droga do folderu (Z8)
        self._waga_akcji()

    def _set_params_enabled(self, on):
        """Zamrożenie/odmrożenie parametrów DRY na czas apply (ochrona `self._plan` w biegu). Cały
        WIERSZ karty (`holder`), nie samo radio — inaczej nota trybu („ten sam wolumen → hardlink")
        zostaje w pełnej jasności i zamrożenie czyta się plamiasto (wiz #7)."""
        self.combo_layout.setEnabled(on)
        if self.combo_zestaw is not None:            # zestaw to parametr planu jak układ (R2-2)
            self.combo_zestaw.setEnabled(on)
        self.chk_copy.setEnabled(on)
        self.btn_add.setEnabled(on)
        self.btn_dry.setEnabled(on and self._current_root() is not None)
        for c in self._cards:
            c["holder"].setEnabled(on)

    def _on_cancel_apply(self):
        if self._apply_worker is not None:
            self._apply_worker.request_cancel()      # rdzeń sprawdza PRZED następnym plikiem
            self.btn_cancel.setEnabled(False)
            self.progress_note.set_full_text(i18n.t("proj.cancelling"))

    @Slot(int, int, str, str)
    def _on_apply_progress(self, done_n, total, dst, status):
        if self.busy.maximum() != total:
            self.busy.setRange(0, total)
        self.busy.setValue(done_n)
        self._apply_seen = (done_n, total)
        tail = dst.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        eta = eta_text(done_n, total, time.monotonic() - self._apply_started)
        self.progress_note.set_full_text(f"{done_n}/{total}{eta} · {tail}")

    @Slot(object)
    def _on_apply_done(self, res):
        """Wydanie skończone (pełne albo anulowane): raport z rdzenia, „Utwórz" gaśnie — dysk się
        zmienił, więc kolejne wydanie wymaga ŚWIEŻEGO DRY („Odśwież podgląd").

        Krok wydania przerwany błędem systemu (AR-197, `res.error`): zdanie błędu w języku UI nad
        raportem częściowym (liczby tego, co zaszło, i nietknięte), szczegół systemu pod kursorem,
        „Przerwane błędem” - jak awaria całej operacji (`_on_apply_failed`), ale z liczbami.
        Niezapisany manifest (`proj_manifest_failed`, `proj_manifest_busy` - cudzy plik roboczy):
        pliki leżą, więc zdanie powodu mówi, czego brakuje i po co; czas tej próby czeka na naprawę
        (`_ts_po_awarii`, AR-213). Wydanie obiektu uruchamia wtedy samo świeżą sondę (po sprzątnięciu
        biegu - `_po_biegu`), a pod głową błędu staje jej werdykt: oferta „Zapisz manifest” albo
        odmowa z radą (`_pokaz_sonde`). Głowa niczego nie obiecuje - naprawa bywa odmówiona. Stary
        manifest uszkodzony albo innego wydania (`proj_manifest_damaged`, `proj_manifest_foreign`,
        AR-234) to też krok manifestu: pliki leżą, stary plik nietknięty. Zdanie paska (`summary` ze
        szczegółem, AR-245) mówi o przerwaniu także po zamknięciu okna."""
        if res.error is not None:
            krok_manifestu = res.error.code in ("proj_manifest_failed", "proj_manifest_busy",
                                                "proj_manifest_damaged", "proj_manifest_foreign")
            if krok_manifestu:
                # Pliki leżą, manifestu nie ma: naprawa w tej sesji okna (świeża sonda → „Zapisz
                # manifest”) stempluje manifest czasem TEJ próby (AR-213).
                self._ts_po_awarii = (self._apply_root, self._apply_now)
                glowa = i18n.t("proj.manifest_error_head", msg=zdanie_odmowy(res.error))
            else:
                glowa = i18n.t("proj.apply_error", msg=tekst_powodu(res.error), made="") + "\n\n"
            self._zakoncz_bledem(glowa, res.error, i18n.t("proj.btn_error"), res)
            if krok_manifestu and self._object_id is not None:
                self._po_awarii = (glowa, szczegol_powodu(res.error, root=self._apply_root))
                self._dry_pending = True             # sonda rusza po sprzątnięciu biegu (`_po_biegu`)
            return
        if self._ts_po_awarii is not None and _target_key(self._ts_po_awarii[0]) == _target_key(
                self._apply_root):
            self._ts_po_awarii = None                # manifest tego korzenia zapisany tym wydaniem
        self._apply_end()
        # Cel był ZAMROŻONY na czas biegu, więc `_current_root()` to dokładnie ten, na który wydano.
        _settings().setValue("projection/last_target", _canon_path(self._current_root()))   # ostatnio UŻYTY = domyślny
        text, warn = self._format(res, self._plan, dry=False, partial=res.cancelled)
        self._show_report(text, report_outcome(res, partial=res.cancelled), warn=warn)
        # ŚLAD PO ZAMKNIĘCIU (wizytacja P-C #4): po `exec()` okno główne nie niosło ani słowa
        # o wydaniu — jedynym trwałym zapisem był `_PROJEKCJA.json` w celu, czyli POZA aplikacją.
        # Zdanie składamy TU, gdzie liczby są świeże; `grid` je tylko przekazuje na statusbar.
        # Liczba plików odmieniona frazą („skopiowano 1 plik"), nie „1 skopiowano".
        word = i18n.t("proj.word_copy_done" if res.copy else "proj.word_link_done")
        files = i18n.t_plural("proj.files_copied" if res.copy else "proj.files_linked",
                              res.counts.get("linked", 0))
        if self._object_id is None:
            # Anulowane wydanie na stół nie mówi „Wydano” (AR-245) - jak tryb obiektu niżej.
            self.summary = (i18n.t("proj.status_cancelled", word=word, n=res.counts.get("linked", 0),
                                   total=len(self._plan.items), root=self._current_root())
                            if res.cancelled else
                            i18n.t("proj.status_summary", files=files, root=self._current_root()))
        elif res.cancelled:
            # Statusbar zostaje po zamknięciu okna jako JEDYNY ślad - „Wydano" nad połową drzewa
            # mówiłoby, że folder jest gotowy pod WBPP, a jest w nim tylko część planu.
            self.summary = i18n.t("proj.obj.status_cancelled", canon=self._canon, word=word,
                                  n=res.counts.get("linked", 0), total=len(self._plan.items),
                                  root=self._apply_root)
        else:
            self.summary = i18n.t("proj.obj.status_summary", canon=self._canon, files=files,
                                  root=self._apply_root)
        # Sukces i anulowanie jedną drogą (Z8): po anulowaniu częściowe drzewo leży w folderze,
        # a raport mówi „Przerwano” i ile nietkniętych - przycisk prowadzi do folderu, w którym
        # wydanie się wznawia albo cofa (skasowanie folderu).
        self._sync_open(self._apply_root)
        self.btn_apply.setEnabled(False)
        # nie głosi akcji, która zaszła (wiz K2) — także wtedy, gdy nie zaszła ŻADNA (#1)
        self.btn_apply.setText(i18n.t("proj.btn_cancelled") if res.cancelled else (
            i18n.t("proj.btn_created_ok") if res.counts.get("linked", 0)
            else i18n.t("proj.btn_nothing_new")))
        self._waga_akcji()                           # wygaszony „Utworzono”/„Przerwano” bez złota (AR-245)

    @Slot(object, object)
    def _on_apply_aborted(self, powod, partial):
        """Sonda pierwszego linku padła (SMB oddał kopię zamiast hardlinka) - werdykt o wolumenie.
        Powód z kodem (`proj_first_link`, AR-200) mówi w języku UI. „Nie utworzono” - przycisk NIE
        obiecuje akcji, której raport zabrania (wiz #4)."""
        self._zakoncz_bledem(i18n.t("proj.abort_prefix", msg=tekst_powodu(powod)), powod,
                             i18n.t("proj.btn_not_created"), partial)

    def _zdanie_przerwania(self, powod):
        """Zdanie paska gospodarza o wydaniu przerwanym (AR-245) - krok z błędem, werdykt sondy pierwszego
        linku, wyjątek całej operacji: po zamknięciu okna pasek mówi, że wydania nie skończono i gdzie."""
        if self._object_id is None:
            return i18n.t("proj.status_failed", msg=tekst_powodu(powod), root=self._apply_root)
        return i18n.t("proj.obj.status_failed", canon=self._canon, msg=tekst_powodu(powod),
                      root=self._apply_root)

    @Slot(object)
    def _on_apply_failed(self, msg):
        # Ile już powstało PRZED błędem — bez tego user widzi samą awarię i nie wie, że w celu leży
        # częściowe drzewo (ścieżka anulowania to mówi, ścieżka błędu milczała - wiz #2). Błąd
        # systemu klasą w języku UI, surowy tekst systemu pod kursorem raportu (AR-184).
        done_n, total = self._apply_seen
        made = i18n.t("proj.made_before_error", done=done_n, total=total) if done_n else ""
        self._zakoncz_bledem(i18n.t("proj.apply_error", msg=tekst_powodu(msg), made=made), msg,
                             i18n.t("proj.btn_error"))

    @Slot(object)
    def _on_manifest_done(self, res):
        """Wynik zapisu manifestu (AR-213, `ManifestWorker`). Zapisany - raport z liczbą id
        wcześniejszych wydań zachowanych i zapomnianych i wierszami faktów treści (`manifest_fact_lines`:
        klatki bez kopii, id bez dowodu, data z drzewa albo jej brak - rolą ostrzeżenia), zdanie na
        pasek, „Manifest zapisany ✓”, Eksplorator ze złotą wagą (folder jest gotowy i dla żniw);
        manifest opisał komplet w międzyczasie (`current`) - zdanie bez zapisu i „Bez zmian ✓”.
        Odmowa albo błąd - ogon zakończenia błędem: zdanie odmowy mówi radę (skasuj `.part`, sprawdź
        manifest, odśwież podgląd) i idzie zdaniem na pasek ze szczegółem (AR-245). Zamknięcie odłożone
        z Esc w biegu wykonuje `_po_biegu` na KAŻDEJ drodze końca zapisu - odmowa ma dokąd trafić
        (pasek gospodarza), więc okno nie zostaje wbrew Esc."""
        if res.status in ("refused", "error"):
            self._zakoncz_bledem(i18n.t("proj.obj.manifest_error", msg=zdanie_odmowy(res.powod)),
                                 res.powod, i18n.t("proj.btn_error"),
                                 pasek=i18n.t("proj.obj.status_manifest_failed", canon=self._canon,
                                              msg=tekst_powodu(res.powod), root=self._apply_root))
            return
        self._apply_end()
        self._zapis_manifestu = False
        if self._ts_po_awarii is not None and _target_key(self._ts_po_awarii[0]) == _target_key(
                self._apply_root):
            self._ts_po_awarii = None
        if res.status == "written":
            linie = [i18n.t("proj.obj.manifest_written")]
            if res.kept or res.dropped:
                linie.append(i18n.t("proj.obj.manifest_kept", kept=res.kept, dropped=res.dropped))
            warn = manifest_fact_lines(res, foldery=False)
            self._show_report("\n".join(linie + warn), "ok", warn=warn)
            self.summary = i18n.t("proj.obj.status_manifest", canon=self._canon, root=self._apply_root)
            przycisk = i18n.t("proj.obj.btn_manifest_written")
        elif res.status == "current":
            self._show_report(i18n.t("proj.obj.manifest_current"), "ok")
            self.summary = i18n.t("proj.obj.status_manifest_current", canon=self._canon, root=self._apply_root)
            przycisk = i18n.t("proj.btn_nothing_new")
        else:                                        # zapis bez `should_cancel` - innych wyników nie ma (EXPECT)
            raise AssertionError(f"nieoczekiwany wynik zapisu manifestu: {res.status!r}")
        self._sync_open(self._apply_root)
        self.btn_apply.setEnabled(False)
        self.btn_apply.setText(przycisk)

    @Slot(object)
    def _on_manifest_failed(self, powod):
        """Wyjątek zapisu manifestu (`powod_okna`) - ten sam ogon co odmowa: zdanie na pasek ze
        szczegółem, a zamknięcie odłożone z Esc wykonuje `_po_biegu` (AR-245)."""
        self._zakoncz_bledem(i18n.t("proj.obj.manifest_error", msg=zdanie_odmowy(powod)), powod,
                             i18n.t("proj.btn_error"),
                             pasek=i18n.t("proj.obj.status_manifest_failed", canon=self._canon,
                                          msg=tekst_powodu(powod), root=self._apply_root))

    def _show_report(self, text, outcome=None, warn=(), tip=""):
        """JEDYNA droga tekstu do panelu raportu. `outcome` (None | 'ok' | 'warn' | 'error') koloruje
        PIERWSZY BLOK — wynik widać, zanim user przeczyta słupek liczb (wizytacja P2: `pipeline`
        koloruje błąd, a ten dialog był jednolicie szary). `warn` - wiersze (pełny tekst bloku) luk
        z `_format`, malowane kolorem roli `warn`: liczby braków miały kolor liczb tego, co jest.
        `tip` - podpowiedź raportu (szczegół systemu awarii, AR-184); każdy raport stawia ją od nowa,
        więc szczegół jednej awarii nie zostaje pod następnym raportem.

        Tekst zostaje NIETKNIĘTY: `toPlainText()` oddaje dokładnie argument, bo kolor to warstwa
        formatu, nie treść — kontrakt „raport zaczyna się od «Przerwano»" (wiz #6) i wszystkie
        asercje na tekście trzymają się bez zmian. `outcome=None` (podgląd, sonda, plan) zostaje
        w kolorze tekstu - neutralność też jest komunikatem.

        Wcięcie WISZĄCE każdego bloku (`leftMargin` + ujemny `textIndent`, też warstwa formatu):
        pierwsza linia stoi, gdzie stała, a zawinięta kontynuacja zaczyna się `_REPORT_HANG` znaków
        głębiej niż własne wcięcie wiersza - zawinięcie nie łamie słupka monospace."""
        self._raport_teraz = (text, tuple(warn))     # raport pod zdaniem znikniętego folderu (Z8)
        self.report.setPlainText(text)
        self.report.setToolTip(tip)
        znak = QFontMetricsF(self.report.font()).horizontalAdvance(" ")
        ostrzezenia = set(warn)
        blok = self.report.document().firstBlock()
        while blok.isValid():
            wiersz = blok.text()
            wisi = (len(wiersz) - len(wiersz.lstrip(" ")) + _REPORT_HANG) * znak
            fmt_bloku = blok.blockFormat()
            fmt_bloku.setLeftMargin(wisi)
            fmt_bloku.setTextIndent(-wisi)
            cur = QTextCursor(blok)
            cur.setBlockFormat(fmt_bloku)
            if wiersz in ostrzezenia:
                cur.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                fmt_luki = QTextCharFormat()
                fmt_luki.setForeground(_COLORS["warn"])
                cur.mergeCharFormat(fmt_luki)
            blok = blok.next()
        if outcome is None:
            return
        cur = QTextCursor(self.report.document().firstBlock())
        cur.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setForeground(_COLORS[outcome])
        fmt.setFontWeight(QFont.Bold)
        cur.mergeCharFormat(fmt)

    def _format(self, res, plan, *, dry, partial=False, payload=None):
        """Raport → `(tekst, wiersze_luk)`; drugie idzie do `_show_report(warn=…)`. Układ nazwą
        z katalogu (`layout_text`), nie tokenem dysku."""
        c = res.counts
        word_todo = i18n.t("proj.word_copy_todo" if res.copy else "proj.word_link_todo")
        word_done = i18n.t("proj.word_copy_done" if res.copy else "proj.word_link_done")
        mode = i18n.t("proj.mode_copies" if res.copy else "proj.mode_links")
        layout = layout_text(res.layout)
        lines, warn = [], []
        if dry:
            if dry_complete(res):
                lines.append(i18n.t("proj.dry_head_complete", layout=layout, mode=mode))
            else:
                lines.append(i18n.t("proj.dry_head", layout=layout, mode=mode))
            lines.append(i18n.t("proj.dry_counts", todo=word_todo, would=c.get("would-link", 0),
                                exists=c.get("exists", 0), conflict=c.get("conflict", 0),
                                skipped=c.get("skipped", 0)))
            if payload is not None and res.copy:
                size_line = i18n.t("proj.dry_size", size=format_bytes(payload["size_total"]))
                if payload["size_missing"]:
                    m = payload["size_missing"]
                    size_line += f"  {i18n.t_plural('proj.files_no_size', m)}"
                lines.append(size_line)
            naprawa = payload["manifest"] if payload is not None else None
            if naprawa is not None and naprawa.status != "current":
                # Komplet z luką manifestu (AR-213) - rolą ostrzeżenia, bo żniwa wydania nie widzą:
                # co zapis dopisze albo dlaczego zapisu nie będzie.
                linie = (manifest_offer_lines(naprawa) if naprawa.status == "would-write"
                         else [i18n.t("proj.obj.manifest_refused", msg=zdanie_odmowy(naprawa.powod))])
                lines.extend(linie)
                warn.extend(linie)
        else:
            # abort → nie „Utworzono" (wizytator #6); anulowanie nazywa się WPROST (W1) — user ma
            # wiedzieć, że reszta planu jest nietknięta, a nie że wydanie zawiodło. Rozbiór stanów
            # (w tym „nic nowego" przy powtórce) ma JEDNEGO właściciela: `report_head_key`.
            head = i18n.t(report_head_key(res, partial=partial))
            lines.append(i18n.t("proj.done_head", head=head, layout=layout, mode=mode))
            lines.append(i18n.t("proj.done_counts", done=word_done, linked=c.get("linked", 0),
                                exists=c.get("exists", 0), conflict=c.get("conflict", 0),
                                vbad=c.get("verify_bad", 0), errors=c.get("error", 0),
                                skipped=c.get("skipped", 0)))
            if c.get("unverified"):
                # Link utworzony, sonda nie przeczytała plików (AR-197) - leży na dysku, więc nie
                # znika z liczb, ale nie jest „zlinkowany” z dowodem tożsamości.
                lines.append(i18n.t("proj.unverified", n=c["unverified"]))
            if res.dropped:
                # Scalenie manifestu bez utraty (AR-213): id wcześniejszych wydań, których plików
                # dowodnie nie ma w drzewie - manifest mówi o drzewie, nie o historii.
                lines.append(i18n.t("proj.manifest_dropped", n=res.dropped))
            if res.cancelled or res.error is not None:
                # Ile planu ZOSTAŁO: drzewo kategorii niżej rysuje się z PEŁNEGO planu, więc bez tej
                # linii raport po anulowaniu albo przerwaniu (abort sondy, krok z błędem systemu -
                # AR-197) wygląda na kompletny. PO liczbach tego, co się stało - pierwsza liczba pod
                # nagłówkiem ma mówić o skutku, nie o jego braku (wiz #11).
                # Przerwanie bez nietkniętych (manifest po komplecie plików) nie dostaje wiersza
                # „nietknięte: 0 … wznów”: wznawiać nie ma czego.
                touched = sum(c.get(k, 0) for k in ("linked", "exists", "conflict", "error",
                                                    "verify_bad", "unverified"))
                nietkniete = max(len(plan.items) - touched, 0)
                if res.cancelled or nietkniete:
                    lines.append(i18n.t("proj.untouched", n=nietkniete))
        if plan.info is not None:                          # wydanie obiektu: zestawy i powody luk
            for wiersz, rola in object_report_lines(plan.info):
                lines.append(wiersz)
                if rola == "warn":
                    warn.append(wiersz)
        if res.drift:
            # Rozjazd manifestu PRZED drzewem planu: stare drzewo NIE daje `conflict` (leży pod inną
            # ścieżką), więc liczniki wyżej wyglądają czysto — bez tej linii raport milczy o tym,
            # że korzeń dostanie DRUGIE drzewo obok starego (te same i-węzły, WBPP liczy dwa razy).
            lines.append(drift_text(res.drift, res.layout))
        if plan.multi_present:
            lines.append(i18n.t("proj.multi_present", n=plan.multi_present))
        folders: dict = {}
        for it in plan.items:
            key = tree_folder_text(it.segments)
            folders[key] = folders.get(key, 0) + 1
        nf = len(folders)
        # „drzewo PLANU": po anulowaniu/abortcie sekcja niżej dalej opisuje pełen plan, nie stan
        # dysku — bez tego słowa czyta się jak listing celu (wiz #6).
        lines.append(i18n.t("proj.plan_tree", tree=i18n.t_plural("proj.plan_tree_folders", nf)))
        for key, n in sorted(folders.items(), key=lambda kv: (-kv[1], kv[0]))[:_TREE_CAP]:
            lines.append(f"    {key}: {n}")
        if len(folders) > _TREE_CAP:
            lines.append(i18n.t("proj.more_folders", n=len(folders) - _TREE_CAP))
        return "\n".join(lines), warn

    # ---- sprzątanie wątków przy zamknięciu ----
    def done(self, r):
        """Zamknięcie dialogu (Zamknij/Esc/X) nie może zostawić żywego QThread pod kasowanym rodzicem
        („QThread: Destroyed while thread is still running" = twardy abort apki).

        WYDANIE W BIEGU: zamknięcie = ŻĄDANIE ANULOWANIA, okno ZOSTAJE. Czekanie z timeoutem byłoby
        zakładem o czas jednego pliku — kopia 200 MB przez SMB przekracza każdy sensowny limit, a po
        jego wygaśnięciu wątek-sierota dalej tworzyłby pliki pod skasowanym rodzicem. Okno zostaje
        też po to, by raport „Przerwano" (ile powstało, ile nietkniętych) miał dokąd trafić — bez
        niego user zostaje z częściowym drzewem i zerową wiedzą. Drugie Esc, już po biegu, zamyka.

        ZAPIS MANIFESTU W BIEGU (AR-213): jeden plik, nieprzerywalny - „Anulowanie… (po bieżącym
        pliku)” kłamałoby, bo manifest i tak powstaje. Notka, że okno zamknie się samo, staje wierszem
        PANELU RAPORTU pod raportem biegu (AR-262) - nota postępu obok paska ma ~145 px i elizja zjadała
        jej sens (zmierzone natywnie: 146 px na 316 px treści); panel zawija. Raport składa się od raportu
        biegu, więc drugie Esc nie dopisuje notki drugi raz. Zamknięcie czeka na sprzątnięcie wątku
        (`_po_biegu`) na KAŻDEJ drodze końca zapisu (AR-245): odmowa albo błąd zapisu idą zdaniem na
        pasek gospodarza ze szczegółem (`summary`), więc Esc nie zostawia okna otwartego wbrew człowiekowi.

        SONDA DRY: krótka i NICZEGO nie tworzy → cancel + wait, jak dotąd; diagnoza manifestu słucha
        tego samego anulowania (`DryWorker`)."""
        if isinstance(self._apply_worker, ManifestWorker):
            self._zamknij_po_zapisie = r
            self._show_report(self._raport_biegu + "\n\n" + i18n.t("proj.obj.closing_after_manifest"))
            return
        if self._apply_worker is not None:
            self._on_cancel_apply()
            return
        if self._dry_worker is not None:
            self._dry_worker.request_cancel()
        if self._dry_thread is not None:
            self._dry_thread.quit()
            self._dry_thread.wait(10_000)
        super().done(r)


# ---------------------------------------------------------------- okno teczek (wybór obiektu)

# Stan teczki → rola koloru z motywu (`_COLORS`, SPOT z nagłówkiem raportu) i zdanie pod kursorem.
# Kropka sama nie wystarcza: kolor bez słowa nie mówi nic czytelnikowi, który go nie rozróżnia.
_STATE_ROLES = {"green": "ok", "amber": "warn", "red": "error"}
_STATE_TIPS = {"green": "proj.pick.state.green", "amber": "proj.pick.state.amber",
               "red": "proj.pick.state.red"}
_PICK_HEADERS = ("", "proj.pick.col.object", "proj.pick.col.hours", "proj.pick.col.lights",
                 "proj.pick.col.nights", "proj.pick.col.sets", "proj.pick.col.flat",
                 "proj.pick.col.dark", "proj.pick.col.last_night")
_PICK_COL_OBJECT = 1


class _KropkaStanu(QStyledItemDelegate):
    """Kolumna kropki stanu: w zaznaczonym wierszu Qt maluje tekst kolorem `HighlightedText`
    (biel), więc kropka gubiła stan teczki dokładnie wtedy, gdy człowiek ją wskazał. Kolor roli
    z komórki (`ForegroundRole`) zostaje też pod zaznaczeniem; podpowiedź mówi stan słowem."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        kolor = index.data(Qt.ForegroundRole)
        if kolor is not None:
            option.palette.setColor(QPalette.HighlightedText,
                                    kolor.color() if isinstance(kolor, QBrush) else QColor(kolor))


class ObjectPickDialog(QDialog):
    """Okno teczek „Wydaj obiekt…": wiersz na obiekt z aktywnymi lightami (`queries.release_readiness`),
    godzinami malejąco, z kropką stanu i procentami kalibracji. Dwuklik albo „Dalej" (Enter) wybiera
    obiekt - wołający otwiera z nim `ProjectionDialog` w trybie obiektu. Wynik: `self.object_id`.

    Read-model liczy się INLINE, bez wątku tła: zmierzone na kopii żywej `pf4` (73 obiekty,
    2026-10-09) ~120 ms z surowymi flatami włącznie - poniżej progu, od którego okno potrzebowałoby
    stanu „Liczę gotowość…". Gdy archiwum urośnie ponad ~300 ms, wzorzec `DryWorker` czeka obok.

    `preselect` (id obiektu) zaznacza teczkę na starcie - wołający podaje ją, gdy zbiór gridu
    niesie lighty dokładnie jednego obiektu (`queries.sole_light_object`); bez niego „Dalej" jest
    szczerze wygaszony, a nie uzbrojony na przypadkowym pierwszym wierszu. Pole „Szukaj" zawęża
    i, gdy zaznaczenie wypadnie z widoku, zaznacza pierwszą pasującą teczkę - wpisanie nazwy
    i Enter to cała droga dla kogoś, kto wie, czego szuka.

    Szukanie to ta sama reguła co szukajka facetu Obiekt (`facet_model.search_hit` z aliasami
    `queries.object_alias_index`), nie własny klucz okna: „sh2 131" trafia `Sh2-131`, „m106"
    `NGC4258`, a nazwa potoczna z aliasu ręki - swój obiekt. Dwie reguły szukania tego samego
    archiwum dawały w dwóch oknach dwie różne odpowiedzi na tę samą frazę. Strzałki w polu
    przesuwają zaznaczenie po widocznych teczkach, więc teczka poza kadrem nie kosztuje
    przeniesienia ręki na mysz; fraza bez trafień ma zdanie, nie gołą tabelę."""

    def __init__(self, con, *, preselect=None, parent=None):
        super().__init__(parent)
        self.object_id = None
        self._rows = queries.release_readiness(con)
        self._aliases = queries.object_alias_index(con)
        self.setWindowTitle(i18n.t("proj.pick.title"))
        self.setModal(True)
        self.resize(860, 560)
        self._build_ui()
        self._fill()
        if preselect is not None:
            for i, r in enumerate(self._rows):
                if r["object_id"] == preselect:
                    self.table.selectRow(i)
                    self.table.scrollToItem(self.table.item(i, _PICK_COL_OBJECT))
                    break
        self._sync_next()

    def _build_ui(self):
        v = QVBoxLayout(self)
        hint = QLabel(i18n.t("proj.pick.hint"))
        hint.setProperty("role", "secondary")
        v.addWidget(hint)
        row_s = QHBoxLayout()
        row_s.addWidget(QLabel(i18n.t("proj.pick.search_label")))
        self.search = QLineEdit()
        self.search.setPlaceholderText(i18n.t("proj.pick.search_placeholder"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.search.installEventFilter(self)          # Up/Down → zaznaczenie tabeli (`eventFilter`)
        row_s.addWidget(self.search, 1)
        v.addLayout(row_s)

        self.table = QTableWidget(0, len(_PICK_HEADERS))
        self.table.setHorizontalHeaderLabels([i18n.t(k) if k else "" for k in _PICK_HEADERS])
        self.table.horizontalHeaderItem(0).setToolTip(i18n.t("proj.pick.col.state_tip"))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setItemDelegateForColumn(0, _KropkaStanu(self.table))
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(_PICK_COL_OBJECT, QHeaderView.Stretch)
        # Dwuklik, NIE `activated`: Enter na tabeli i tak dochodzi do domyślnego „Dalej" (widok
        # emituje `activated` i przepuszcza klawisz), więc podpięcie obu wybierałoby dwa razy.
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.table.itemSelectionChanged.connect(self._sync_next)
        v.addWidget(self.table, 1)
        self.empty_label = QLabel(i18n.t("proj.pick.empty"))
        self.empty_label.setProperty("role", "secondary")
        self.empty_label.setVisible(not self._rows)
        v.addWidget(self.empty_label)

        act = QHBoxLayout()
        act.addStretch(1)
        self.btn_next = QPushButton(i18n.t("proj.pick.next"))
        self.btn_next.setDefault(True)
        _fn = self.btn_next.font(); _fn.setBold(True); self.btn_next.setFont(_fn)
        self.btn_next.clicked.connect(self._on_next)
        btn_close = QPushButton(i18n.t("proj.btn_close"))
        btn_close.setAutoDefault(False)
        btn_close.clicked.connect(self.reject)
        act.addWidget(self.btn_next)
        act.addWidget(btn_close)
        v.addLayout(act)
        self.search.setFocus()

    def _fill(self):
        self.table.setRowCount(len(self._rows))
        right = Qt.AlignRight | Qt.AlignVCenter
        for i, r in enumerate(self._rows):
            dot = QTableWidgetItem("●")
            dot.setForeground(_COLORS[_STATE_ROLES[r["stan"]]])
            dot.setTextAlignment(Qt.AlignCenter)
            dot.setToolTip(i18n.t(_STATE_TIPS[r["stan"]]))
            # Części jednej całości (`queries.split_pct` w `release_readiness`): suma = pokrycie
            # flatem, nie 99 przy komplecie - te same liczby co karta teczki na Domu.
            mf, raw, pending = r["pct_master_flat"], r["pct_raw_flat"], r["pct_pending"]
            flat = f"{mf} % / {raw} %"
            if r["n_pending"]:
                flat += i18n.t("proj.pick.flat_pending", n=pending)
            cells = [dot, QTableWidgetItem(r["canon"]),
                     f"{r['hours']:.1f}", str(r["lights"]), str(r["nights"]), str(r["zestawy"]),
                     flat, f"{r['pct_master_dark']} %", r["last_night"] or ""]
            for col, cell in enumerate(cells):
                item = cell if isinstance(cell, QTableWidgetItem) else QTableWidgetItem(cell)
                if col > _PICK_COL_OBJECT:
                    item.setTextAlignment(right)
                self.table.setItem(i, col, item)
            self.table.item(i, _PICK_COL_OBJECT).setData(Qt.UserRole, r["object_id"])

    def _selected_row(self):
        """Zaznaczony WIDOCZNY wiersz albo `None` - wiersz ukryty filtrem bywa nadal zaznaczony,
        a „Dalej" na niewidocznej teczce wydawałby coś, czego user nie widzi."""
        rows = self.table.selectionModel().selectedRows()
        if not rows or self.table.isRowHidden(rows[0].row()):
            return None
        return rows[0].row()

    def _visible_rows(self):
        return [i for i in range(len(self._rows)) if not self.table.isRowHidden(i)]

    def _apply_filter(self, text):
        for i, r in enumerate(self._rows):
            self.table.setRowHidden(i, facet_model.search_hit(text, r["canon"], self._aliases) is None)
        widoczne = self._visible_rows()
        if self._selected_row() is None:
            self.table.clearSelection()
            if widoczne:
                self.table.selectRow(widoczne[0])
        # Stan pusty dwoma zdaniami jak listwa facetów (R-S3-5): „fraza nic nie trafiła" to inna
        # prawda niż „w bazie nie ma teczek" - pierwsza każe zmienić frazę, druga przyjąć lighty.
        fraza = (text or "").strip()
        if self._rows and not widoczne:
            self.empty_label.setText(i18n.t("proj.pick.empty_search", fraza=fraza))
        else:
            self.empty_label.setText(i18n.t("proj.pick.empty"))
        self.empty_label.setVisible(not widoczne)
        self._sync_next()

    def eventFilter(self, obj, event):
        """Up/Down w polu „Szukaj" przesuwa zaznaczenie tabeli. Fokus zostaje w polu: kolejna
        litera dalej zawęża, a Enter trafia w domyślne „Dalej" na przesuniętej teczce. Reszta
        klawiszy należy do pola (Home/End to kursor w tekście, nie skok po tabeli)."""
        if (obj is self.search and event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Up, Qt.Key_Down)):
            self._move_selection(-1 if event.key() == Qt.Key_Up else 1)
            return True
        return super().eventFilter(obj, event)

    def _move_selection(self, step):
        """Zaznacz sąsiednią WIDOCZNĄ teczkę (`step` = -1/+1), zatrzymując się na krańcach listy.
        Wiersze ukryte frazą się pomija - zaznaczenie niewidocznej teczki wydałoby coś, czego user
        nie widzi. Bez zaznaczenia pierwszy krok idzie na kraniec, z którego strzałka wchodzi."""
        widoczne = self._visible_rows()
        if not widoczne:
            return
        biezacy = self._selected_row()
        if biezacy is None:
            cel = widoczne[0] if step > 0 else widoczne[-1]
        else:
            k = widoczne.index(biezacy) + step
            cel = widoczne[min(max(k, 0), len(widoczne) - 1)]
        self.table.selectRow(cel)
        self.table.scrollToItem(self.table.item(cel, _PICK_COL_OBJECT))

    def _sync_next(self):
        self.btn_next.setEnabled(self._selected_row() is not None)

    def _on_double_click(self, row, _col):
        self.table.selectRow(row)
        self._on_next()

    def _on_next(self):
        row = self._selected_row()
        if row is None:
            return
        self.object_id = self._rows[row]["object_id"]
        self.accept()
