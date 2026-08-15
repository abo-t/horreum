"""Read-model osi TELESKOP (PLAN_gui §5 — read path). Czyste funkcje `con → list[Row]`,
testowalne BEZ Qt. ODCZYT nie jest „jedną klingą" (klinga dotyczy ZAPISU emitującego event) —
SELECT wolno wszędzie; zapis usera idzie WYŁĄCZNIE przez `horreum.repo`.

TWARDE OGRANICZENIE (PLAN_gui §4, rec. nr 6): wyłącznie **SQL-LITERAŁY + parametry `?`** oraz
wyłącznie **`con.execute`** (bez pandas/ORM/`read_sql` — ścieżki niewidziane przez meta-test AST,
`EXEC_METHODS=execute*`). Dynamiczny SQL (f-string) w tym pliku WYSADZIŁBY bramkę §7.1, mimo że to
czysty odczyt: `_first_sql_verb` zwraca `None` dla nie-literału, a `None` poza `repo.py`/`db.py`
= offender. Warianty/filtry => parametry `?` w stałym literale albo OSOBNE literały w gałęziach `if`,
NIGDY składanie stringa SQL. Listy zmiennej długości (id/keywordy) idą jako TABLICA JSON przez
`json_each(?)` — literał stały, jeden parametr (zamiast dynamicznych `?` — PLAN_gui_grid §3).
"""

import json
import os
import re

from horreum.grouper import NO_TELESCOPE_KINDS      # jeden właściciel zbioru rodzajów poza osią
from horreum.resolve.frames import LIGHT_KINDS
from horreum.resolve.objects import CLEARABLE_OBJECT_SOURCES, WEAK_OBJECT_SOURCES
from horreum.resolver import NO_OBJECT_CARD_FILETYPES, path_proposals, review_state
from horreum.stacks import REASON_NO_OBJECT, REASON_OFFSET_UNKNOWN


PATH_TAIL_DIRS = 2
"""Ile katalogów pokazujemy przed nazwą pliku w panelu drążenia — ZMIERZONE, nie wybrane.

Na 703 RAW-ach bez obiektu sam folder-rodzic ma **3 różne wartości** (`portable`, `OSC`,
`NOCONFIG`) i nie rozróżnia niczego; ostatnie DWA katalogi mają **34** — i jest to dokładnie
tyle, ile nazw wyprowadza z tych ścieżek świadek S2 („34 nazw / 703 klatek" w kolejce). Trzeci
katalog dokłada `LIGHTS` u wszystkich, czyli zero informacji za dodatkową szerokość."""


def path_tail(path, dirs=PATH_TAIL_DIRS):
    """Ogon ścieżki: `dirs` ostatnich katalogów + nazwa pliku. Czysta funkcja, zero SQL.

    Kolumna nazywa się „Ścieżka", a pokazywała `basename` — i to nie jest drobiazg nazewniczy,
    tylko brak informacji, po której user wybiera (firsthand 0808, DWA zgłoszenia: najpierw
    gotowe stosy, potem RAW-y). Nazwy z lustrzanki (`astro_dsc4198.dng`) i nazwy z WBPP
    (`masterLight_BIN-1_….xisf`) nie niosą tożsamości ŻADNEJ — niesie ją katalog.

    JEDNA REGUŁA DLA WSZYSTKICH KUBEŁKÓW, bez gałęzi per rodzaj klatki. Poprzednia wersja ciął
    to po `kind='master_light'` z uzasadnieniem „light niesie oznaczenie we własnej nazwie" —
    **uzasadnienie było fałszywe i obalił je pomiar** (703 RAW-y z nazwami bez oznaczenia).
    Kubełki przeglądu z definicji zbierają klatki, których maszyna NIE UMIAŁA nazwać; nie ma
    wśród nich takiego, w którym katalog byłby szumem.

    Cena nazwana: przy stosach widać też `master`, przy RAW-ach `portable` — segmenty wspólne
    całej populacji. Alternatywą byłaby lista segmentów „nieistotnych", czyli zgadywanie cudzej
    konwencji katalogów; wolimy dwa znaki szumu od reguły, która przy pierwszym nowym drzewie
    zacznie ukrywać coś, co niesie sens."""
    if not path:
        return ""
    czesci = [c for c in re.split(r"[\\/]", str(path)) if c]
    return "\\".join(czesci[-(dirs + 1):])


def stack_folder(path):
    """Folder OBRAZU ze ścieżki gotowego stosu — albo `None`. Czysta funkcja, zero SQL.

    DZIADEK, NIE RODZIC — i to jest zmierzone, nie estetyczne: drzewo WBPP kończy się katalogiem
    `master`, więc rodzic brzmi tak samo u WSZYSTKICH stosów i nie rozróżnia niczego
    (`…\\A7R3_105_LMC\\master\\masterLight_….xisf`). Gdy `master` nie występuje, właściwą
    odpowiedzią jest rodzic — stąd warunek, a nie stałe piętro w górę.

    Powstało z firsthandu 0808: kubełek „bez nazwy, gotowe stosy" daje 18 wierszy, których nie da
    się odróżnić, bo nazwy plików generuje WBPP i sześć stosów LMC czyta się identycznie.
    Tożsamość siedzi WYŁĄCZNIE w tym segmencie ścieżki. JEDEN właściciel reguły, bo pytają o nią
    dwie powierzchnie (kolumna Obiekt w Zbiorach i lista drążenia w Przeglądzie obiektów) —
    dwie kopie rozjechałyby się przy pierwszej zmianie układu drzewa."""
    if not path:
        return None
    czesci = [c for c in re.split(r"[\\/]", str(path)) if c]
    if len(czesci) < 2:
        return None
    rodzic = czesci[-2]
    if rodzic.lower() == "master" and len(czesci) >= 3:
        dziadek = czesci[-3]
        # KORZEŃ NIE JEST FOLDEREM OBIEKTU (bramka pakietu, zarzut 9): przy układzie
        # `X:\master\plik` dziadkiem jest litera dysku, więc kolumna pokazywałaby `⟨R:⟩` —
        # podpowiedź bez treści, udającą nazwę. Wtedy uczciwiej milczeć.
        return None if dziadek.endswith(":") else dziadek
    return rodzic


OBJECT_CELL_STATES = ("canon", "cleared", "kind", "raw", "hint")
"""Stany komórki „Obiekt" — LUSTRO gałęzi `object_cell`, do bramki parytetu z katalogiem i18n.

Kolejność JEST kolejnością rozstrzygania w `object_cell` i to nie jest przypadek: `cleared` bije
`kind`, a `kind` bije `raw`, bo klatka może spełniać kilka warunków naraz, a powiedzieć ma tę
rzecz, która jest jej NAJŚWIEŻSZYM faktem i tłumaczy pusty facet obok."""

CLEARED_MARK = "↺"
"""Znacznik cofnięcia — TEN SAM, którym kolejka przeglądu znaczy wiersze cofnięte (paczka G3).
Jeden alfabet dla jednego faktu; drugi znak kazałby uczyć się dwa razy tego samego."""


def object_cell(row):
    """Komórka „Obiekt" jako para `(tekst, stan)` — JEDEN właściciel polityki tej kolumny.

    Qt-wolne i to jest wybór, nie przypadek: polityka jest czystą funkcją, więc jej bramki jadą
    bez PySide6 — jak `stack_folder`, który wyszedł tu z tego samego powodu (dwie powierzchnie
    pytają o tę samą regułę).

    DLACZEGO PARA, A NIE SAM STRING. Do tej paczki kolumna zwracała `object_canon or object_raw`
    i zlewała w jednym napisie DWA RÓŻNE TWIERDZENIA: „ten obiekt tak się nazywa" (kanon osi)
    oraz „tyle mówi nagłówek pliku" (surowe zeznanie). Skutek widać było gołym okiem po geście
    „Cofnij przypisanie": wiersz dalej pokazywał `NGC7023`, a facet Obiekt na tym samym ekranie
    był już pusty — jeden ekran, dwa sprzeczne zdania o tych samych klatkach (`R-S3-4`).

    I NIE JEST TO DŁUG O ZEROWEJ POPULACJI. Zmierzone na żywym archiwum: **2364 klatki
    KALIBRACYJNE** (flat 2256, master_flat 74, master_dark 34) niosą w nagłówku `FlatWizard`,
    `DARK` albo `Target` — i kolumna twierdziła o nich „obiektem tego flata jest FlatWizard",
    choć kalibracja obiektu nie ma z DEFINICJI. Nagrobek dokłada trzeci powód do populacji, która
    istnieje niezależnie od niego.

    NAGROBEK NIGDY NIE JEST PUSTKĄ (`CLEARED_MARK`) — i to też jest z pomiaru: **845 klatek nieba
    nie ma `object_raw`** (w tym 757 RAW-ów z lustrzanki, które nie mają gdzie go nieść). Ich
    komórka jest pusta, a kursywa i szarość na pustym stringu są niewidzialne — bez znacznika dług
    zostałby otwarty dla większości własnej przyszłej populacji.

    PODPOWIEDŹ ZE ŚCIEŻKI (`hint`) NIE UDAJE NAZWY: nawiasy kątowe odróżniają ją od kanonu, bo
    wzięcie „tyle wiem z folderu" za „tak się ten obiekt nazywa" byłoby gorsze niż pusta komórka.
    Tylko `master_light`, bo light z akwizycji ma własną drogę (szczebel ścieżki S2 PROPONUJE mu
    kanon). Nic z tego nie trafia do bazy: to warstwa PREZENTACJI, gest osi należy do człowieka.

    WEJŚCIEM JEST SŁOWNIK, NIE `sqlite3.Row` — i to jest kontrakt, nie szczegół (bramka pakietu
    0810, zarzut A#1): `Row` nie ma metody `.get` W OGÓLE, więc podanie surowego wiersza kończy się
    `AttributeError` przy pierwszej komórce. Wołający ma go rozpakować (`grid._derive` robi
    `{k: row[k] for k in row.keys()}`), bo `kind`/`path`/`object_source` wchodzą nie z każdego
    zapytania gridu, a `Row` na brakującym kluczu rzuca — `dict.get` oddaje `None`.

    WIERSZ NIEMY O RODZAJU NIE DOSTAJE ZDANIA O RODZAJU (bramka pakietu 0810, zarzut zgodny
    u dwóch soczewek). Gałąź `kind` twierdzi „kalibracja obiektu nie ma z DEFINICJI", więc wolno
    ją postawić WYŁĄCZNIE przy rodzaju ZNANYM: `row.get("kind")` bez klucza oddaje `None`, a `None
    not in LIGHT_KINDS` jest prawdą — light u wołającego bez `kind` dostawał tooltip o kalibracji.
    Dziś populacja jest zerowa (jedyny konsument to `grid._derive` ← `base_rows`, która `kind`
    niesie zawsze, a `frame.kind` jest `NOT NULL`), ale kontrakt tej funkcji sam zaprasza drugą
    powierzchnię — więc fallbackiem jest `raw`, który o rodzaju nie twierdzi niczego."""
    if row.get("object_canon"):
        return row["object_canon"], "canon"
    raw = row.get("object_raw") or ""
    if row.get("object_source") == "user_cleared":
        return (f"{CLEARED_MARK} {raw}" if raw else CLEARED_MARK), "cleared"
    # STAN TŁUMACZY TEKST, więc bez tekstu nie ma czego tłumaczyć — i dlatego pytanie o ZEZNANIE
    # stoi PRZED pytaniem o rodzaj. Odwrotna kolejność dawała PUSTEJ komórce tooltip „kalibracja
    # obiektu nie ma z definicji" wszędzie tam, gdzie wiersz nie niesie `kind` (a nie niesie go
    # z każdego zapytania gridu) — czyli zdanie o rodzaju, którego ten wiersz nie zna. Złapała to
    # własna bramka tej paczki, nie recenzja.
    if raw:
        rodzaj = row.get("kind")
        return raw, "kind" if rodzaj is not None and rodzaj not in LIGHT_KINDS else "raw"
    if row.get("kind") == "master_light":
        folder = stack_folder(row.get("path"))
        if folder:
            return f"⟨{folder}⟩", "hint"
    return "", "canon"          # nic do powiedzenia — pusta komórka bez stanu do wytłumaczenia


def telescope_label(row):
    """JEDYNY właściciel reguły `label → telescop_canon` (P-B; wcześniej ta sama reguła siedziała
    w czterech miejscach warstwy widżetów i rozjeżdżała się o końcowe `or ""`).

    Nazwa usera (`label`), a gdy teleskop jeszcze nienazwany — `telescop_canon` z nagłówka
    (realny przypadek: cała oś `proposed`; kolumna NIE ma prawa milczeć, bo nazwa z nagłówka jest
    user-czytelna). Klatka bez osi (LEFT JOIN bez configu — review) → `''`: brak osi, nie brak danych.

    Wiersz OSI niesie kolumnę `label`, wiersz KLATKI `telescope_label` (alias JOIN-a) — właściciel
    zna oba zapisy, wołający żadnego. Wiersz bez którejkolwiek kolumny to błąd zapytania, nie stan
    do obsłużenia: `KeyError`/`IndexError` wprost (EXPECT).

    Ta sama reguła w DANYCH żyje osobno i świadomie: `projection.LAYOUTS['wbpp-feed']` robi coalesce
    krotką nazw kolumn, bo layout jest danymi (D-P1), nie kodem — konsolidacja z tą funkcją
    skasowałaby tamten kontrakt."""
    label = row["telescope_label"] if "telescope_label" in row.keys() else row["label"]
    return label or row["telescop_canon"] or ""


def active_telescopes(con):
    """Aktywne (KANONICZNE) teleskopy z licznością klatek — lista główna GUI.

    Filtr kanoniczności JAWNY (`WHERE t.merged_into IS NULL`, rec.R2 nr 2): widok
    `telescope_canonical` zwraca WSZYSTKIE wiersze (kanon + scalone z ich `canon_id`), więc sam join
    przez widok nie odsiewa scalonych — bez tego WHERE scalony `approved` wyciekłby jako osobny wiersz
    (§3b). Licznik agreguje po `canon_id` ścieżką `telescope_canonical → config → frame` (rec. nr 7):
    klatki scalonych członków rolują się pod kanon, kolizja kamery (dwa configi tej samej kamery)
    sumuje się pod jednym kanonem. `LEFT JOIN` => teleskop bez klatek ma `frame_count=0` (nie znika).
    Frame z `config_id IS NULL` (review) NIE dołącza się do żadnego configu => poza sumą (poprawne —
    jest w delcie, nie na osi). Zwraca wiersze: id, telescop_canon, label, status, f_ratio_nominal,
    focal_nominal, frame_count."""
    return con.execute(
        "SELECT t.id, t.telescop_canon, t.label, t.status, t.f_ratio_nominal, t.focal_nominal, "
        "       COUNT(fr.id) AS frame_count "
        "FROM telescope t "
        "LEFT JOIN telescope_canonical tc ON tc.canon_id = t.id "
        "LEFT JOIN config c ON c.telescope_id = tc.id "
        "LEFT JOIN frame fr ON fr.config_id = c.id "
        "WHERE t.merged_into IS NULL "
        "GROUP BY t.id "
        "ORDER BY t.id"
    ).fetchall()


def merged_under(con, canon_id):
    """Teleskopy scalone „pod" danym kanonem (widok szczegółu — co zwinięto w ten teleskop). Dzięki
    inwariantowi głębokość ≤ 1 (§3a) wszystkie są BEZPOŚREDNIMI członkami (`merged_into = canon_id`),
    więc prosty filtr po kolumnie wystarcza — nie ma głębszych łańcuchów do rozwijania. Zwraca wiersze:
    id, telescop_canon, label, status, f_ratio_nominal, focal_nominal (puste, gdy nic nie scala)."""
    return con.execute(
        "SELECT id, telescop_canon, label, status, f_ratio_nominal, focal_nominal "
        "FROM telescope WHERE merged_into = ? ORDER BY id",
        (canon_id,),
    ).fetchall()


def axis_events(con, telescope_id=None, limit=200):
    """Podgląd eventów osi teleskopu (audyt — kto/kiedy/before→after). `telescope_id=None` => cała oś
    (`target LIKE 'telescope:%'`, w tym `telescope.proposed/review` od groupera); inaczej historia
    JEDNEGO teleskopu (`target = 'telescope:<id>'`). Najnowsze pierwsze (`id DESC`), ucięte do `limit`.

    Dwie OSOBNE gałęzie z literałami SQL (nie jeden f-string) — wariant filtra przez parametr `?`
    w stałym literale, zgodnie z §4 (dynamiczny SQL wysadziłby bramkę). `target` składamy w Pythonie
    i wiążemy jako `?` — to wartość parametru, nie tekst SQL (literał pozostaje stały)."""
    if telescope_id is None:
        return con.execute(
            "SELECT id, ts, actor, verb, target, payload, reason FROM event "
            "WHERE target LIKE 'telescope:%' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return con.execute(
        "SELECT id, ts, actor, verb, target, payload, reason FROM event "
        "WHERE target = ? ORDER BY id DESC LIMIT ?",
        (f"telescope:{telescope_id}", limit),
    ).fetchall()


# ============================================================ oś OBSERWATORIUM (PLAN_os_obserwatorium §3)
# Read-model osi stanowisk — mirror osi teleskopu (lista→scal→nazwij). RÓŻNICA: licznik klatek liczony
# ścieżką `observatory_canonical → frame` BEZPOŚREDNIO przez `frame.observatory_id` (obserwatorium NIE ma
# configu — inaczej niż teleskop). Filtr kanoniczności JAWNY (`WHERE merged_into IS NULL`), jak teleskop.


def active_observatories(con):
    """Aktywne (KANONICZNE) stanowiska z licznością klatek — lista główna osi OBSERWATORIUM.

    Filtr kanoniczności JAWNY (`WHERE o.merged_into IS NULL`, jak `active_telescopes`): widok
    `observatory_canonical` zwraca WSZYSTKIE wiersze (kanon + scalone), więc sam join go nie odsiewa —
    bez WHERE scalony wyciekłby jako osobny wiersz. Licznik agreguje po `canon_id` ścieżką
    `observatory_canonical → frame` BEZPOŚREDNIO przez `frame.observatory_id` (BEZ configu): klatki
    scalonych członków rolują się pod kanon. `LEFT JOIN` => stanowisko bez klatek ma `frame_count=0`
    (nie znika). Zwraca: id, name, lat, lon, elev, status, frame_count."""
    return con.execute(
        "SELECT o.id, o.name, o.lat, o.lon, o.elev, o.status, "
        "       COUNT(fr.id) AS frame_count "
        "FROM observatory o "
        "LEFT JOIN observatory_canonical oc ON oc.canon_id = o.id "
        "LEFT JOIN frame fr ON fr.observatory_id = oc.id "
        "WHERE o.merged_into IS NULL "
        "GROUP BY o.id "
        "ORDER BY o.id"
    ).fetchall()


def merged_under_observatory(con, canon_id):
    """Stanowiska scalone „pod" danym kanonem (widok szczegółu — co zwinięto w to stanowisko). Dzięki
    inwariantowi głębokość ≤ 1 (gwardy `merge_observatory`) wszystkie są BEZPOŚREDNIMI członkami
    (`merged_into = canon_id`). Zwraca: id, name, lat, lon, elev, status (puste, gdy nic nie scala)."""
    return con.execute(
        "SELECT id, name, lat, lon, elev, status "
        "FROM observatory WHERE merged_into = ? ORDER BY id",
        (canon_id,),
    ).fetchall()


def observatory_axis_events(con, observatory_id=None, limit=200):
    """Podgląd eventów osi obserwatorium (audyt — kto/kiedy/before→after). `observatory_id=None` =>
    cała oś (`target LIKE 'observatory:%'`: proposed/named/merged/unmerged); inaczej historia JEDNEGO
    stanowiska. Najnowsze pierwsze (`id DESC`), ucięte do `limit`. Dwie OSOBNE gałęzie z literałami SQL
    (§4 — dynamiczny SQL wysadziłby bramkę); `target` składany w Pythonie i wiązany jako `?`.
    (`observatory.assigned` celuje w `frame:<id>` — per-klatka, świadomie poza audytem osi, jak
    `config.assigned` przy teleskopie.)"""
    if observatory_id is None:
        return con.execute(
            "SELECT id, ts, actor, verb, target, payload, reason FROM event "
            "WHERE target LIKE 'observatory:%' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return con.execute(
        "SELECT id, ts, actor, verb, target, payload, reason FROM event "
        "WHERE target = ? ORDER BY id DESC LIMIT ?",
        (f"observatory:{observatory_id}", limit),
    ).fetchall()


# ============================================================ oś OBIEKT (PLAN_gui_object §3, read-only)
# Read-model biblioteki + kolejki przeglądu. KIND-AWARE: obiekt liczony TYLKO na light/master_light
# (kalibracja nie ma obiektu z definicji — memory horreum-object-resolution-kind-aware). Filtr teleskopu
# ZAWSZE przez `telescope_canonical` (rolowanie scalonych pod kanon). Filtry opcjonalne realizowane
# wzorcem `(? IS NULL OR kol = ?)` w JEDNYM stałym literale (R#5) — NIE rozgałęzieniem 8 SELECT-ów:
# literał stały (bramka AST §7.1 widzi `SELECT`), wartość wiązana DWUKROTNIE per filtr.


def library_objects(con, *, telescope_id=None, camera_id=None, filter_canon=None):
    """Biblioteka: kanoniczne obiekty z licznością klatek (light/master_light), z OPCJONALNYMI filtrami
    osi. PREDYKAT = `frame.kind` (R#1: `object.kind` to inne pole — `deep_sky|solar_system|comet` po
    kroku 5a — i NIE jest zwracane ani używane jako predykat; widok renderuje `canon`/`catalog`).
    `telescope_id` = id KANONICZNEGO teleskopu (dopasowanie przez `telescope_canonical.canon_id`, więc
    klatki spod scalonych członków rolują się pod kanon). JOIN (nie LEFT) frame→object: obiekt bez
    klatek po filtrze znika z widoku (poprawne — filtr zawęża). Zwraca: id, canon, catalog, frame_count."""
    return con.execute(
        "SELECT o.id, o.canon, o.catalog, COUNT(f.id) AS frame_count "
        "FROM object o "
        "JOIN frame f ON f.object_id = o.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "WHERE f.kind IN ('light','master_light') "
        "  AND (? IS NULL OR tc.canon_id = ?) "
        "  AND (? IS NULL OR f.camera_id = ?) "
        "  AND (? IS NULL OR f.filter_canon = ?) "
        "GROUP BY o.id "
        "ORDER BY o.canon",
        (telescope_id, telescope_id, camera_id, camera_id, filter_canon, filter_canon),
    ).fetchall()


def object_frames(con, object_id, *, telescope_id=None, camera_id=None, filter_canon=None):
    """Klatki danego obiektu (light/master_light) z tymi samymi filtrami co biblioteka. Location przez
    `MIN(id)` SPOŚRÓD OBECNYCH, z powrotem do dowolnej (R#3: frame 1:N location - bez tego N lokalizacji
    zduplikowałoby klatkę; D-V-9: spośród kopii wygrywa ŻYWA, nie ta, która wjechała pierwsza - inaczej
    panel pokazywał martwy adres i kolumnę „Obecna: Nie" dla klatki, której plik leży na dysku).
    Reguła wyboru adresu jest ZNAK W ZNAK ta sama, co w `base_rows` (tam pełne uzasadnienie i pomiar) -
    ten sam fakt renderowany na dwóch powierzchniach ma dwa razy znaczyć to samo. `present` to
    KOLUMNA statusu, NIE predykat (R#7: frame, którego wszystkie lokalizacje mają present=0, MUSI być
    widoczny — tożsamość = sha1_data, nie obecność; „baza=autorytet"). `telescope_label` +
    `telescop_canon` z kanonicznego teleskopu (canon = fallback etykiety, gdy teleskop nienazwany).
    Zwraca: frame_id, sha1_data, filter_canon, telescope_label, telescop_canon, f_ratio_nominal,
    focal_nominal, camera_model, date_obs, exptime, path, drive_letter, present."""
    return con.execute(
        "SELECT f.id AS frame_id, f.sha1_data, f.filter_canon, "
        "       t.label AS telescope_label, t.telescop_canon, t.f_ratio_nominal, t.focal_nominal, "
        "       cam.model_canon AS camera_model, "
        "       h.date_obs, h.exptime, loc.path, loc.drive_letter, loc.present "
        "FROM frame f "
        "LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN telescope t ON t.id = tc.canon_id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "LEFT JOIN location loc ON loc.id = COALESCE("
        "        (SELECT MIN(id) FROM location WHERE frame_id = f.id AND present = 1), "
        "        (SELECT MIN(id) FROM location WHERE frame_id = f.id)) "
        "WHERE f.object_id = ? "
        "  AND f.kind IN ('light','master_light') "
        "  AND (? IS NULL OR tc.canon_id = ?) "
        "  AND (? IS NULL OR f.camera_id = ?) "
        "  AND (? IS NULL OR f.filter_canon = ?) "
        "ORDER BY f.id",
        (object_id, telescope_id, telescope_id, camera_id, camera_id, filter_canon, filter_canon),
    ).fetchall()


def review_queue(con):
    """Kolejka przeglądu osi obiektu ze STANU (NIE z `count(event)` — R#2/R#4: `flag_config_review`/
    `object.review_summary` mnożą eventy przy re-skanie, stan jest idempotentny). Kanały:
      - `object_review`: light/master_light z `object_id IS NULL` i obecnym `object_raw` (JOIN header,
        `GROUP BY object_raw, cleared`) — co user zostawił nierozpoznane, rozszczepione po ŹRÓDLE:
        klatka z nagrobkiem dostaje własny wiersz, bo jest WERDYKTEM, a nie brakiem wiedzy (S3);
      - `nameless_count`: light/master_light z `object_id IS NULL`, z nagłówkiem, ale BEZ `object_raw`
        (T5a) — klatka, która nie ma o czym zeznawać, więc GROUP BY nie ma jej jak pokazać;
        drążenie do klatek daje `nameless_frames` (P-D) i to ONO jest właścicielem predykatu;
      - `config_review_count`: `config_id IS NULL AND EXISTS(header)` — KONIECZNY `EXISTS(header)`
        (R#2): grouper iteruje `frame JOIN header`, więc klatka bez nagłówka nigdy nie jest flagowana
        i cicho zostaje config NULL; bez tego predykatu licznik zlałby trzy stany;
      - `headerless_count`: frame BEZ wiersza `header` (`NOT EXISTS`) — osobny realny kubełek
        wydobyty spod fałszywego config-review; liczony po WSZYSTKICH rodzajach (inna oś: skan);
      - `unreadable_count`: klatki z ≥1 kopią, która STAŁA SIĘ nieczytelna (`location.unreadable_since
        NOT NULL`, #13) — drążenie do dokładnych kopii daje `unreadable_copies` (Z6/P4).
    Liczniki poza obiekt-review i `nameless_count` liczy `resolver.review_state` — JEDEN właściciel
    predykatu stanu (#12): ta sama derywacja zasila raport dostawy, więc kolejka i raport nie mogą
    się rozjechać.

      - `nameless_raw_count`: jak wyżej, ale w formacie, który NIE MA JAK zeznać o obiekcie
        (`resolver.NO_OBJECT_CARD_FILETYPES` — EXIF nie zna `OBJECT` ani RA/DEC). Osobny kubełek,
        bo osobna droga naprawy: RĘCZNE przypisanie, nigdy karta w pliku. Od S4 kubełek DRĄŻY
        (`nameless_raw_frames`) i niesie akcję, więc licznik jest DŁUGOŚCIĄ tego drążenia
        (D-PD-10) — do S4 był ostatnim wyłomem wobec tej reguły w tym pliku: osobny `COUNT`
        pokazywałby inną liczbę niż lista, którą kubełek otwiera. Kotwica akceptacji
        (`resolver.nameless_raw_lights`) zostaje osobnym literałem po stronie rdzenia i równość
        całej trójki pinuje test (bramka 13).
      - `nameless_stacks_count`: jak wyżej, ale to GOTOWY OBRAZ po integracji (`kind='master_light'`,
        droga „Stosy" — I-2b/D-P-I-5). Osobny kubełek, bo osobna POPULACJA — nie dlatego, że nie ma
        drogi naprawy. Od D-0802-1 (2026-08-02) droga jest ta sama co u lightów (karta `OBJECT`
        do pliku), więc kubełek DRĄŻY (`nameless_stack_frames`) i niesie akcję; licznik jest
        długością tego drążenia (D-PD-10), nie osobnym COUNT-em.

    PARTYCJA wobec perspektywy gridu (T5a — dwa predykaty „do przeglądu" pod jedną nazwą; szew
    zmierzony 2026-07-31, żywa pf4: 0 nazwanych + 25 bezimiennych + 0 lightów bez nagłówka = 25):
        sum(object_review.n) + nameless_count + nameless_cleared_count
            + nameless_raw_count + nameless_raw_cleared_count
            + nameless_stacks_count + nameless_stacks_cleared_count
            + (light/master_light bez wiersza `header`) == |review_frame_ids|
    `object_review` domyka się bez osobnego członu, bo rozszczepienie siedzi w jego GROUP BY —
    suma po wierszach liczy obie połówki. Trzy pozostałe kubełki mają po DWIE liczby, bo ich
    licznik jest DŁUGOŚCIĄ drążenia, a drążeń jest po dwa (S3/R-S2b-1 dla RAW-a, R-S3-1 dla
    lightów archiwum i gotowych stosów).
    Człony RAW i STOSY dopisane 2026-08-01 i to nie jest kosmetyka: `review_frame_ids` pyta
    o sam brak obiektu, więc jedne i drugie w nim SĄ. Wycięcie populacji z `nameless_count` bez
    własnego kubełka rozspójnia partycję dokładnie o jej liczbę — dla RAW o 763, dla stosów o 22.
    Trzeci człon jest PODZBIOREM `headerless_count` (ten liczy też kalibrację i `unknown`, bo mówi
    o skanie, nie o osi obiektu) — dlatego kolejka nie może go po prostu dodać: te dwa liczniki
    odpowiadają na różne pytania. Dopóki `nameless_count` nie istniał, kolejka milczała o klatkach,
    które grid pokazywał — stąd ten kubełek.

      - `path_proposed_*`: PODZBIÓR kubełka RAW, świadomie **POZA PARTYCJĄ** (S2, D-OW-2/B) —
        te klatki są już policzone w `nameless_raw_count` i dodanie ich do równania rozspójniłoby
        je dokładnie o własną liczbę. To nie jest szósty kubełek, tylko DROGA WYJŚCIA pokazana przy
        kubełku, który ją ma: ścieżka proponuje kanon, a zapis następuje dopiero gestem człowieka.
        Dwie liczby, bo jednostki są dwie: `names` to pozycje do przejrzenia (≈35), `frames` to
        klatki, które zmienią stan po zatwierdzeniu (≈707). Jeden właściciel derywacji —
        `resolver.path_proposals`. **`None` znaczy „nie policzono"** (słownik obiektów własnych ma
        błąd), a `0` — „nie ma czego liczyć"; wołający ma te dwa stany rozróżnić.

    Zwraca dict: {object_review: [Row(object_raw, cleared, n)], nameless_count: int,
    nameless_cleared_count: int, nameless_raw_count: int, nameless_raw_cleared_count: int,
    nameless_stacks_count: int, nameless_stacks_cleared_count: int,
    path_proposed_names: int, path_proposed_frames: int,
    config_review_count: int, headerless_count: int, unreadable_count: int}."""
    object_review = con.execute(
        "SELECT h.object_raw AS object_raw, "
        "       (f.object_source IS 'user_cleared') AS cleared, COUNT(*) AS n "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind IN ('light','master_light') AND f.object_id IS NULL "
        "  AND f.superseded_by IS NULL "
        "  AND f.retired_at IS NULL "
        "  AND h.object_raw IS NOT NULL "
        "GROUP BY h.object_raw, cleared "
        # KOLEJNOŚĆ PROWADZI NAZWĄ, NIE POŁÓWKĄ (R-S3-2). `ORDER BY n DESC` sortował POŁÓWKAMI,
        # więc obie połowy tej samej nazwy rozdzielał obcy kubełek: zmierzone `LDN 1174 · 9` →
        # `IC 1805 · 7` → `LDN 1174 · 5 · cofnięte ręką`. Przy 42 obiektach dzieli je cały ekran,
        # a user „załatwia LDN 1174" i zostawia drugą połówkę, nie wiedząc, że istnieje.
        # Klucz pierwszy = SUMA obu połówek (okno nad agregatem — pozycja waży tym, ile roboty
        # niesie NAZWA), klucz drugi = nazwa, więc połówki zawsze stoją obok siebie; `cleared`
        # na końcu trzyma nietkniętą PRZED cofniętą, bo podwiersz ma iść pod swoim wierszem.
        "ORDER BY SUM(COUNT(*)) OVER (PARTITION BY h.object_raw) DESC, object_raw, cleared"
    ).fetchall()
    # Lustro `object_review` po drugiej stronie NULL-a: JOIN header = „zeznanie JEST", brak
    # `object_raw` = „nie mówi o obiekcie". Bez tego kubełka klatki wpadały między predykaty.
    # JEDEN właściciel predykatu (D-PD-10): licznik to DŁUGOŚĆ read-modelu drążenia, nie osobny
    # COUNT — dwa literały rozjechałyby się przy pierwszej zmianie kształtu (kubełek pokazywałby
    # inną liczbę niż lista, którą otwiera).
    nameless = nameless_frames(con)
    # DWIE LICZBY ROZŁĄCZNE, nie licznik i jego podzbiór (S3/R-S2b-1): klatka z nagrobkiem wraca
    # do tego kubełka nieodróżnialna od nietkniętej, a akcja ręki cicho ją pomijała. Sumują się
    # w partycji, bo `review_frame_ids` pyta o sam brak obiektu i widzi obie.
    #
    # OD R-S3-1 ROZSZCZEPIENIE MA KAŻDY Z CZTERECH KUBEŁKÓW BEZIMIENNYCH, nie dwa z nich. Dopisek
    # dostały wcześniej `object_review` (GROUP BY) i RAW, a lighty archiwum i gotowe stosy — nie;
    # cofnięty FITS i cofnięty stos wracały do wspólnego wiersza nieodróżnialne, choć od D-OW-7 ta
    # druga droga jest osiągalna gestem. To był dług WIDOKU, nie mechanizmu (writeback karty gasi
    # nagrobek poprawnie), i dlatego rozszczepienie kończy się na read-modelu plus wierszu kolejki.
    nameless_cleared = nameless_frames(con, cleared=True)
    raw = nameless_raw_frames(con)               # licznik = długość drążenia (D-PD-10), jak wyżej
    raw_cleared = nameless_raw_frames(con, cleared=True)
    stosy = nameless_stack_frames(con)          # licznik = długość drążenia (D-PD-10), jak wyżej
    stosy_cleared = nameless_stack_frames(con, cleared=True)
    # Szczebel ścieżki wciągnął SŁOWNIK obiektów własnych do read-modelu kolejki, a słownik jest
    # plikiem CZŁOWIEKA i jego edycja to operacja wspierana. Literówka w assecie ma zostać
    # ZGŁOSZONA, nie wywalić widok tracebackiem przy samym otwarciu — i NIE ma udawać zera:
    # `None` znaczy „nie policzono", `0` znaczy „nie ma czego liczyć". Dwie różne prawdy.
    try:
        propozycje = path_proposals(con)        # PODZBIÓR kubełka RAW, poza partycją (wyżej)
        prop_names, prop_frames = len(propozycje), sum(p.n_frames for p in propozycje)
    except ValueError:
        prop_names = prop_frames = None
    st = review_state(con)
    # Bliźniak kubełka sprzętu po drugiej stronie gestu (R1, bramka 3a zarzut 1): DROGA POWROTNA
    # dla pomyłki ręki. Licznik = długość drążenia (D-PD-10), jak u kubełków bezimiennych.
    reka = config_by_hand_frames(con)
    return {"object_review": object_review, "config_by_hand_count": len(reka),
            "nameless_count": len(nameless),
            "nameless_cleared_count": len(nameless_cleared),
            "nameless_raw_count": len(raw),
            "nameless_raw_cleared_count": len(raw_cleared),
            "nameless_stacks_count": len(stosy),
            "nameless_stacks_cleared_count": len(stosy_cleared),
            "path_proposed_names": prop_names,
            "path_proposed_frames": prop_frames,
            "config_review_count": st.no_config,
            "headerless_count": st.headerless, "unreadable_count": st.unreadable}


def object_review_frames(con, object_raw, cleared=False):
    """Drążenie pojedynczej pozycji obiekt-review: klatki o danym `object_raw`, wciąż nierozwiązane
    (`object_id IS NULL`). JOIN header (object_raw mieszka w header, R#3).

    Adres przez `MIN(id)` SPOŚRÓD OBECNYCH, z powrotem do dowolnej - reguła ZNAK W ZNAK jak
    w `base_rows` (D-V-9; tam pomiar i pełne uzasadnienie). Tu waży podwójnie: to lista, z której
    człowiek WYBIERA klatki do zapisu, więc adres martwy przy żywym pliku myli w chwili decyzji.

    KLUCZ JEST PARĄ (`object_raw`, `cleared`) — S3/R-S2b-1. Klatka z NAGROBKIEM (`user_cleared`)
    wraca do tego samego kubełka co nietknięta, bo predykat pyta o sam brak obiektu; do rozszczepienia
    wyglądała identycznie, a akcja „Przypisz obiekt…" cicho ją pomijała (klinga chroni werdykt ręki
    przed przypadkowym wskrzeszeniem). Drążenie po samym stringu zwróciłoby UNIĘ obu pozycji, więc
    zapis sięgnąłby klatek spoza klikniętego wiersza.

    Predykat idzie PARAMETREM na stałym literale (`IS 'user_cleared'` zwraca 0/1, null-safe), a nie
    dwiema gałęziami SQL — dwa literały tego samego SELECT-a rozjechałyby się przy pierwszej zmianie
    kolumn, a to ten sam panel je renderuje.

    Zwraca: frame_id, sha1_data, telescope_label, telescop_canon, f_ratio_nominal, focal_nominal,
    camera_model, date_obs, path."""
    return con.execute(
        "SELECT f.id AS frame_id, f.sha1_data, t.label AS telescope_label, "
        "       t.telescop_canon, t.f_ratio_nominal, t.focal_nominal, "
        "       cam.model_canon AS camera_model, h.date_obs, loc.path "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN telescope t ON t.id = tc.canon_id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "LEFT JOIN location loc ON loc.id = COALESCE("
        "        (SELECT MIN(id) FROM location WHERE frame_id = f.id AND present = 1), "
        "        (SELECT MIN(id) FROM location WHERE frame_id = f.id)) "
        "WHERE f.kind IN ('light','master_light') AND f.object_id IS NULL AND h.object_raw = ? "
        "  AND (f.object_source IS 'user_cleared') = ? "
        "ORDER BY f.id",
        (object_raw, int(cleared)),
    ).fetchall()


def nameless_frames(con, cleared=False):
    """Drążenie kubełka „bez nazwy w nagłówku" (P-D, D-PD-11): DOKŁADNIE JEDEN wiersz na klatkę,
    z celem writebacku (`present=1`) i jawną kardynalnością kopii. Predykat ZNAK W ZNAK ten sam,
    co licznik `review_queue` — który liczy `len()` tego wyniku (D-PD-10, jeden właściciel).

    ROZŁĄCZNY SAM ZE SOBĄ po `cleared` od R-S3-1 — bliźniaczo do kubełka RAW (S3) i z tego samego
    powodu: klatka, której nazwę ZDJĘTO ręką, wraca tu, bo predykat pyta o sam brak obiektu, a jej
    `object_raw` jest NULL-em (nazwa przyszła z regionu/ścieżki/xref, nie z karty). Do rozszczepienia
    siedziała w jednym wierszu z klatką nigdy nietkniętą — czyli WERDYKT CZŁOWIEKA wyglądał jak brak
    wiedzy. Droga naprawy jest ta sama dla obu połówek (karta `OBJECT` do PLIKU) i to ONA gasi
    nagrobek (`writeback.py:704-705`), więc rozszczepienie jest o WIDOK, nie o mechanizm.

    RÓWNOŚĆ Z KOTWICĄ RDZENIA po rozszczepieniu: kotwicą jest SUMA OBU drążeń —
    `len(…()) + len(…(cleared=True)) == resolver.nameless_lights`. Sam człon domyślny NIE równa się,
    bo `nameless_lights` pyta o brak obiektu i nagrobki liczy (ta sama lekcja, co przy RAW-ach:
    dopóki żaden nagrobek nie istniał, stary pin świecił zielono, czyli pinował NIEOBECNOŚĆ
    populacji zamiast równości).

    ŚWIADOMY FORMATU (2026-08-01): `NO_OBJECT_CARD_FILETYPES` odpada, bo ta lista jest WEJŚCIEM
    DIALOGU zapisu — RAW-a `macro.resolve_target` i tak odrzuca (read-only), więc bez tego warunku
    okno „Napraw nagłówek…" otwierałoby się z listą, której KAŻDA pozycja jest pominięta. Populacja
    nie znika z kolejki: liczy ją własny kubełek (`resolver.nameless_raw_lights`).

    ŚWIADOMY ŹRÓDŁA od I-2b (D-P-I-5): `kind='light'` zamiast `IN ('light','master_light')` —
    gotowe stacki mają WŁASNE drążenie (`nameless_stack_frames`), bo są własnym kubełkiem kolejki.
    Od D-0802-1 (2026-08-02) nie chodzi już o to, że writeback ich nie tyka — tyka — tylko o to,
    że dwa kubełki muszą zostać rozłączne, inaczej partycja policzyłaby stacki dwa razy.

    Cel przez `l.id = (SELECT MIN(id) … present = 1)`, NIE przez `JOIN … present = 1`:
      - naiwny JOIN ZMIENIŁby predykat — klatka bezimienna BEZ obecnej kopii wypadłaby z licznika,
        choć zostaje w `review_frame_ids` i w inwariancie partycji `review_queue`;
      - naiwny LEFT JOIN po `present=1` ZAWYŻAŁby licznik przy dwóch obecnych kopiach.
    `n_present` (podzapytanie) jest więc KOLUMNĄ, nie predykatem: `0` i `>1` idą do dialogu jako
    pominięte Z POWODEM — tym samym, którego użyje makro. Cel jest TEN SAM co makra: read-model
    bierze `MIN(id)` wśród obecnych, `macro.resolve_target` bierze `present[0]` z `ORDER BY f.id,
    l.id` (`writeback_frame_targets`) — ta sama lokacja, nie „podobna".

    Kolumny NIE są ozdobą: panel klatek dialogu jedzie `_fill_frames`, który czyta `sha1_data`
    bezwarunkowo i woła `telescope_label(row)` (kontrakt `IndexError` przy braku kolumny) — wąski
    SELECT wywaliłby dialog przy pierwszym renderze. `f_ratio_nominal`/`focal_nominal` świadomie
    POZA (NARROW: `_fill_frames` ich nie czyta).

    `ORDER BY l.path, f.id` daje stabilność i wypycha `n_present=0` na górę (NULL sortuje się
    pierwszy); grupowanie po folderze robi wołający SŁOWNIKIEM (kolejność pierwszego wystąpienia),
    bo porządek po PEŁNEJ ścieżce przeplata katalog z podkatalogiem. Zwraca: frame_id, sha1_data,
    filetype, date_obs, telescope_label, telescop_canon, camera_model, location_id, path, n_present."""
    return con.execute(
        "SELECT f.id AS frame_id, f.sha1_data, f.filetype, h.date_obs, "
        "       t.label AS telescope_label, t.telescop_canon, "
        "       cam.model_canon AS camera_model, "
        "       l.id AS location_id, l.path, "
        "       (SELECT COUNT(*) FROM location WHERE frame_id = f.id AND present = 1) AS n_present "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN telescope t ON t.id = tc.canon_id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "LEFT JOIN location l ON l.id = (SELECT MIN(id) FROM location "
        "                                WHERE frame_id = f.id AND present = 1) "
        "WHERE f.kind = 'light' AND f.object_id IS NULL "
        "  AND f.superseded_by IS NULL "
        "  AND f.retired_at IS NULL "
        "  AND h.object_raw IS NULL "
        "  AND f.filetype NOT IN (SELECT value FROM json_each(?)) "
        "  AND (f.object_source IS 'user_cleared') = ? "
        "ORDER BY l.path, f.id",
        (json.dumps(list(NO_OBJECT_CARD_FILETYPES)), int(cleared))
    ).fetchall()


def nameless_raw_frames(con, cleared=False):
    """Drążenie kubełka „bez nazwy, format bez karty (RAW)" (S4) — bliźniak `nameless_frames`
    o jednym słowie różnicy: `filetype IN NO_OBJECT_CARD_FILETYPES` zamiast `NOT IN`.

    Do S4 ten kubełek był wierszem INFORMACYJNYM: droga naprawy istniała (ręczne „Przypisz
    obiekt…"), ale wisiała przy pozycji `object_raw`, a RAW `object_raw` NIE MA z definicji —
    czyli mechanizm był bez powierzchni. Drążenie jest połową tej powierzchni: bez niego pozycja
    zapala przycisk, który zapisze grupę, której user nigdy nie zobaczył.

    ROZŁĄCZNY z `nameless_frames` po FORMACIE i z `nameless_stack_frames` po `kind` — partycja
    `review_queue` liczy wszystkie trzy i zachodzące zbiory rozspójniłyby ją o własną liczbę.
    Od S3 rozłączny TAKŻE SAM ZE SOBĄ po `cleared`: klatka z nagrobkiem wraca do tego kubełka
    (predykat pyta o sam brak obiektu), a wyglądała identycznie jak nietknięta — przy akcji, która
    ją cicho pomijała. Dwie liczby ROZŁĄCZNE, nie kubełek i jego podzbiór: partycja sumuje obie.

    RÓWNOŚĆ Z KOTWICĄ RDZENIA (bramka 13) PO ROZSZCZEPIENIU: kotwicą jest SUMA OBU drążeń —
    `len(…()) + len(…(cleared=True)) == resolver.nameless_raw_lights`. Sam człon domyślny kotwicy
    NIE równa się, bo `nameless_raw_lights` pyta o brak obiektu i nagrobki liczy. Zapis „`len()`
    tego wyniku == kotwica" był prawdą do S3 i przestał nią być w tym samym commicie, który
    dołożył parametr — dopóki żaden nagrobek nie istniał, stary pin świecił zielono, czyli pinował
    NIEOBECNOŚĆ populacji zamiast równości. Dwa literały, bo warstwy są dwie i zależność idzie
    w jedną stronę — jak przy `nameless_frames`.

    Kolumny, cel przez `MIN(id) … present = 1` i `ORDER BY` — jak w `nameless_frames` (ten sam
    panel `_fill_frames` je czyta; wąski SELECT wywala render na pierwszym wierszu). Cel jest tu
    MARTWĄ literą dla writebacku (RAW jest read-only — `macro.resolve_target` go odrzuca), ale
    kolumna `path` niesie folder, po którym user rozpoznaje grupę na ekranie. Zwraca: frame_id,
    sha1_data, filetype, date_obs, telescope_label, telescop_canon, camera_model, location_id,
    path, n_present."""
    return con.execute(
        "SELECT f.id AS frame_id, f.sha1_data, f.filetype, h.date_obs, "
        "       t.label AS telescope_label, t.telescop_canon, "
        "       cam.model_canon AS camera_model, "
        "       l.id AS location_id, l.path, "
        "       (SELECT COUNT(*) FROM location WHERE frame_id = f.id AND present = 1) AS n_present "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN telescope t ON t.id = tc.canon_id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "LEFT JOIN location l ON l.id = (SELECT MIN(id) FROM location "
        "                                WHERE frame_id = f.id AND present = 1) "
        "WHERE f.kind = 'light' AND f.object_id IS NULL "
        "  AND f.superseded_by IS NULL "
        "  AND f.retired_at IS NULL "
        "  AND h.object_raw IS NULL "
        "  AND f.filetype IN (SELECT value FROM json_each(?)) "
        "  AND (f.object_source IS 'user_cleared') = ? "
        "ORDER BY l.path, f.id",
        (json.dumps(list(NO_OBJECT_CARD_FILETYPES)), int(cleared))
    ).fetchall()


def config_review_frames(con):
    """Drążenie kubełka „bez zestawu (teleskop × kamera)" (R1, #DR2) — jeden wiersz na klatkę.

    Predykat jest LUSTREM `resolver.review_state.no_config` znak w znak: `config_id IS NULL`
    + rodzaj NA OSI teleskopu (kalibracja ma NULL jako stan docelowy) + `EXISTS(header)` (grouper
    iteruje `frame JOIN header`, więc klatka bez zeznania nigdy nie jest flagowana). Dwa literały,
    bo warstwy są dwie i zależność idzie w jedną stronę — a RÓWNOŚĆ PINUJE TEST, dokładnie jak przy
    kotwicy `nameless_raw_lights` (bramka 13). Kopiowanie zbioru rodzajów jest zakazane: idzie
    przez `json_each(?)` od jedynego właściciela (`grouper.NO_TELESCOPE_KINDS`).

    KOLUMNA `telescop` NIE JEST OZDOBĄ — to ona pokazuje, DLACZEGO automat nie umiał: dla RAW-a
    z lustrzanki nagłówek albo milczy (zdjęcie przez teleskop), albo niesie nazwę OBIEKTYWU (E3-3),
    a użytkownik musi widzieć różnicę, zanim wskaże sprzęt. Reszta kolumn jak w `nameless_frames`
    (ten sam panel `_fill_frames` je czyta; wąski SELECT wywala render na pierwszym wierszu).

    Klatka BEZ KOPII zostaje w wyniku z `path IS NULL` (LEFT JOIN) — bo brak obecnej kopii NIE jest
    sam w sobie powodem zniknięcia z kubełka (klatka zniknięta z dysku dalej czeka na decyzję).
    WYJĄTKIEM jest klatka ZASTĄPIONA (`superseded_by IS NOT NULL`): tam robotę przejęła następczyni,
    a stara jest zapisem historii — dlatego wypada z kubełka i ma własną perspektywę „Zastąpione".
    Zmierzone 2026-08-09: bez tego warunku sierota 15958 siedziała w kubełku sprzętu (424 zamiast
    423) i w kubełku RAW-ów jako JEDYNA jego pozycja, oferując robotę na pliku, którego nie ma.
    Zwraca: frame_id,
    sha1_data, filetype, kind, date_obs, telescope_label, telescop_canon, camera_model, camera_id,
    telescop, location_id, path, n_present."""
    return con.execute(
        "SELECT f.id AS frame_id, f.sha1_data, f.filetype, f.kind, h.date_obs, "
        "       t.label AS telescope_label, t.telescop_canon, "
        "       cam.model_canon AS camera_model, f.camera_id, h.telescop, "
        "       l.id AS location_id, l.path, "
        "       (SELECT COUNT(*) FROM location WHERE frame_id = f.id AND present = 1) AS n_present "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN telescope t ON t.id = tc.canon_id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "LEFT JOIN location l ON l.id = (SELECT MIN(id) FROM location "
        "                                WHERE frame_id = f.id AND present = 1) "
        "WHERE f.config_id IS NULL "
        "  AND f.superseded_by IS NULL "
        "  AND f.retired_at IS NULL "
        "  AND f.kind NOT IN (SELECT value FROM json_each(?)) "
        "ORDER BY l.path, f.id",
        (json.dumps(sorted(NO_TELESCOPE_KINDS)),)
    ).fetchall()


def config_by_hand_frames(con):
    """Bliźniak `config_review_frames` po drugiej stronie GESTU: klatki, którym zestaw wskazała RĘKA.

    Ten read-model jest DROGĄ POWROTNĄ, nie ozdobą (bramka pakietu 3a, zarzut 1). Kubełek sprzętu
    pyta o `config_id IS NULL`, więc klatka po geście z niego WYPADA — i do R1 nie było jak jej
    już dotknąć: automat odmawia (guard lepkości), a jedyne okno otwiera się z kubełka, w którym
    jej nie ma. Pierwsza pomyłka ręki byłaby wieczna. Osobny wiersz kolejki i osobna lista są tu
    dokładnie tą samą figurą, co „cofnięte ręką" na osi obiektu (S3/R-S3-1): populacja rozłączna
    z kubełkiem, ta sama droga naprawy, własny licznik.

    Kolumny jak w `config_review_frames` — obie listy jadą przez ten sam panel `_fill_frames`.

    KLATKA ZASTĄPIONA WYPADA TAK SAMO JAK U PARY (bramka pakietu 0810, zarzut 2). Para dostała ten
    warunek 0809 z powodem zmierzonym na sierocie 15958; ten wiersz go nie dostał, choć `transfer_facts`
    kopiuje config na następczynię i NIE zeruje `config_source` poprzedniczki — obie tożsamości niosą
    więc wskazanie ręki. Bez warunku kubełek liczył JEDEN plik dwa razy, a okno w trybie ZMIANY
    oferowało gest na tożsamości, której roboty nikt już nie potrzebuje (zapis szedłby na martwą
    klatkę). Populacja dziś **0** — to tripwir, nie naprawa objawu; wchodzi, bo diff i tak dotknął
    tego SELECT-a."""
    return con.execute(
        "SELECT f.id AS frame_id, f.sha1_data, f.filetype, f.kind, h.date_obs, "
        "       t.label AS telescope_label, t.telescop_canon, "
        "       cam.model_canon AS camera_model, f.camera_id, h.telescop, "
        "       l.id AS location_id, l.path, "
        "       (SELECT COUNT(*) FROM location WHERE frame_id = f.id AND present = 1) AS n_present "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN telescope t ON t.id = tc.canon_id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "LEFT JOIN location l ON l.id = (SELECT MIN(id) FROM location "
        "                                WHERE frame_id = f.id AND present = 1) "
        "WHERE f.config_source IS NOT NULL "
        "  AND f.superseded_by IS NULL "
        "  AND f.retired_at IS NULL "
        "ORDER BY l.path, f.id").fetchall()


def _grupuj_po_folderze_i_kamerze(rows):
    """Wspólny składacz grup **folder × kamera** dla obu list osi sprzętu (SPOT).

    Jedna funkcja, bo obie odpowiadają na to samo pytanie („co jest jednostką gestu"), a dwie kopie
    rozjechałyby się przy pierwszej zmianie klucza — a klucz jest tu kontraktem DDL, nie gustem.

    `other_kinds` = RODZAJE ODBIEGAJĄCE OD ŚWIATŁA w grupie, `[(kind, n)]` malejąco (R1-3). Kubełek
    sprzętu odsiewa wyłącznie `NO_TELESCOPE_KINDS` (dark/bias), więc trafia do niego każdy inny
    rodzaj — dziś na archiwum jest to jeden XISF-owy masterflat z niezmapowanym `IMAGETYP`
    (`kind='unknown'`, 1 z 423). Gest go PRZYJMIE i tak ma być (oś opisuje optykę, nie rodzaj
    klatki), ale okno musi ten fakt nieść: bez niego folder z jedną klatką wygląda identycznie
    jak RAW z lustrzanki, o który to okno pyta. `light` jest tłem kubełka i dlatego go nie ma
    na liście — człon ma być SYGNAŁEM odchylenia, a nie etykietą na wszystkich 36 grupach."""
    grupy = {}
    for r in rows:
        folder = os.path.dirname(r["path"]) if r["path"] else None
        klucz = (folder, r["camera_id"])
        g = grupy.get(klucz)
        if g is None:
            g = grupy[klucz] = {"folder": folder, "camera_id": r["camera_id"],
                                "camera_model": r["camera_model"], "telescop": r["telescop"],
                                "telescope_label": r["telescope_label"],
                                "n_frames": 0, "frame_ids": [], "_kinds": {}}
        elif g["telescop"] != r["telescop"]:
            g["telescop"] = None                 # folder z dwoma zeznaniami nie ma jednego świadka
        if r["kind"] != "light":
            g["_kinds"][r["kind"]] = g["_kinds"].get(r["kind"], 0) + 1
        g["n_frames"] += 1
        g["frame_ids"].append(r["frame_id"])
    for g in grupy.values():
        # LICZBA PRZY RODZAJU, NIE SAM RODZAJ: grupa bywa mieszana (folder × kamera nie zna
        # rodzaju), więc „rodzaj: unknown" bez liczby twierdziłby, że taka jest CAŁA grupa.
        g["other_kinds"] = sorted(g.pop("_kinds").items(), key=lambda kn: (-kn[1], kn[0]))
    return list(grupy.values())


def config_by_hand_groups(con):
    """Grupy folder × kamera dla klatek z zestawem od RĘKI — wejście okna w trybie ZMIANY."""
    return _grupuj_po_folderze_i_kamerze(config_by_hand_frames(con))


def config_review_groups(con):
    """Kubełek sprzętu pogrupowany w JEDNOSTKI GESTU: **folder × kamera** (D-DR-3).

    Nie jest to drugi predykat, tylko PROJEKCJA `config_review_frames` — grupowanie robi Python,
    bo folder to `dirname(path)`, którego SQLite nie ma, a drugi SELECT dałby dwie odpowiedzi na
    jedno pytanie (ta sama reguła, co przy grupowaniu po folderze w oknie „Napraw nagłówek…").

    KAMERA JEST CZĘŚCIĄ KLUCZA, nie ozdobą wiersza: `config` niesie DOKŁADNIE JEDNĄ kamerę
    (`UNIQUE(telescope_id, camera_id)`), a zmierzone 2 z 36 folderów archiwum mają dwa korpusy
    (`NGC5194\\portable`, `NGC6853\\portable`). Grupa „folder" bez kamery obiecywałaby jeden gest
    tam, gdzie muszą być dwa configi.

    KLATKA BEZ KOPII trafia do grupy o `folder=None` — i to jest jedyna grupa, której nazwy nie ma
    na dysku. Nie znika, bo licznik kubełka ją liczy, więc lista, która ją gubi, kłamałaby
    o zakresie gestu. ⚠ MOWA O KLATCE ZNIKNIĘTEJ, NIE O ZASTĄPIONEJ — dawny zapis wskazywał tu
    „sierotę po podmianie pliku" i przestał być prawdą 0809 (`d3cbeb9`): zastąpiona wypadła
    z kubełka razem z całą kolejką, bo jej robotę przejęła następczyni.

    `telescop` grupy = zeznanie PIERWSZEJ klatki, gdy wszystkie mówią to samo; różne zeznania
    w jednym folderze dają `None` (grupa nie ma jednego świadka i nie ma udawać, że ma).

    Zwraca listę dictów: {folder, camera_id, camera_model, telescop, telescope_label, n_frames,
    frame_ids}."""
    return _grupuj_po_folderze_i_kamerze(config_review_frames(con))


def nameless_stack_frames(con, cleared=False):
    """Drążenie kubełka „gotowe stosy bez nazwy" (D-0802-1, P6d) — bliźniak `nameless_frames`
    o jednym słowie różnicy: `kind='master_light'`.

    ROZŁĄCZNY SAM ZE SOBĄ po `cleared` od R-S3-1, jak oba kubełki wyżej. Ta droga nie jest
    hipotetyczna: D-OW-7 dało gestowi osi obiektu dostęp do GOTOWEGO OBRAZU, więc cofnięcie na
    stosie jest osiągalne jednym kliknięciem — a bez rozszczepienia stos z werdyktem ręki wracał
    do wspólnego wiersza nieodróżnialny od stosu, o którym nikt nigdy nie decydował. Kotwica
    rdzenia (`resolver.nameless_stacks`) równa się SUMIE obu drążeń, nie samemu pierwszemu.

    Do 2026-08-02 ten kubełek był INFORMACYJNY, bo pisarz XISF nie umiał dopisać karty (D-X-12),
    więc okno „Napraw nagłówek…" otwierałoby się z listą, której KAŻDA pozycja jest pominięta —
    ta sama patologia, dla której RAW-y są wycięte z `nameless_frames`. P6d nauczyła pisarza
    wstawiać kartę (`scan.build_fits_keyword_element`), więc droga naprawy istnieje i kubełek
    dostał drążenie.

    ROZŁĄCZNY z `nameless_frames` po `kind` — partycja `review_queue` liczy oba i zsumowanie
    zachodzących zbiorów rozspójniłoby ją dokładnie o liczbę stosów.

    `NO_OBJECT_CARD_FILETYPES` świadomie POZA predykatem, inaczej niż u lightów: RAW-owy
    `master_light` nie ma jak powstać (`kind_from_path` zna tylko light/dark/flat/bias, a droga
    „Stosy" powołuje rodzaj z `IMAGETYP`), więc warunek byłby martwą literą udającą bramkę.

    Kolumny, cel przez `MIN(id) … present = 1` i `ORDER BY` — jak w `nameless_frames` (ten sam
    panel `_fill_frames` je czyta). Zwraca: frame_id, sha1_data, filetype, kind, date_obs,
    telescope_label, telescop_canon, camera_model, location_id, path, n_present.

    `kind` wchodzi do WYNIKU, choć jest też warunkiem — po to, żeby panel umiał odróżnić stos od
    klatki nieba i pokazać przy stosie FOLDER (firsthand 0808: nazwy plików WBPP nie rozróżniają
    18 wierszy tego kubełka). Warunek w `WHERE` mówi, KOGO wybieramy; kolumna mówi wołającemu,
    CO dostał — i tylko ta druga jest kontraktem dla powierzchni."""
    return con.execute(
        "SELECT f.id AS frame_id, f.sha1_data, f.filetype, f.kind, h.date_obs, "
        "       t.label AS telescope_label, t.telescop_canon, "
        "       cam.model_canon AS camera_model, "
        "       l.id AS location_id, l.path, "
        "       (SELECT COUNT(*) FROM location WHERE frame_id = f.id AND present = 1) AS n_present "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN telescope t ON t.id = tc.canon_id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "LEFT JOIN location l ON l.id = (SELECT MIN(id) FROM location "
        "                                WHERE frame_id = f.id AND present = 1) "
        "WHERE f.kind = 'master_light' AND f.object_id IS NULL "
        "  AND f.superseded_by IS NULL "
        "  AND f.retired_at IS NULL "
        "  AND h.object_raw IS NULL "
        "  AND (f.object_source IS 'user_cleared') = ? "
        "ORDER BY l.path, f.id",
        (int(cleared),)
    ).fetchall()


def path_proposal_frames(con, frame_ids):
    """Klatki propozycji ze ŚCIEŻKI pod panel drążenia (S2) — DEKORACJA podanych `frame_ids`,
    nie drugi predykat.

    Świadomie BEZ własnego `WHERE` na populacji: predykat szczebla ma JEDNEGO właściciela
    (`resolver.path_proposals`) i to on rozstrzyga, która klatka jest kandydatem. Powtórzenie go
    tutaj dałoby dwie odpowiedzi na jedno pytanie — dokładnie ta klasa, którą S2 zamyka po stronie
    reguły ścieżki.

    Kolumny jak w `nameless_frames` — ten sam panel (`_fill_frames`) je czyta, a jego kontrakt
    (`sha1_data`, `telescope_label(row)`) wywala się przy wąskim SELECT-cie. Zwraca: frame_id,
    sha1_data, filetype, date_obs, telescope_label, telescop_canon, camera_model, location_id,
    path, n_present."""
    return con.execute(
        "SELECT f.id AS frame_id, f.sha1_data, f.filetype, h.date_obs, "
        "       t.label AS telescope_label, t.telescop_canon, "
        "       cam.model_canon AS camera_model, "
        "       l.id AS location_id, l.path, "
        "       (SELECT COUNT(*) FROM location WHERE frame_id = f.id AND present = 1) AS n_present "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN telescope t ON t.id = tc.canon_id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "LEFT JOIN location l ON l.id = (SELECT MIN(id) FROM location "
        "                                WHERE frame_id = f.id AND present = 1) "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "ORDER BY l.path, f.id",
        (json.dumps([int(i) for i in frame_ids]),)
    ).fetchall()


def object_id_by_canon(con, canon):
    """`object.id` dla kanonu albo None — TĄ SAMĄ frazą, której użyje zapis (`repo.user_assign_object`).

    Dialog przypisania nie może brać id z `library_objects`: tamten read-model ma `JOIN frame`, więc
    obiekt BEZ klatek (po odpięciu, po cofnięciu, po zasianiu z assetu) dla niego nie istnieje. Wtedy
    pre-check konfliktu aliasu porównywał `alias.object_id` z `None` i meldował konflikt tam, gdzie
    klinga zapisałaby bez mrugnięcia — komunikat kłamiący o przyczynie, przy poprawnym kluczu."""
    row = con.execute("SELECT id FROM object WHERE canon = ?", (canon,)).fetchone()
    return row["id"] if row is not None else None


def alias_target(con, alias_norm):
    """Pre-check konfliktu aliasu w dialogu przypisania (#8, P4): `object_id`, na który wskazuje
    `alias_norm`, albo None (alias nieznany — zapis go utworzy). Ostateczny guard i tak siedzi
    w `repo.user_assign_object` (w `_immediate`, TOCTOU) — to czytnik UX, nie bramka."""
    row = con.execute(
        "SELECT object_id FROM object_alias WHERE alias_norm = ?", (alias_norm,)).fetchone()
    return row["object_id"] if row is not None else None


def unreadable_copies(con):
    """Drążenie kubełka `unreadable` (#13, Z6/P4): DOKŁADNE KOPIE (location) z markerem
    `unreadable_since` — nie klatki (klatka z 2 oznaczonymi kopiami = 2 wiersze). `present`
    pokazane per kopia: oznaczona kopia może być `present=0` (znikła po oznaczeniu — forward-guard
    #13) i to MA być widoczne. `sha1_data` = kontekst tożsamości klatki (UI skraca do 12).
    ORDER: najnowsze oznaczenie na górze, potem ścieżka. Zwraca: frame_id, sha1_data, volume,
    path, present, unreadable_since, reason.

    `reason` (Z6) = OSTATNI `event(frame.review)` TEJ kopii: stan mówi, KTÓRA kopia wypadła,
    dziennik — CZEGO nie da się przeczytać (żywa pf4: „ParseError: not well-formed…"). Atrybucja
    idzie PARĄ (`target = 'sha1:'||sha1_data` ORAZ `payload.path == location.path`), bo target
    jest per KLATKA, a klatka bywa wielokopiowa — po samym sha1 obie kopie dostałyby cudzy powód.
    BEZ filtra po prefiksie: `frame.review` emitują DWA miejsca (`flag_frame_review` przy miękkim
    lądowaniu W1 i `refresh_location_unreadable` przy markerze) i oba opisują tę samą niemożność
    odczytu, więc rozstrzyga ŚWIEŻOŚĆ, nie autor. Kopia przemianowana po oznaczeniu zostawia
    w payloadzie STARĄ ścieżkę → `reason IS NULL` i powierzchnia pokazuje „—": brak dowodu jest
    uczciwszy niż powód pożyczony od innej kopii."""
    return con.execute(
        "SELECT l.frame_id, f.sha1_data, l.volume, l.path, l.present, l.unreadable_since, "
        "       (SELECT e.reason FROM event e "
        "         WHERE e.verb = 'frame.review' AND e.target = 'sha1:' || f.sha1_data "
        "           AND json_extract(e.payload, '$.path') = l.path "
        "         ORDER BY e.id DESC LIMIT 1) AS reason "
        "FROM location l JOIN frame f ON f.id = l.frame_id "
        "WHERE l.unreadable_since IS NOT NULL "
        "ORDER BY l.unreadable_since DESC, l.path"
    ).fetchall()


def park_overview(con):
    """Przegląd parku (T4/T5): kanoniczne teleskopy z licznikiem lightów, ostatnią klatką i stanem
    `in_park` (1 = w parku, 0 = historyczny, NULL = user się nie wypowiedział).

    JEDEN właściciel literału (SPOT): ten sam wiersz karmi CLI `horreum park` i dialog „Park…"
    ekranu planera — dwie powierzchnie tej samej decyzji nie mają prawa liczyć lightów inaczej.
    Kolejność `lights DESC` jest kolejnością SPRZĘTU, nie alfabetu: `sky.park` sortuje raport
    alfabetycznie (determinizm), ale człowiek szuka swojego głównego teleskopu na górze.
    Zwraca wiersze: id, telescop_canon, label, in_park, lights, last_seen — OBIE kolumny nazwy, bo
    wiersz musi przejść przez `telescope_label` (dialog „Park…" pokazuje nazwę USERA), a `canon`
    zostaje tożsamością zestawu i tokenem CLI `horreum park --add`."""
    return con.execute(
        "SELECT t.id, t.telescop_canon, t.label, t.in_park, "
        "  (SELECT COUNT(*) FROM frame f JOIN config c ON c.id = f.config_id "
        "   WHERE c.telescope_id = t.id AND f.kind = 'light') AS lights, "
        "  (SELECT MAX(h.date_obs) FROM frame f JOIN config c ON c.id = f.config_id "
        "   JOIN header h ON h.frame_id = f.id "
        "   WHERE c.telescope_id = t.id AND f.kind = 'light') AS last_seen "
        "FROM telescope t WHERE t.merged_into IS NULL ORDER BY lights DESC"
    ).fetchall()


def object_ids_for_canons(con, canons):
    """`object_id` dla listy kanonów archiwum (most planer → grid, D-0731-7). Zwraca pary
    `(id, canon)` — facet Obiekt gridu chce OBU (etykieta chipa bierze kanon, filtr id).

    Wiele kanonów, bo jeden cel katalogu bywa w archiwum pod kilkoma nazwami naraz (`IC410`
    ORAZ `LBN807`, D-T2-d) — most ma pokazać SUMĘ klatek celu, nie jedną z nazw. Lista idzie
    przez `json_each(?)` (literał stały, jeden parametr — reguła nagłówka pliku); kanon nieznany
    bazie po prostu nie ma wiersza, bo „cel bez klatek" to stan, nie błąd."""
    return con.execute(
        "SELECT id, canon FROM object WHERE canon IN (SELECT value FROM json_each(?)) "
        "ORDER BY canon",
        (json.dumps(list(canons)),),
    ).fetchall()


def telescope_facets(con):
    """Distinct KANONICZNE teleskopy (`merged_into IS NULL`) do kontrolki filtra — żeby filtr pokazywał
    realnie istniejące osie. `telescop_canon` służy za etykietę zastępczą, gdy `label` pusty (teleskop
    jeszcze nienazwany — proposed). Zwraca: id, telescop_canon, label, f_ratio_nominal, focal_nominal."""
    return con.execute(
        "SELECT id, telescop_canon, label, f_ratio_nominal, focal_nominal FROM telescope "
        "WHERE merged_into IS NULL ORDER BY id"
    ).fetchall()


def filter_facets(con):
    """Distinct realnie występujące `filter_canon` do kontrolki filtra. Zwraca: filter_canon."""
    return con.execute(
        "SELECT DISTINCT filter_canon FROM frame WHERE filter_canon IS NOT NULL ORDER BY filter_canon"
    ).fetchall()


# ============================================================ GRID „Klatki" (PLAN_gui_grid §3, read-only)
# Read-model gridu nad EAV `cards`. Silnik filtra (`horreum.filter_engine`) woła `leaf_frame_ids`
# (predykat-liść → zbiór) i `all_frame_ids` (uniwersum); pivot (`horreum.pivot`) dostaje wiersze z
# `cards_pivot`; kolumny bazowe z `base_rows`. Każdy predykat-liść = OSOBNY literał w gałęzi `if`
# (skill ast-write-gate-read-model-sql-literals) — NIGDY f-string. `kind` wybiera literał; wartości `?`.


def all_frame_ids(con):
    """UNIWERSUM filtra = WSZYSTKIE frame (w tym BEZ kart i zniknięte present=0 — F1). Baza dla
    `not_exists` i `filter=None`. NIGDY z `DISTINCT frame_id FROM cards`: do P6a gubiłoby cały XISF,
    dziś gubi klatki bez czytelnego zeznania (szkielety, kopie nieczytelne) — a te są w bazie
    właśnie po to, żeby je było widać. Zwraca set[int]."""
    return {int(r[0]) for r in con.execute("SELECT id FROM frame").fetchall()}


def leaf_frame_ids(con, kind, keyword, p1=None, p2=None):
    """Predykat-liść filtra → set[frame_id]. `kind` (z `filter_engine`) wybiera OSOBNY literał; keyword i
    wartości wiązane `?`. Numeryczne po `value_num` (wiersze NULL wypadają same); tekstowe po `value_raw`;
    liczbo-podobne trafiają oba; `like` po `value_raw LIKE ? ESCAPE`. Semantyka 1:1 z dawcą `query.py`.
    Liście RELACYJNE `rel_*` (F4, facety — PLAN_ux_redesign §5) chodzą po frame/config/header zamiast
    cards; `keyword` dla nich nieużywany (silnik podaje None). `rel_telescope` = canon_id kanonicznego
    teleskopu (scaleni członkowie rolują się pod kanon przez `telescope_canonical`, jak
    `active_telescopes`). `rel_night` = zakres `[p1, p2)` na `header.date_obs` — OBA parametry pełne
    datetime (granice liczy `filter_engine.night_bounds`); klatka bez header/date_obs nie wpada."""
    if kind == "rel_object":
        cur = con.execute("SELECT id FROM frame WHERE object_id = ?", (p1,))
    elif kind == "rel_filter":
        cur = con.execute("SELECT id FROM frame WHERE filter_canon = ?", (p1,))
    elif kind == "rel_kind":
        cur = con.execute("SELECT id FROM frame WHERE kind = ?", (p1,))
    elif kind == "rel_telescope":
        cur = con.execute(
            "SELECT f.id FROM frame f "
            "JOIN config c ON c.id = f.config_id "
            "JOIN telescope_canonical tc ON tc.id = c.telescope_id "
            "WHERE tc.canon_id = ?",
            (p1,),
        )
    elif kind == "rel_night":
        cur = con.execute(
            "SELECT f.id FROM frame f JOIN header h ON h.frame_id = f.id "
            "WHERE h.date_obs >= ? AND h.date_obs < ?",
            (p1, p2),
        )
    elif kind == "exists":
        cur = con.execute("SELECT frame_id FROM cards WHERE keyword = ?", (keyword,))
    elif kind == "num_gt":
        cur = con.execute("SELECT frame_id FROM cards WHERE keyword = ? AND value_num > ?", (keyword, p1))
    elif kind == "num_lt":
        cur = con.execute("SELECT frame_id FROM cards WHERE keyword = ? AND value_num < ?", (keyword, p1))
    elif kind == "num_ge":
        cur = con.execute("SELECT frame_id FROM cards WHERE keyword = ? AND value_num >= ?", (keyword, p1))
    elif kind == "num_le":
        cur = con.execute("SELECT frame_id FROM cards WHERE keyword = ? AND value_num <= ?", (keyword, p1))
    elif kind == "eq_raw":
        cur = con.execute("SELECT frame_id FROM cards WHERE keyword = ? AND value_raw = ?", (keyword, p1))
    elif kind == "ne_raw":
        cur = con.execute("SELECT frame_id FROM cards WHERE keyword = ? AND value_raw <> ?", (keyword, p1))
    elif kind == "eq_rawnum":
        cur = con.execute(
            "SELECT frame_id FROM cards WHERE keyword = ? AND (value_raw = ? OR value_num = ?)",
            (keyword, p1, p2),
        )
    elif kind == "ne_rawnum":
        cur = con.execute(
            "SELECT frame_id FROM cards "
            "WHERE keyword = ? AND value_raw <> ? AND (value_num IS NULL OR value_num <> ?)",
            (keyword, p1, p2),
        )
    elif kind == "like":
        cur = con.execute(
            "SELECT frame_id FROM cards WHERE keyword = ? AND value_raw LIKE ? ESCAPE '\\'", (keyword, p1)
        )
    else:
        raise ValueError(f"nieznany kind liścia: {kind!r}")
    return {int(r[0]) for r in cur.fetchall()}


def keyword_facets(con):
    """Distinct keywordy z `cards` + pokrycie (ile klatek ma daną kartę) do panelu Pól. Od P6a/P6b
    karty mają OBA formaty — XISF też (dawniej FITS-only, D-G), więc panel przestał być ślepy na
    mastery. Zwraca wiersze: keyword, n (COUNT DISTINCT frame_id), malejąco po pokryciu.
    UWAGA nazewnicza: „facets" tu = pokrycie KEYWORDÓW (kolumny gridu); listwa facetów F4 (Obiekt/Filtr/
    Rodzaj/Teleskop/Noc) to funkcje `facet_*` niżej — INNY fakt (F4R#9)."""
    return con.execute(
        "SELECT keyword, COUNT(DISTINCT frame_id) AS n FROM cards GROUP BY keyword ORDER BY n DESC, keyword"
    ).fetchall()


# ============================================================ LISTWA FACETÓW (F4, PLAN_ux_redesign §5)
# Liczniki wymiarów dla FacetRail: liczność wartości w podanym zbiorze frame_ids (SIBLING-SET —
# FramesView liczy zbiór per facet BEZ własnej grupy, F4R#1). Wszystko STAŁE LITERAŁY + `json_each(?)`.
# JAWNE predykaty NULL (F4R#10): żaden literał nie może urodzić fantomowego kubełka NULL (kubełki NULL
# świadomie poza v1 — kalibracja bez obiektu POPRAWNA, kind-aware).


def facet_objects(con, frame_ids):
    """Kubełki facetu Obiekt: kanoniczne obiekty w zbiorze + liczność. `object_id IS NULL` wypada
    JOIN-em (kalibracja bez obiektu — poprawnie poza listą). ORDER canon (lista pod szukajkę).
    Zwraca: id, canon, n."""
    return con.execute(
        "SELECT o.id, o.canon, COUNT(*) AS n "
        "FROM frame f JOIN object o ON o.id = f.object_id "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "GROUP BY o.id ORDER BY o.canon",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def object_alias_index(con):
    """Mapa `canon → {alias_norm}` dla szukajki facetu Obiekt (S3, obietnica §1).

    Kanon `LMC` nie zawiera ani jednej litery z „Large Magellanic Cloud", więc bez tej mapy szukajka
    jest ślepa dokładnie na klasę obiektów, dla której powstała ta paczka. Klucze są JUŻ znormalizowane
    (`object_alias.alias_norm` to `norm_alnum` z chwili zapisu), więc dopasowanie liczy się bez
    dotykania rdzenia po stronie widżetu — predykat mieszka w `facet_model.search_hit`.

    Zakres = CAŁA biblioteka aliasów, nie tylko obiekty widocznego zbioru: szukajka chowa wiersze
    listy, a ta lista przychodzi z sibling-setu — filtrowanie mapy po zbiorze nic by nie oszczędziło,
    a rozjechałoby dwa wejścia tego samego pytania. Zwraca dict[str, set[str]]."""
    idx = {}
    for canon, alias in con.execute(
            "SELECT o.canon AS canon, a.alias_norm AS alias_norm "
            "FROM object_alias a JOIN object o ON o.id = a.object_id").fetchall():
        idx.setdefault(canon, set()).add(alias)
    return idx


def recent_hand_objects(con, limit=5):
    """Kanony, którym RĘKA nadała obiekt ostatnio — skrót „ostatnio użyte" w menu Zbiorów (R-S2b-12).

    Zwraca listę Row(canon, catalog, kind), najświeższe pierwsze, najwyżej `limit` pozycji.

    ŹRÓDŁEM JEST DZIENNIK, I TO JEST TU WŁAŚCIWY WYBÓR — nie wyłom w regule „read-model ze STANU"
    (memory `horreum-review-queue-from-state`). Tamta reguła broni LICZNIKÓW pracy do zrobienia:
    `count(event)` rośnie z liczbą przebiegów, więc kubełek liczony ze zdarzeń kłamie. Tu pytanie
    brzmi inaczej — „co ostatnio robiłem" — i jest z natury pytaniem o historię, której stan tabel
    nie pamięta (`frame.object_id` mówi CO jest, nie KIEDY to wskazałem). Powtórzenia nie szkodzą:
    `GROUP BY` po obiekcie i `MAX(id)` czynią wynik idempotentnym wobec liczby zdarzeń.

    Filtr `object_source='user'` jest WĄSKI CELOWO: skrót ma podawać nazwy, które człowiek REALNIE
    wskazał palcem. `path` (potwierdzona propozycja ze ścieżki) i szczeble automatu odpadają — menu
    „ostatnio użyte" ma odtwarzać gest, a nie streszczać przebieg.

    Zapis ręki nie zna dziś `kind` przy istniejącym obiekcie (repo go nie INSERTuje), więc bierzemy
    go z tabeli `object` — skrót woła tę samą klingę co okno i musi mieć komplet pól.

    KOSZT ZMIERZONY, nie oszacowany (bramka pakietu, zarzut 6): pełny skan `event` bez indeksu na
    `verb`, na żywej `pf4` ze 137 059 zdarzeniami, wołany synchronicznie przy każdym otwarciu menu
    — **mediana 23 ms** (próg akceptacji 100 ms). Mieści się z zapasem, więc indeks byłby migracją
    bez odbiorcy. Wartość rośnie z dziennikiem, nie z archiwum: gdy `SELECT count(*) FROM event`
    przekroczy ~500 tys., zmierz ponownie i dopiero wtedy sięgaj po `CREATE INDEX event(verb, id)`.

    ZNA TYLKO NADANIA, nie cofnięcia — świadomie, ale to nie jest darmowe: kanon zdjęty przed
    chwilą („Cofnij przypisanie") zostaje na szczycie listy. Broni przed przypadkowym wskrzeszeniem
    dysklozura po stronie gestu (skrót oddaje ster oknu, gdy ma zgasić nagrobek — `grid.py`), a nie
    ten read-model; gdyby ta obrona kiedyś padła, TU jest drugie miejsce do naprawy."""
    return con.execute(
        "SELECT o.canon AS canon, o.catalog AS catalog, o.kind AS kind "
        "FROM event e JOIN object o ON o.id = json_extract(e.payload, '$.object_id') "
        "WHERE e.verb = 'object.assigned' "
        "  AND json_extract(e.payload, '$.object_source') = 'user' "
        "GROUP BY o.id ORDER BY MAX(e.id) DESC LIMIT ?",
        (int(limit),)).fetchall()


def facet_filters(con, frame_ids):
    """Kubełki facetu Filtr: `filter_canon` w zbiorze + liczność; JAWNIE `IS NOT NULL` (F4R#10).
    Zwraca: filter_canon, n (n DESC — najczęstsze na górze)."""
    return con.execute(
        "SELECT filter_canon, COUNT(*) AS n FROM frame "
        "WHERE filter_canon IS NOT NULL "
        "  AND id IN (SELECT value FROM json_each(?)) "
        "GROUP BY filter_canon ORDER BY n DESC, filter_canon",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def facet_kinds(con, frame_ids):
    """Kubełki facetu Rodzaj: `kind` w zbiorze + liczność (`kind` NOT NULL w schemacie — bez predykatu).
    Zwraca: kind, n (n DESC)."""
    return con.execute(
        "SELECT kind, COUNT(*) AS n FROM frame "
        "WHERE id IN (SELECT value FROM json_each(?)) "
        "GROUP BY kind ORDER BY n DESC, kind",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def facet_telescopes(con, frame_ids):
    """Kubełki facetu Teleskop: KANONICZNE teleskopy w zbiorze + liczność; klatki scalonych członków
    rolują się pod kanon (`telescope_canonical`, jak `active_telescopes`); frame bez configu wypada
    JOIN-em. Etykietę składa wołający JEDNYM `telescope_label(row)` z tego pliku (label→canon).
    Zwraca: id (canon_id), label, telescop_canon, n (n DESC)."""
    return con.execute(
        "SELECT t.id, t.label, t.telescop_canon, COUNT(*) AS n "
        "FROM frame f "
        "JOIN config c ON c.id = f.config_id "
        "JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "JOIN telescope t ON t.id = tc.canon_id "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "GROUP BY t.id ORDER BY n DESC, t.id",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def facet_nights(con, frame_ids):
    """Kubełki facetu Noc: noc = `date(date_obs, '-12 hours')` (D-UX-1) + liczność; JAWNIE
    `date_obs IS NOT NULL` (F4R#10). INWARIANT (F4R#6): `date_obs` = NAIWNE ISO z `T`, bez sufiksu
    strefy — sufiks `Z`/`+HH:MM` rozjechałby tę derywację (konwersja UTC) z liściem `rel_night`
    (porównanie leksykalne); spójność kubełek↔liść pinuje test własności. Zwraca: night, n
    (night DESC — najnowsze na górze)."""
    return con.execute(
        "SELECT date(h.date_obs, '-12 hours') AS night, COUNT(*) AS n "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE h.date_obs IS NOT NULL "
        "  AND f.id IN (SELECT value FROM json_each(?)) "
        "GROUP BY night ORDER BY night DESC",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def vanished_frame_ids(con):
    """Zbiór frame_id ZNIKNIĘTYCH: klatka MA lokacje, ale ŻADNEJ obecnej (perspektywa „Zniknięte",
    P5/#7). Guard `EXISTS` odróżnia „zniknęła" od „nigdy nie miała lokalizacji" (frame osierocony
    przez `rebind_location` — inny stan, inna robota). JEDEN właściciel predykatu: liczy z niego
    zarówno licznik Porządków (`tasks_state`), jak i trim gridu — jak `dup_frame_ids`. Zwraca set[int]."""
    return {int(r[0]) for r in con.execute(
        "SELECT f.id FROM frame f "
        "WHERE f.retired_at IS NULL "
        "  AND EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id) "
        "  AND NOT EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id AND l.present = 1)"
    ).fetchall()}


def missing_copy_frame_ids(con):
    """Zbiór frame_id, które MAJĄ żywą kopię i JEDNOCZEŚNIE znają adres martwy (perspektywa
    „Brakujące kopie", D-V-9a).

    CZWARTY STAN, nie odmiana trzech poprzednich - i różnica jest robocza, nie taksonomiczna:
      * ZNIKNIĘTA (`vanished_frame_ids`) - nie ma ANI JEDNEJ żywej kopii, robota jest DO ZROBIENIA;
      * DUPLIKAT (`dup_frame_ids`) - ma WIĘCEJ NIŻ JEDNĄ żywą kopię, czyli nadmiar, nie ubytek;
      * ZASTĄPIONA / WYCOFANA - historia, którą zamknął gest albo następczyni;
      * BRAKUJĄCA KOPIA - klatka żyje, ale jedna z jej kopii zniknęła. Nic nie zginęło i nic nie
        wymaga pośpiechu; to jest ślad po przeprowadzce albo po utraconej kopii zapasowej.

    DLACZEGO OSOBNA POWIERZCHNIA, A NIE SAM TOOLTIP (bramka pakietu D-V-9, soczewka repo F4).
    Do naprawy D-V-9 siatka pokazywała takim klatkom adres MARTWY - i robiła to po cichu, bo
    znacznik zniknięcia wymaga `n_present == 0`. Naprawa uciszyła kłamstwo, ale zostawiła fakt
    widoczny WYŁĄCZNIE pod kursorem: żaden kubełek, licznik ani filtr nie pokazywał go razem.
    Zmierzona populacja: **128 gotowych obrazów** - najcenniejsza część archiwum. Fakt o tylu
    klatkach, którego nie da się zobaczyć inaczej niż jeden po drugim, jest faktem schowanym.

    ⚠ TA LICZBA OPISUJE DZISIEJSZĄ POPULACJĘ, NIE PREDYKAT (bramka pakietu D-V-9a). Predykat jest
    świadomie KIND-AGNOSTYCZNY: utrata jednej z dwóch kopii jest tym samym faktem dla mastera,
    lighta i darka, więc zawężenie do `light/master_light` odebrałoby powierzchni część jej własnej
    treści. Że dziś wychodzi z niego 128 samych `master_light`, jest własnością ARCHIWUM po
    uporządkowaniu drzewa stosów - zmierzone kodem produkcyjnym na snapshocie żywej bazy
    2026-08-15 (`GROUP BY kind` → jeden wiersz). Gdy kiedyś wejdzie tu inny rodzaj, wiersz Porządków
    pokaże większą liczbę i będzie to POPRAWNE; nieprawdą stanie się wtedy słowo „obrazów"
    w tekście dla użytkownika, nie ten SQL.

    ⚠ ZAWĘŻENIE DO KLATEK ŻYWYCH JEST TREŚCIĄ PREDYKATU, nie ostrożnością. Bez `EXISTS(present=1)`
    zbiór wchłonąłby klatki ZNIKNIĘTE (wszystkie kopie martwe), czyli powielił perspektywę
    „Zniknięte" i zamienił listę „nic nie zginęło" w listę „poszukaj plików". Zastąpione i wycofane
    wypadają z tego samego powodu, co z kubełków roboczych: ich historię zamknął już inny zapis,
    a ten wiersz ma mówić o klatkach ŻYWYCH.

    Zwraca set[int]."""
    return {int(r[0]) for r in con.execute(
        "SELECT f.id FROM frame f "
        "WHERE f.superseded_by IS NULL AND f.retired_at IS NULL "
        "AND EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id AND l.present = 1) "
        "AND EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id AND l.present = 0)"
    ).fetchall()}


def superseded_frame_ids(con):
    """Zbiór frame_id ZASTĄPIONYCH: `frame.superseded_by IS NOT NULL` (perspektywa „Zastąpione", R4).

    TRZECI STAN, nie odmiana dwóch poprzednich, i różnica jest robocza, nie taksonomiczna:
      * ZNIKNIĘTA (`vanished_frame_ids`) — plik zniknął z dysku, robota jest DO ZROBIENIA
        (znaleźć albo wycofać);
      * BEZ LOKACJI OD ZAWSZE — klatka szkieletowa, inny stan i inna robota;
      * ZASTĄPIONA — treść pod ścieżką się zmieniła, robotę PRZEJĘŁA NASTĘPCZYNI. Nie ma tu nic
        do zrobienia, jest co obejrzeć.

    DLACZEGO WIDOCZNA, A NIE SKASOWANA (decyzja Zdzinia 2026-08-09, „z widocznym nagrobkiem"):
    wiersz jest ogniwem — `superseded_by` to jedyny zapis faktu „to ta sama fotka po edycji",
    a `repo.transfer_human_facts` czyta z niego werdykt człowieka. Kasacja gubiłaby jedno i drugie;
    archiwum jest append-only, a jedyna kasacja w jego historii (C3, 7 klatek) była wyjątkiem
    z czterema strażnikami. Tempo zmierzone: `location.rebound` odpalił **2 razy** przez pięć
    tygodni życia bazy — populacja rośnie wolno i nie magazyn jest jej kosztem, tylko szum
    w kubełkach roboczych.

    JEDEN właściciel predykatu dla licznika Porządków i trimu gridu — jak `vanished_frame_ids`
    i `dup_frame_ids`. Zwraca set[int]."""
    return {int(r[0]) for r in con.execute(
        "SELECT f.id FROM frame f WHERE f.superseded_by IS NOT NULL"
    ).fetchall()}


def retired_frame_ids(con):
    """Zbiór frame_id WYCOFANYCH ręką (perspektywa „Wycofane", D-OW-3/R2): `retired_at IS NOT NULL`.

    CZWARTY STAN, nie odmiana trzech poprzednich, i różnica znów jest ROBOCZA:
      * ZNIKNIĘTA — plik zniknął z dysku, robota jest DO ZROBIENIA (znaleźć albo wycofać);
      * ZASTĄPIONA — treść przejęła następczyni, robota jest CUDZA;
      * BEZ LOKACJI OD ZAWSZE — klatka szkieletowa, inna robota;
      * WYCOFANA — **człowiek powiedział, że tej roboty nie ma**. Jedyny z czterech, który jest
        WERDYKTEM, a nie faktem o świecie — i dlatego jedyny, który MUSI mieć drogę powrotu
        (`repo.restore_frames`).

    Godziny wycofanej klatki ZOSTAJĄ w `object_exposure` i to jest granica, nie przeoczenie: klatka
    została naświetlona naprawdę, a następczyni, która by je przejęła, nie ma. Odjęcie ich byłoby
    kasowaniem historii — czyli tym, przed czym `retired_at` ma bronić.

    JEDEN właściciel predykatu dla licznika Porządków i trimu gridu. Zwraca set[int]."""
    return {int(r[0]) for r in con.execute(
        "SELECT f.id FROM frame f WHERE f.retired_at IS NOT NULL"
    ).fetchall()}


def retired_conflict_frame_ids(con):
    """Zbiór frame_id WYCOFANYCH, KTÓRYCH PLIK WRÓCIŁ na dysk — jedyny stan, w którym ŻYWA klatka
    wypada ze WSZYSTKICH kubełków roboczych.

    Powstaje bez niczyjej pomyłki: wycofanie jest werdyktem o chwili zapisu, a plik może wrócić
    później zwykłym re-skanem (`repo.refresh_location` zapala `present = 1`). Werdykt nie gaśnie
    wtedy sam — i NIE MA gasnąć: cofnięcie gestu ręki przez wjazd materiału łamie warunek stały
    „ręka nietykalna". Powrót pliku unieważnia PRZESŁANKĘ werdyktu, ale unieważnić sam werdykt może
    wyłącznie człowiek.

    Dlatego stan ma być GŁOŚNY, a nie naprawiany po cichu w którąkolwiek stronę: liczy go AKCYJNY
    wiersz Porządków (prowadzi do gestu „Przywróć klatkę") oraz inwariant `audit.retire_invariants`
    (kryterium akceptacji §5.17). Bez tej pary paczka leczyłaby jeden ślepy zaułek i tylnymi
    drzwiami wnosiła drugi, cichszy.

    Predykat jest LUSTREM członu `wycofana_z_obecna_kopia` z audytu — znak w znak, dwie warstwy,
    równość pinuje test (wzorzec `nameless_*` / bramka 13). Zwraca set[int]."""
    return {int(r[0]) for r in con.execute(
        "SELECT f.id FROM frame f WHERE f.retired_at IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id AND l.present = 1)"
    ).fetchall()}


def dup_frame_ids(con):
    """Zbiór frame_id z >1 OBECNĄ lokacją (perspektywa „Duplikaty"). JEDNA derywacja trimu dla zbioru
    głównego i sibling-setów facetów (SPOT — trim w Pythonie na `n_present` i ten literał muszą znaczyć
    to samo; por. `base_rows` n_present). Zwraca set[int]."""
    return {int(r[0]) for r in con.execute(
        "SELECT frame_id FROM location WHERE present = 1 GROUP BY frame_id HAVING COUNT(*) > 1"
    ).fetchall()}


def review_frame_ids(con):
    """Zbiór frame_id perspektywy „Do przeglądu": light/master_light z `object_id IS NULL`
    (równoważne trimowi `object_canon is None` — `object.canon` NOT NULL, LEFT JOIN daje NULL
    wyłącznie przy braku obiektu).

    To SZERSZE pytanie niż kubełek `object_review` w `review_queue`: tam GROUP BY `object_raw`
    wymaga nagłówka Z NAZWĄ, tutaj liczy się sam brak obiektu. Rozjazd nie jest duplikatem do
    usunięcia — to dwa różne pytania (grid: „co jeszcze nie ma obiektu", kolejka: „co rozstrzygnąć
    i pod jaką nazwą"). Relacja jest PARTYCJĄ, a jej równanie ma JEDEN DOM — docstring
    `review_queue` (T5a). Powtórzenie go tutaj było drugą siedzibą tego samego faktu i rozjechało
    się przy pierwszym rozszczepieniu kubełka: S3 dopisało `nameless_raw_cleared_count` do jednej
    kopii, a druga cicho została przy starym składzie. Walidatorem jest `_partycja`
    w `tests/test_gui_queries_object.py` — też JEDEN dom, nie kopia per test.
    Ten zbiór NIE jest świadomy ANI formatu, ANI źródła i to jest zamierzone: RAW-owy light bez
    obiektu i gotowy stack bez obiektu wymagają przeglądu tak samo jak każdy inny — różnią się
    DROGĄ naprawy (ręka / żadna / karta w pliku), a nie tym, czy jest co rozstrzygnąć. Ta
    świadomość żyje po stronie kubełków kolejki, nie tutaj.

    ŚWIADOMY ZA TO ZASTĄPIENIA (2026-08-09): klatka z `superseded_by` odpada, bo jej robotę przejęła
    następczyni — a przegląd jest listą ROBOTY, nie spisem wierszy. To ten sam warunek, co w każdym
    kubełku kolejki i w rdzeniu; równość partycji wymaga, żeby stał po OBU stronach naraz.
    Zwraca set[int]."""
    return {int(r[0]) for r in con.execute(
        "SELECT id FROM frame WHERE object_id IS NULL AND superseded_by IS NULL "
        "AND retired_at IS NULL "
        "AND kind IN ('light','master_light')"
    ).fetchall()}


def lineage_reason_stale(row):
    """Czy zapisany powód braku rodowodu ZWIETRZAŁ wobec bieżącego stanu. Czysta funkcja, zero SQL.

    JEDEN WŁAŚCICIEL PREDYKATU (SPOT) dla dwóch wołających o różnych stawkach: panel „Rodowód"
    pyta o JEDEN obraz („czy mam prawo powtórzyć to zdanie?"), perspektywa `lineage_pending_frame_ids`
    pyta o CAŁE archiwum („kogo tam posłać?"). Predykat w Pythonie, nie w SQL, właśnie dlatego:
    literał SQL nie da się współdzielić między zapytaniami (bramka §7.1 zakazuje składania), więc
    druga siedziba tej reguły byłaby SIN-DUP-em, który rozjedzie się przy pierwszym nowym powodzie.

    `unresolved_reason` jest zapisem z chwili OSTATNIEGO przebiegu rodowodu, a fakty, na których
    stoi, zmienia GEST CZŁOWIEKA między przebiegami. Pytamy WĄSKO — tylko o te powody, których
    przesłankę widać w tym samym wierszu: obiekt nadany po przebiegu i odniesienie czasu wskazane
    po przebiegu. Powód ogólny („czy to jeszcze aktualne?") wymagałby znacznika zmiany faktów,
    którego dziś nie ma.

    STAWKA JEST WYŻSZA NIŻ KOMUNIKAT: stos ze zwietrzałym powodem czeka na PRZELICZENIE (etap
    „Policz rodowód stosów" w Dostawie), nie na decyzję człowieka — więc do kubełka nie należy.
    Zmierzone na żywej pf4 0808: 46 stosów z powodem, z czego 11 to `no_object` po nadaniu nazwy
    ręką. Kubełek bez tego sita wysyłałby użytkownika do jedenastu wierszy, w których panel sam
    mówi „ten zapis jest starszy niż twoje zmiany".

    CZŁON WEJŚĆ PYTA O KAŻDE NIEWYKLUCZONE WEJŚCIE, NIE O SAMĄ RĘKĘ — i to jest zgodne, nie
    szersze, bo `asserted_by <> 'user'` przy zapisanym powodzie jest STANEM ZAKAZANYM: pilnuje go
    bramka akceptacji §5.14 („powód wyklucza wejścia automatu", `scripts/acceptance_s5.py`).
    Zależność jest tu NAZWANA, bo jest cicha: gdyby tamten inwariant kiedyś upadł, ten predykat
    zacząłby uznawać wejście automatu za werdykt człowieka. Bramka pakietu 3a (0808) wskazała to
    zgodnie dwoma silnikami — proza mówiła wtedy „ręką", a kod liczył wszystko.

    WEJŚCIA WSKAZANE RĘKĄ WIETRZĄ KAŻDY POWÓD, nie tylko parę wrażliwą — i ten człon jest
    KONIECZNOŚCIĄ, nie wygodą. Werdykt ręki ma rangę najwyższą (`repo.RANGA_ASSERT`), więc kolejny
    przebieg rodowodu zostawia taki stos NIETKNIĘTY w całości (`stacks.run_stack_lineage`, gałąź
    „chroniony i powód") — łącznie z zapisanym powodem, który zamarza w bazie NA ZAWSZE. Bez tego
    członu stos raz rozstrzygnięty ręką wracałby do kubełka po każdym przebiegu, a panel powtarzałby
    „nie wiem, z czego powstał" nad listą klatek, które człowiek własnoręcznie potwierdził.

    `row` = wiersz z kolumnami `unresolved_reason`, `object_now`, `utc_offset_min`, `inputs`
    (`stack_lineage_head` albo `_lineage_reason_rows`). Zwraca bool."""
    powod = row["unresolved_reason"]
    if row["inputs"]:
        return True
    if powod == REASON_NO_OBJECT:
        return row["object_now"] is not None
    if powod == REASON_OFFSET_UNKNOWN:
        return row["utc_offset_min"] is not None
    return False


def _lineage_reason_rows(con):
    """Integracje z ZAPISANYM powodem braku rodowodu + fakty, po których poznać zwietrzenie.
    Wąski literał pod `lineage_pending_frame_ids` — pełny opis obrazu daje `stack_lineage_head`.
    `inputs` liczy WYŁĄCZNIE wejścia niewykluczone, jak w głowie panelu: stos, z którego człowiek
    odrzucił wszystkich kandydatów, wciąż nie ma rodowodu i do kubełka NALEŻY.
    Zwraca: master_frame_id, unresolved_reason, object_now, utc_offset_min, inputs."""
    return con.execute(
        "SELECT i.master_frame_id, i.unresolved_reason, i.utc_offset_min, "
        "       (SELECT f.object_id FROM frame f WHERE f.id = i.master_frame_id) AS object_now, "
        "       (SELECT COUNT(*) FROM integration_input ii "
        "         WHERE ii.integration_id = i.id AND ii.excluded = 0) AS inputs "
        "FROM integration i WHERE i.unresolved_reason IS NOT NULL "
        "  AND EXISTS (SELECT 1 FROM frame f WHERE f.id = i.master_frame_id "
        "                AND f.retired_at IS NULL)"
    ).fetchall()


def lineage_pending_frame_ids(con):
    """Zbiór frame_id perspektywy „Rodowód do potwierdzenia": gotowe obrazy, których rodowodu
    przebieg NIE ROZSTRZYGNĄŁ i których powód jest wciąż aktualny (`lineage_reason_stale` = False).

    JEDEN właściciel predykatu — jak `dup_frame_ids`/`vanished_frame_ids`: liczy z niego zarówno
    licznik Porządków (`tasks_state`), jak i trim gridu, więc wiersz zadania i lista, którą otwiera,
    nie mają jak się rozjechać.

    POWSTAŁO Z BRAKU POWIERZCHNI, nie z braku mechanizmu (Zdzin, 0808): panel „Rodowód" umiał
    potwierdzić i odrzucić wejście od I-2d, ale działał WYŁĄCZNIE z zaznaczenia jednej klatki —
    żeby trafić na 35 obrazów czekających na gest, trzeba było przeklikać 128 stosów i patrzeć,
    który się odezwie. Kod nazywał ten dług wprost w tym pliku („NIE MA TU `stack_frames_needing_hand`")
    i wskazywał cenę: własna PERSPEKTYWA, bo gest mieszka w Zbiorach. Tą ceną jest ten zbiór.

    ŚWIADOMIE BEZ WARUNKU NA `kind`: `integration.master_frame_id` wskazuje gotowy obraz z definicji
    drogi „Stosy", więc `kind = 'master_light'` byłby martwą literą udającą bramkę (ta sama figura,
    co `NO_OBJECT_CARD_FILETYPES` poza `nameless_stack_frames`).

    Zwraca set[int]."""
    return {int(r["master_frame_id"]) for r in _lineage_reason_rows(con)
            if not lineage_reason_stale(r)}


# ============================================================ PORTFEL NAŚWIETLEŃ (F7, PLAN_ux_redesign §8)
# „Ile mam godzin na obiekt, per filtr?". STAŁY literał + `json_each(?)`. Godziny z `header.exptime`
# przez `frame JOIN header` — NIE z cards. Powód pierwotny (cards FITS-only) ZNIKNĄŁ po P6a/P6b, ale
# reguła zostaje: `header` to ZEZNANIE (jeden wiersz na klatkę, pola gorące), a `cards` to jego lustro
# tekstowe — liczby bierzemy ze źródła, nie z odbicia. KIND-AWARE `kind='light'` (EXPTIME masterlighta
# = czas ZINTEGROWANY → wliczony podwoiłby godziny).
# header 1:1 z frame (PK frame_id) → frame w >1 present location = JEDEN wiersz, `SUM` bez inflacji.


def object_exposure(con, frame_ids):
    """Naświetlenie per (obiekt, filtr) w zbiorze: `SUM(exptime)` sekund + liczba lightów BEZ exptime.
    JAWNE-NULL: `exptime IS NULL` u lighta → `n_null` (nie ciche pominięcie); `filter_canon IS NULL`
    → własna grupa (kubełek „(bez filtra)"). Grupa cała bez exptime → `secs=NULL` (agregat = 0 s).
    `object_id IS NOT NULL` (kalibracja/bez-obiektu poza facetem Obiekt); XISF/light bez header wypada
    JOIN-em. Godziny — jak licznik facetu — obejmują klatki `present=0` (parytet z `facet_objects`).

    KLATKA ZASTĄPIONA NIE DOLICZA SEKUND (R4, `frame.superseded_by`) — i to jest szew, na którym
    `present=0` wyżej robi RÓŻNICĘ: duch nie ma obecnej kopii, więc bez tego warunku wpadałby tu
    przez tamtą furtkę i doliczał ekspozycję, którą już liczy jego następczyni. Zniknięcie
    i zastąpienie to dwa różne stany: kopii, która ZNIKNĘŁA, godziny się należą (naświetlenie było,
    plik gdzieś jest), kopii ZASTĄPIONEJ — nie, bo to ten sam plik pod nową tożsamością.

    ⚠ PARYTET Z `facet_objects` OBEJMUJE `present`, NIE ZASTĄPIENIE — i tu się rozjeżdża świadomie.
    Uniwersum gridu to WSZYSTKIE klatki (`all_frame_ids`, w tym bez lokacji), a facet ich nie
    odsiewa, więc para „zastąpiona + następczyni" pokaże w facecie **2**, a tutaj godziny **jednej**.
    Dopóki klatka zastąpiona nie niesie obiektu, rozjazd jest niewidoczny (zmierzone na żywym
    archiwum 0809: obie takie klatki mają `object_id NULL`). Staje się widoczny po
    `transfer_human_facts`, które ZOSTAWIA obiekt na starej klatce.
    PYTANIE „ZNIKAĆ CZY ZOSTAWAĆ" JEST JUŻ ROZSTRZYGNIĘTE (decyzja Zdzinia 0809, `d3cbeb9`):
    **zostaje i jest OZNACZONA** — grid maluje ją własnym tłem i pisze w komórce „zastąpiona przez
    #N", a `PRESET_SUPERSEDED` daje jej perspektywę. Otwarty został wyłącznie SAM FACET: `facet_objects`
    dalej liczy ją do uniwersum, więc rozjazd `2` vs `1` czeka na pierwszą zastąpioną Z OBIEKTEM.
    Godziny na to nie czekają i nie mają czekać — podwójny rachunek jest chorobą, którą R4 leczy.
    Zwraca wiersze: object_id, filter_canon, secs, n_null."""
    return con.execute(
        "SELECT f.object_id, f.filter_canon, "
        "       SUM(h.exptime)         AS secs, "
        "       SUM(h.exptime IS NULL) AS n_null "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind = 'light' AND f.object_id IS NOT NULL "
        "  AND f.superseded_by IS NULL "
        "  AND f.id IN (SELECT value FROM json_each(?)) "
        "GROUP BY f.object_id, f.filter_canon "
        "ORDER BY f.object_id, secs DESC",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def perspectives(con):
    """Nazwane widoki z BAZY (I-1, D-P-I-3) — `[(nazwa, spec|None), …]` po nazwie.

    Perspektywa jedzie z archiwum, nie z komputerem: ta sama para „nazwa + specyfikacja" ma się
    otworzyć na laptopie po skopiowaniu pliku bazy. Sortowanie po nazwie, bo lista jest do
    ZNAJDOWANIA, a kolejność zapisu nie niesie tu żadnej informacji.

    `spec=None` znaczy „wiersz jest, ale nie umiem go zastosować" i ma DWIE przyczyny: treść nie
    jest JSON-em obiektowym albo niesie znacznik `legacy_sql` z migracji 0013 (nazwany widok
    zapisany kiedyś jako SQL — szkielet z 0002 nigdy nie dostał pisarza, więc taki wiersz mógł
    powstać wyłącznie ręcznie). Degradacja jest ŁAGODNA i JAWNA: pusty spec zastosowany w gridzie
    czyta się jak „pokaż wszystko", czyli filtr zdejmujący filtr — cichy fałsz zamiast pytania.

    Nieznane KLUCZE wewnątrz spec-a to co innego i tu ich nie ruszamy: baza z nowszej wersji
    Horreum ma prawo nieść pole, którego ta jeszcze nie zna, a `grid` czyta spec przez `.get`,
    więc pomija je bez wyjątku (§4.3 briefu)."""
    out = []
    for r in con.execute("SELECT name, spec_json FROM saved_query ORDER BY name").fetchall():
        try:
            spec = json.loads(r["spec_json"])
        except (ValueError, TypeError):
            spec = None
        if not isinstance(spec, dict) or "legacy_sql" in spec:
            spec = None
        out.append((r["name"], spec))
    return out


def integrated_exposure(con):
    """Naświetlenie, które REALNIE weszło w gotowe obrazy — per (obiekt, filtr), SUB LICZONY RAZ.

    Siostra `object_exposure`: tamta mówi „ile naświetliłem", ta „ile z tego jest w obrazie".
    Różnica jest wartością sama w sobie — 40 h zebrane i 12 h zintegrowane to dwa różne stany
    projektu, a planer bez tej drugiej liczby doradza wyłącznie z naświetleń.

    LICZNIK STOI NA `DISTINCT input_frame_id` I TO JEST CAŁY SENS TEJ FUNKCJI (fakt 20 briefu P-I).
    `integration_input` jest POKRYCIEM, nie podziałem: zmierzone 43 pary integracji tej samej półki
    mają nakładające się okna (reprocessingi tej samej nocy — `WBPP` vs `WBPP_nowy` — oraz warianty
    tego samego obrazu: `_ast`, `_drizzle_1x`, `_integration`). Suma po WIERSZACH relacji policzyłaby
    ten sam sub tyle razy, ile obrazów z niego zrobiono, i pokrycie rosłoby od samego przeliczania
    archiwum. Podzapytanie `DISTINCT` zdejmuje N:M PRZED sumowaniem.

    `excluded = 0` — werdykt ręki „ta klatka NIE weszła" (I-2d) jest faktem, a nie ukryciem wiersza.

    OBIEKT BIERZEMY Z KLATKI WEJŚCIOWEJ, nie z mastera: godziny są własnością subów, a oś obiektu
    lighta przeszła tę samą drabinę resolvera co reszta archiwum. `kind = 'light'` w warunku jest
    strażnikiem, nie ozdobą — rodowód wiąże dziś wyłącznie lighty, ale `EXPTIME` mastera to czas
    ZINTEGROWANY i wpuszczony tu podwoiłby rachunek.

    JAWNE-NULL jak w `object_exposure`: `n_null` liczy wejścia bez `exptime` zamiast je przemilczeć.
    Zwraca wiersze: object_id, filter_canon, secs, n_null."""
    return con.execute(
        "SELECT f.object_id, f.filter_canon, "
        "       SUM(h.exptime)         AS secs, "
        "       SUM(h.exptime IS NULL) AS n_null "
        "FROM (SELECT DISTINCT ii.input_frame_id AS fid FROM integration_input ii "
        "       WHERE ii.excluded = 0) d "
        "JOIN frame f ON f.id = d.fid "
        "JOIN header h ON h.frame_id = d.fid "
        "WHERE f.kind = 'light' AND f.object_id IS NOT NULL "
        "GROUP BY f.object_id, f.filter_canon "
        "ORDER BY f.object_id, secs DESC").fetchall()


def stack_locations(con):
    """GDZIE LEŻY GOTOWY OBRAZ — klatki `master_light` per obiekt, ze ścieżką obecnej kopii.

    Druga połowa mostu do planera (I-2e): „ile godzin weszło" bez „gdzie to jest" zostawia
    użytkownika z liczbą, po którą musi iść do eksploratora. Ścieżka jak w `nameless_frames`
    (`present = 1`, najniższe `id`) — kopia, którą realnie da się otworzyć.

    Stos bez obecnej kopii ZOSTAJE w wyniku z `path = NULL`: tożsamość klatki to `sha1_data`, nie
    ścieżka, a „obraz jest, ale nie mam go pod ręką" to inna odpowiedź niż „obrazu nie ma".
    Obiektu nierozpoznanego nie zgadujemy — stos bez `object_id` do wiersza celu nie należy i widać
    go własnym kubełkiem bezimiennych (D-P-I-5).

    Zwraca wiersze: object_id, frame_id, path."""
    return con.execute(
        "SELECT f.object_id, f.id AS frame_id, "
        "       (SELECT l.path FROM location l WHERE l.frame_id = f.id AND l.present = 1 "
        "         ORDER BY l.id LIMIT 1) AS path "
        "FROM frame f WHERE f.kind = 'master_light' AND f.object_id IS NOT NULL "
        "ORDER BY f.object_id, f.id").fetchall()


def stack_lineage_head(con, frame_id):
    """Wiersz `integration` dla klatki stosu + LICZBY, którymi panel opisze obraz (I-2d) — albo
    `None`, gdy rodowodu jeszcze nie liczono dla tej klatki.

    `inputs`/`secs` liczą WYŁĄCZNIE wejścia niewykluczone (`excluded = 0`): odrzucone ręką zostają
    w tabeli jako fakt „ta klatka NIE weszła", ale w godzinach obrazu nie mają czego szukać.
    `excluded` osobno, żeby powierzchnia umiała powiedzieć, ile decyzji już zapadło.

    `twins` = ile INNYCH integracji ma DOKŁADNIE ten sam zbiór wejść (równość `integ_hash`).
    Bez tej liczby flaga „okno nierozłączne" kłamie o przyczynie: zmierzone na 128 realnych stosach
    — z 62 oflagowanych integracji **51 ma bliźniaka o identycznym zbiorze** (to warianty tego
    samego obrazu: `_ast`, `_drizzle_1x`, `_integration`), a tylko część dzieli klatki częściowo
    z INNYM ujęciem tej nocy. Ostrzeżenie należy się tym drugim; pierwszym należy się wyjaśnienie.

    `shared` LICZY REALNE WSPÓŁDZIELENIE, nie nakładanie się okien — i to jest różnica, nie niuans.
    `integration.ambiguous` mówi o PLANIE („okna tej półki zachodzą"), więc bywa prawdziwe także
    tam, gdzie całe zachodzenie tłumaczą warianty tego samego obrazu. `shared` pyta o STAN: czy ten
    sam wiersz `integration_input` należy do integracji o INNYM odcisku. Panel ostrzega z tego
    pytania, bo tylko ono odróżnia „ten sub policzono dwa razy" od „ten obraz ma drugą wersję".

    `object_now` to BIEŻĄCY obiekt klatki mastera — nie po to, żeby go wyświetlić, tylko żeby
    powierzchnia umiała rozpoznać, że `unresolved_reason` ZWIETRZAŁ. Powód jest zapisem z chwili
    OSTATNIEGO przebiegu rodowodu, a obiekt zmienia się gestem człowieka między przebiegami —
    więc panel potrafił twierdzić „obraz nie ma rozpoznanego obiektu" o wierszu, który w kolumnie
    obok pokazywał nazwę (firsthand 0808, sprzeczność w JEDNYM oknie). Kolumna jest tu ODPOWIEDZIĄ
    na tę sprzeczność, nie ozdobą: bez niej panel nie ma z czym porównać własnego zapisu.

    `utc_offset_min` (R2) niesie ODNIESIENIE CZASU tego obrazu w trójstanie migracji 0016:
    `None` = nikt nie wskazał, `0` = UTC, wartość = minuty. Panel czyta je po to, żeby odróżnić
    „nie wiem" od „to jest UTC" — dwa różne zdania, których jedna kolumna bez trójstanu nie
    umiałaby powiedzieć.

    Zwraca: integration_id, unresolved_reason, degenerate, ambiguous, telescope_mismatch,
    declared_rows, drizzle_inputs, disabled_inputs, tool, window_start, window_end,
    utc_offset_min, inputs, excluded, secs, sources (rozdzielone przecinkiem źródła pewności
    wejść), twins, shared."""
    return con.execute(
        "SELECT i.id AS integration_id, i.unresolved_reason, i.degenerate, i.ambiguous, "
        "       i.telescope_mismatch, i.declared_rows, i.drizzle_inputs, i.disabled_inputs, "
        "       i.tool, i.window_start, i.window_end, i.utc_offset_min, "
        "       (SELECT f.object_id FROM frame f WHERE f.id = i.master_frame_id) AS object_now, "
        "       (SELECT COUNT(*) FROM integration b WHERE b.integ_hash IS NOT NULL "
        "         AND b.integ_hash = i.integ_hash AND b.id <> i.id) AS twins, "
        "       (SELECT COUNT(DISTINCT b.id) FROM integration_input ia "
        "          JOIN integration_input ib ON ib.input_frame_id = ia.input_frame_id "
        "          JOIN integration b ON b.id = ib.integration_id "
        "         WHERE ia.integration_id = i.id AND ia.excluded = 0 AND ib.excluded = 0 "
        # ODCISK NIEZNANY ⇒ OSTRZEGAJ. `IS NOT` byłby NULL-safe jako operator, ale semantycznie
        # zlewa „nie wiem, jaki zbiór" z „ten sam zbiór": dwie integracje bez odcisku (rodowód
        # z samych werdyktów ręki) dzieliłyby wtedy klatkę bez słowa. Warunek jawny trzyma też
        # spójność z `twins`, który NULL-e wyklucza wprost.
        "           AND b.id <> i.id AND (i.integ_hash IS NULL OR b.integ_hash IS NULL "
        "                                 OR b.integ_hash <> i.integ_hash)) AS shared, "
        "       (SELECT COUNT(*) FROM integration_input ii "
        "         WHERE ii.integration_id = i.id AND ii.excluded = 0) AS inputs, "
        "       (SELECT COUNT(*) FROM integration_input ii "
        "         WHERE ii.integration_id = i.id AND ii.excluded = 1) AS excluded, "
        "       (SELECT SUM(h.exptime) FROM integration_input ii "
        "          JOIN header h ON h.frame_id = ii.input_frame_id "
        "         WHERE ii.integration_id = i.id AND ii.excluded = 0) AS secs, "
        "       (SELECT GROUP_CONCAT(DISTINCT ii.asserted_by) FROM integration_input ii "
        "         WHERE ii.integration_id = i.id AND ii.excluded = 0) AS sources "
        "FROM integration i WHERE i.master_frame_id = ?", (frame_id,)).fetchone()


def stack_lineage_inputs(con, frame_id):
    """Wejścia stosu pod listę panelu (I-2d) — WSZYSTKIE, także odrzucone ręką (kolumna `excluded`
    niesie werdykt; ukrycie odrzuconych zabrałoby jedyną drogę cofnięcia własnej decyzji).

    Cel przez `MIN(id) … present = 1` jak w `nameless_frames` — panel pokazuje ścieżkę OBECNEJ
    kopii, a klatka bez obecnej kopii i tak zostaje w rodowodzie (tożsamość to `sha1_data`,
    nie ścieżka). Zwraca: input_frame_id, asserted_by, excluded, date_obs, exptime, path."""
    return con.execute(
        "SELECT ii.input_frame_id, ii.asserted_by, ii.excluded, h.date_obs, h.exptime, "
        "       (SELECT l.path FROM location l WHERE l.frame_id = ii.input_frame_id "
        "         AND l.present = 1 ORDER BY l.id LIMIT 1) AS path "
        "FROM integration_input ii JOIN integration i ON i.id = ii.integration_id "
        "LEFT JOIN header h ON h.frame_id = ii.input_frame_id "
        "WHERE i.master_frame_id = ? ORDER BY h.date_obs, ii.input_frame_id",
        (frame_id,)).fetchall()


# DŁUG ZAPŁACONY 0808: „gotowe obrazy czekające na Twoje słowo" ma odtąd wiersz Porządków i własną
# PERSPEKTYWĘ w Zbiorach (`grid.PRESET_LINEAGE`) — zbiór liczy `lineage_pending_frame_ids` wyżej.
# Zapis pierwotny odkładał go słusznie: samo zapytanie bez powierzchni byłoby kodem dla nikogo
# (SIN-PRECRUFT), a ceną jest flaga presetu + serializacja + kryteria, nie jeden SELECT. Cenę
# zapłacił firsthand Zdzinia: panel rodowodu działał z ZAZNACZENIA, więc 35 obrazów czekających
# na gest trzeba było znaleźć, przeklikując 128 stosów.


# ============================================================ PORZĄDKI (F5, PLAN_ux_redesign §6)
# Liczniki listy zadań `TasksView` — bieżący STAN tabel, nigdy `count(event)` (REVIEW-ZE-STANU,
# memory horreum-review-queue-from-state). Zbiory dups/review REUŻYWANE z derywacji perspektyw
# (SPOT — osobny literał COUNT byłby drugim właścicielem predykatu).


def tasks_state(con):
    """Liczniki Porządków ze STANU. `unresolved_lights`/`dup_frames` = len() zbiorów perspektyw
    „Do przeglądu"/„Duplikaty" (JEDNA derywacja z gridem). `telescopes_unlabeled`/
    `observatories_unnamed`: NULL = nienazwane (`label_telescope`/`label_observatory` odrzucają pusty
    string, więc pustych stringów w bazie nie ma); tylko kanoniczne (`merged_into IS NULL`).
    `vanished_frames` = len() zbioru perspektywy „Zniknięte" (P5 — ta sama derywacja co grid; przed
    passem obecności był to osobny literał COUNT, czyli drugi właściciel predykatu).
    `stacks_lineage_pending` = len() zbioru perspektywy „Rodowód do potwierdzenia" — ta sama figura
    po raz trzeci; gest mieszka w panelu „Rodowód" w Zbiorach, więc wiersz Porządków prowadzi do
    perspektywy, a nie do podstrony. `superseded_frames` = len() zbioru „Zastąpione" (R4) — ta sama
    figura po raz czwarty, ale wiersz jest INFORMACYJNY: zastąpiona klatka nie jest robotą, tylko
    zapisem historii, i po to tu stoi, żeby dało się ją znaleźć, skoro zniknęła z kolejek.
    Zwraca dict siedmiu liczników.

    Licznika `xisf_frames` NIE MA od P6c: był informacją „nagłówków XISF nie umiemy zapisać", a ta
    przestała być prawdziwa razem z pisarzem — licznik samego formatu nie jest ani zadaniem, ani
    osobliwością (liczbę plików XISF pokazuje facet formatu w Zbiorach)."""
    telescopes_unlabeled = con.execute(
        "SELECT COUNT(*) FROM telescope WHERE label IS NULL AND merged_into IS NULL"
    ).fetchone()[0]
    observatories_unnamed = con.execute(
        "SELECT COUNT(*) FROM observatory WHERE name IS NULL AND merged_into IS NULL"
    ).fetchone()[0]
    return {
        "unresolved_lights": len(review_frame_ids(con)),
        "stacks_lineage_pending": len(lineage_pending_frame_ids(con)),
        "dup_frames": len(dup_frame_ids(con)),
        "telescopes_unlabeled": telescopes_unlabeled,
        "observatories_unnamed": observatories_unnamed,
        "vanished_frames": len(vanished_frame_ids(con)),
        "superseded_frames": len(superseded_frame_ids(con)),
        "missing_copy_frames": len(missing_copy_frame_ids(con)),
        # Ta sama figura po raz PIĄTY i SZÓSTY (D-OW-3/R2), ale o RÓŻNEJ naturze — i to jest cała
        # rzecz: „Wycofane" są zapisem historii (wiersz informacyjny, jak „Zastąpione"), a
        # „wycofana, a plik wrócił" JEST robotą, bo tylko w tym stanie żywa klatka wypada ze
        # wszystkich kubełków. Gdyby drugi licznik był informacyjny, gest wycofania cicho ukrywałby
        # materiał, który wrócił — czyli wnosiłby dokładnie ten defekt, który paczka leczy.
        "retired_frames": len(retired_frame_ids(con)),
        "retired_conflict_frames": len(retired_conflict_frame_ids(con)),
    }


def has_real_volume_locations(con):
    """Czy baza zna JAKĄKOLWIEK lokację z realnym serialem (`volume != '?'`)? Guard mieszania
    serialu (F5R#3): skan z serialem `'?'` do takiej bazy PODWOIŁBY lokacje znanych klatek (brama
    `(volume,path,mtime)` nie trafi, `UNIQUE(volume,path)` wpuści drugą). `location.volume` jest
    NOT NULL — porównanie bez pułapki trójwartościowej. Zwraca bool."""
    return con.execute(
        "SELECT 1 FROM location WHERE volume != '?' LIMIT 1"
    ).fetchone() is not None


def cards_pivot(con, frame_ids, keywords):
    """Wiersze cards dla pivota: literał `json_each` — listy id/keywordów jako TABLICE JSON (jeden param
    każda), bez dynamicznych `?` ani chunkowania (F4: plan po indeksie PK, ~53 ms/4000 klatek). ORDER BY
    frame_id,keyword,idx (pivot bierze pierwszy idx). Zwraca: frame_id, keyword, idx, value_raw, value_num."""
    return con.execute(
        "SELECT frame_id, keyword, idx, value_raw, value_num FROM cards "
        "WHERE keyword IN (SELECT value FROM json_each(?)) "
        "  AND frame_id IN (SELECT value FROM json_each(?)) "
        "ORDER BY frame_id, keyword, idx",
        (json.dumps(list(keywords)), json.dumps(list(frame_ids))),
    ).fetchall()


# ============================================================ WRITEBACK / makro (krok 4, read-model)
# Read-model stagingu writebacku. Wszystko STAŁE LITERAŁY SELECT + `?` (bramka §7.1). Makro
# (`horreum.macro`) woła te czytniki, sam nie dotyka DB; zapis idzie przez `repo`. Cel writebacku =
# LOCATION (fizyczny plik), więc topologia present-location jest tu, nie na frame.


def writeback_frame_targets(con, frame_ids):
    """Dla zbioru frame_id: filetype + `sha1_data_uncomputable` (frame) + KAŻDA OBECNA (`present=1`)
    location z faktami kopii potrzebnymi do zapisu (header_hash/hdu_index/compressed). Frame BEZ
    obecnej kopii → wiersz z location_id NULL (makro odróżni „brak kopii" od wielu kopii licząc
    wiersze per frame). frame_ids jako TABLICA JSON (`json_each`, jeden param). Wybór celu (D-W1:
    dokładnie 1 present; T6: nie skompresowany; D-X-13: nie degenerat tożsamości) robi makro, nie ten
    czytnik. ORDER BY frame_id, location_id. Zwraca: frame_id, filetype, sha1_data_uncomputable,
    location_id, path, header_hash, hdu_index, compressed."""
    return con.execute(
        "SELECT f.id AS frame_id, f.filetype, f.sha1_data_uncomputable, "
        "       l.id AS location_id, l.path, l.header_hash, l.hdu_index, l.compressed "
        "FROM frame f "
        "LEFT JOIN location l ON l.frame_id = f.id AND l.present = 1 "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "ORDER BY f.id, l.id",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def selection_object_state(con, frame_ids):
    """Stan osi OBIEKT dla ZAZNACZENIA — jedyne wejście obu gestów paska Zbiorów (S2b, §4/14c).

    OSOBNY, WĄSKI CZYTNIK, a nie nowe kolumny WIDOCZNE w gridzie: to `BASE_COLS` wchodzi w kolizję
    z podłogą okna (D-0801-1), a te fakty są potrzebne wyłącznie w chwili gestu. Zdanie zapisane tu
    pierwotnie brzmiało „a nie dwie nowe kolumny w `base_rows`" i było prawdą o kolumnach
    WIDOCZNYCH, ale jako zakaz ogólny okazało się fałszywe: `base_rows` niesie od początku siedem
    kolumn niepokazywanych (`filetype`, `present`, `superseded_by`…), a paczka R-S3-4 dołożyła
    dwie kolejne (`object_source`, `object_cleared_id`) po to, żeby POLITYKA KOLUMNY miała czym
    odróżnić kanon od zeznania. Granica przebiega po `BASE_COLS`, nie po `SELECT`-cie.

    Rozstrzyga TRZY pytania, których widok sam sobie nie odpowie:

    * czy jest co robić (`namable`/`clearable` — wygaszenie kontrolki mówi prawdę, a nie „może się
      uda"; pusty zbiór to jedno, a 800 klatek z samego nagłówka — zupełnie co innego);
    * jaki jest ZAMROŻONY STAN okna (`expected_object_id`) — do parametru klingi;
    * czy zaznaczenie jest jednorodne (`conflict`) — dwa różne obiekty wśród klatek podlegających
      nadpisaniu znaczą ODMOWĘ, bo gest „nazwij te wszystkie" nie ma wtedy jednego przedmiotu.

    `expected` i `conflict` liczą się WYŁĄCZNIE wśród klatek, które gest może ruszyć (light, źródło
    słabe). Liczenie ich po całym zaznaczeniu blokowałoby akcję z powodu klatki, której i tak nikt
    nie zamierzał tknąć — a to odmowa o fałszywej przyczynie.

    DWIE LICZBY DLA ZDANIA, NIE SAM BIT (adjudykacja recenzji S2b): `overwrite` mówi, ile klatek
    gest realnie PRZEMALUJE (mają już kanon ze źródła słabego), a `conflict_n` — ile jest różnych
    obiektów, gdy gest odmawia. Bit `conflict` nie wystarczał: komunikat wstawiał literał „2", więc
    zaznaczenie z siedmioma obiektami kazało zawęzić do dwóch i po zawężeniu odmawiało tak samo.

    TRZECIA POZYCJA MENU (`restorable`, R-S2b-3) LICZY SIĘ TĄ SAMĄ PĘTLĄ i to jest cała jej cena:
    wiersz i tak niesie `object_cleared_id`, więc bramka „jest co przywracać" jest DARMOWA i przy
    tym EXAKTNA. Osobne zapytanie w tym miejscu byłoby powrotem do defektu, który zamknęło P-K:
    ten read-model chodzi przy KAŻDEJ zmianie zaznaczenia, a `Ctrl+A` na 16 tys. klatek robi
    z każdego dołożonego pytania koszt liczony w sekundach na wątku GUI.

    Zwraca dict: n, lights, stacks, stacks_touchable, namable, overwrite, clearable, restorable,
    expected_object_id, conflict, conflict_n, by_source."""
    rows = con.execute(
        "SELECT f.kind, f.object_id, f.object_source, f.object_cleared_id FROM frame f "
        "WHERE f.id IN (SELECT value FROM json_each(?))",
        (json.dumps(list(frame_ids)),)).fetchall()
    by_source, slabe = {}, set()
    n = lights = stacks = stacks_touchable = namable = overwrite = clearable = restorable = 0
    for r in rows:
        n += 1
        by_source[r["object_source"]] = by_source.get(r["object_source"], 0) + 1
        if r["kind"] not in LIGHT_KINDS:
            continue
        lights += 1
        if r["kind"] == "master_light":
            stacks += 1        # LICZONY, nie wykluczany (D-OW-7): stos jest w zasięgu obu gestów
        do_cofniecia = (r["object_source"] in CLEARABLE_OBJECT_SOURCES
                        and r["object_id"] is not None)
        do_nazwania = r["object_id"] is None or r["object_source"] in WEAK_OBJECT_SOURCES
        # DWIE LICZBY STOSÓW, BO DWA RÓŻNE PYTANIA (bramka pakietu 0810, zarzut 1). `stacks` mówi
        # „ILE STOSÓW JEST W ZAZNACZENIU" i tym pytaniem gasi kontrolkę (`lights == stacks`).
        # `stacks_touchable` mówi „ILE Z NICH GEST REALNIE RUSZY" i tylko ta liczba ma prawo stanąć
        # w zdaniu o skutku. Rozjazd nie jest teoretyczny: zmierzone na żywym archiwum
        # **181 ze 193 stosów jest NIETYKALNYCH** (nazwa ze źródła mocnego: `header` 73,
        # `common_name` 50, `catalog_xref` 46), więc człon liczony `stacks` kłamałby w 94%
        # realnych zaznaczeń — i to w tooltipie, który powstał PO TO, żeby powiedzieć prawdę
        # przed gestem. Liczone RAZ, bo klatka bywa naraz do nazwania i do cofnięcia
        # (źródło `path` z nadanym obiektem).
        if r["kind"] == "master_light" and (do_nazwania or do_cofniecia):
            stacks_touchable += 1
        if do_cofniecia:
            clearable += 1
        if r["object_cleared_id"] is not None:
            # NAGROBEK Z PAMIĘCIĄ (0017) — jedyna klatka, którą gest przywracania ma jak ruszyć.
            # Nagrobek BEZ pamięci (baza-dawca sprzed migracji) świadomie się tu nie liczy: gest
            # nie miałby czego przywrócić, a aktywna pozycja obiecywałaby robotę, której nie ma.
            restorable += 1
        if do_nazwania:
            namable += 1
            if r["object_id"] is not None:
                overwrite += 1              # ta klatka ma już kanon — gest go PRZEMALUJE
                slabe.add(r["object_id"])
    return {"n": n, "lights": lights, "stacks": stacks,
            "stacks_touchable": stacks_touchable, "namable": namable,
            "overwrite": overwrite, "clearable": clearable, "restorable": restorable,
            "by_source": by_source,
            "expected_object_id": next(iter(slabe)) if len(slabe) == 1 else None,
            "conflict": len(slabe) > 1, "conflict_n": len(slabe)}


def restore_targets(con, frame_ids):
    """GRUPY DO PRZYWRÓCENIA z zaznaczenia (R-S2b-3) — czytane ze STANU, nie z dziennika.

    Zwraca `(grupy, bez_pamieci)`, gdzie grupa to dict `{object_id, canon, catalog, kind,
    frame_ids}` — po jednej na OBIEKT, bo klinga osi przyjmuje jeden kanon na wywołanie, a masowe
    cofnięcie potrafi objąć klatki kilku różnych obiektów naraz. `object_id` jedzie w grupie nie
    dla zapisu (klinga pisze po KANONIE), tylko jako ZAMROŻONY STAN dla guardu dryfu
    (`repo.user_assign_object(expected_cleared_id=…)`, bramka pakietu 0810). `bez_pamieci` to liczba nagrobków, których nie da
    się przywrócić, bo nie pamiętają przedmiotu (baza-dawca sprzed migracji 0017).

    DLACZEGO STAN, A NIE `event`. Pytanie brzmi „co ta klatka odrzuciła" i jest pytaniem o NIĄ,
    nie o historię. Odpowiadanie skanem dziennika łamie się dwukrotnie: klatka cofnięta dwa razy
    ma dwa `object.cleared` o różnym `was_object_id` (a payload nie mówi, który jest żywy), zaś
    `repo.transfer_human_facts` emituje TEN SAM verb bez tego klucza — nagrobek przeniesiony po
    podmianie pliku miałby ślad, ale bez przedmiotu, więc wyparowałby z OBU liczb naraz. To ta
    sama figura, którą repo dostało już trzy razy (pamięć `horreum-review-queue-from-state`).

    ŹRÓDŁA W GRUPIE NIE MA ŚWIADOMIE. Cofnąć da się dwa źródła (`user` i `path`), ale przywracamy
    ZAWSZE jako `user`, bo przywrócenie JEST wskazaniem palcem — człowiek mówi „jednak tak", i to
    drugi raz świadomie. Awans potwierdzonej propozycji ze ścieżki do wskazania ręki jest tu
    poprawny, a druga kolumna trzymająca „jakie było źródło" karmiłaby wyłącznie ten jeden gest.

    Kolejność grup po `canon`, żeby zdanie po geście było DETERMINISTYCZNE, a nie zależne od
    kolejności wierszy w zaznaczeniu."""
    rows = con.execute(
        "SELECT f.id AS frame_id, o.id AS object_id, o.canon, o.catalog, o.kind "
        "FROM frame f LEFT JOIN object o ON o.id = f.object_cleared_id "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "  AND f.object_source = 'user_cleared' "
        "ORDER BY o.canon, f.id",
        (json.dumps(list(frame_ids)),)).fetchall()
    grupy, bez_pamieci = {}, 0
    for r in rows:
        if r["object_id"] is None:
            bez_pamieci += 1
            continue
        g = grupy.setdefault(r["object_id"], {"object_id": r["object_id"], "canon": r["canon"],
                                              "catalog": r["catalog"], "kind": r["kind"],
                                              "frame_ids": []})
        g["frame_ids"].append(r["frame_id"])
    return list(grupy.values()), bez_pamieci


def rename_frame_targets(con, frame_ids):
    """Dla zbioru frame_id: fakty do `compose_name` (kind/filter_canon/object_canon/object_raw/
    sha1_data/date_obs/exptime — frame+header) + KAŻDA OBECNA (`present=1`) location z `path`+`mtime`
    (kotwica anty-stale renamu). Frame BEZ obecnej kopii → wiersz z location_id NULL (silnik odróżni
    „brak kopii" od wielu, licząc wiersze per frame). Rename DOZWOLONY dla XISF (nie tyka nagłówka),
    więc BEZ `header_hash`/`compressed` (nieistotne). frame_ids jako TABLICA JSON (`json_each`, jeden
    param — §4). ORDER BY frame_id, location_id. Zwraca: frame_id, filetype, kind, filter_canon,
    sha1_data, object_canon, object_raw, date_obs, exptime, location_id, path, mtime."""
    return con.execute(
        "SELECT f.id AS frame_id, f.filetype, f.kind, f.filter_canon, f.sha1_data, "
        "       obj.canon AS object_canon, h.object_raw, h.date_obs, h.exptime, "
        "       l.id AS location_id, l.path, l.mtime "
        "FROM frame f "
        "LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN object obj ON obj.id = f.object_id "
        "LEFT JOIN location l ON l.frame_id = f.id AND l.present = 1 "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "ORDER BY f.id, l.id",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def frame_for_location(con, location_id):
    """frame_id stojący pod daną LOCATION — mapowanie podglądu makra (touched niesie location_id,
    grid kluczuje frame). Zwraca int albo None."""
    row = con.execute("SELECT frame_id FROM location WHERE id = ?", (location_id,)).fetchone()
    return row["frame_id"] if row else None


def frame_cards(con, frame_id):
    """Wszystkie karty jednego frame'a (lustro EAV) do budowy `env` makra i reguł set/add. Sort po
    (keyword, idx) — makro bierze pierwsze wystąpienie jako env, liczy kardynalność. Zwraca:
    keyword, idx, value_raw, value_num, value_type, comment."""
    return con.execute(
        "SELECT keyword, idx, value_raw, value_num, value_type, comment "
        "FROM cards WHERE frame_id = ? ORDER BY keyword, idx",
        (frame_id,),
    ).fetchall()


def location_cards(con, location_id):
    """Karty frame'a stojącego pod daną LOCATION (dla ręcznej edycji komórki gridu — grid=frame,
    ale cel edycji = fizyczny plik = location). Zwraca jak `frame_cards`."""
    return con.execute(
        "SELECT c.keyword, c.idx, c.value_raw, c.value_num, c.value_type, c.comment "
        "FROM cards c JOIN location l ON l.frame_id = c.frame_id "
        "WHERE l.id = ? ORDER BY c.keyword, c.idx",
        (location_id,),
    ).fetchall()


def present_locations(con, frame_ids):
    """ŹRÓDŁO linku PROJEKCJI (krok 6) — dla zbioru frame_id KAŻDA OBECNA (`present=1`) location z
    `path`+`volume`+`drive_letter`+`size_bytes`. Rozszerza wzorzec `writeback_frame_targets` (już
    `present=1`) o `volume`/`drive_letter` (R#1: `base_rows` NIE nadaje się na cel linku - od D-V-9
    preferuje kopię obecną, ale gałąź powrotu ODDAJE `present=0` dla klatki, której wszystkie kopie
    zniknęły → `os.link` na nieistniejące źródło; brak `volume` → EXDEV nierozstrzygalny z góry) oraz o `size_bytes` (F2 redesignu: suma rozmiaru kopii po TEJ
    SAMEJ lokacji, którą wybiera plan — R#5). Frame BEZ obecnej kopii → wiersz z location_id NULL (silnik
    projekcji: `skipped`-kwarantanna). Wiele obecnych → wiele wierszy; silnik bierze pierwszą (D-P5).
    `base_rows` zostaje TYLKO do segmentów layoutu (object/filter/telescope). frame_ids jako TABLICA
    JSON (`json_each`, jeden param — §4). ORDER BY frame_id, location_id. Zwraca: frame_id,
    location_id, path, volume, drive_letter, size_bytes."""
    return con.execute(
        "SELECT f.id AS frame_id, l.id AS location_id, l.path, l.volume, l.drive_letter, l.size_bytes "
        "FROM frame f "
        "LEFT JOIN location l ON l.frame_id = f.id AND l.present = 1 "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "ORDER BY f.id, l.id",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def db_path_of(con):
    """Ścieżka pliku bazy z żywego połączenia (`PRAGMA database_list` → 'main'). Worker off-thread
    (writeback gridu, auto-DRY projekcji) otwiera po niej WŁASNE połączenie w swoim wątku — `con` nie
    przechodzi między wątkami (check_same_thread). `:memory:` → '' → seam wymusza tryb inline."""
    for _seq, name, file in con.execute("PRAGMA database_list"):
        if name == "main":
            return file
    return None


def base_rows(con, frame_ids):
    """Kolumny BAZOWE gridu (warstwa interpretacji NAD lustrem cards) dla zbioru frame_id. Location przez
    `MIN(id)` **SPOŚRÓD OBECNYCH**, z powrotem do dowolnej, gdy żadna nie jest obecna (D-V-9, decyzja
    Zdzinia 2026-08-14). `present` zostaje KOLUMNĄ, nie predykatem - i to nie jest odejście od F3, tylko
    jego dotrzymanie: klatka bez ANI JEDNEJ żywej kopii dalej pokazuje swój adres (gałąź powrotu) i dalej
    dostaje znacznik zniknięcia. Zmienia się wyłącznie klatka, która ma OBIE kopie: ekran przestaje
    pokazywać martwy adres tylko dlatego, że ten wjechał do bazy pierwszy.
    **Zmierzone `?mode=ro` na żywej bazie 2026-08-11 i 2026-08-14:** goły `MIN(id)` wskazywał martwy
    adres dla **128 masterów** (gotowe obrazy - adres w starym drzewie archiwum wjechał przed nowym,
    uporządkowanym) i robił to PO CICHU, bo znacznik zniknięcia wymaga `n_present == 0`, a te klatki
    mają żywą kopię. Kierunek odwrotny: 0 klatek. Zmiana dotyka 128 wierszy z 16 901 - reszta
    archiwum widzi dokładnie to, co przed nią.

    **KOSZT ZMIERZONY na pełnym zakresie** (bramka pakietu żądała liczby, nie oczekiwania): całe
    archiwum w jednym wywołaniu **76,7 ms → 109,3 ms**. To ~3% operacji `grid.refresh`, która na tym
    samym zbiorze trwa ~1000 ms i idzie pod nazwaną fazą zajętości. Wariant z grupowanym `LEFT JOIN`
    zamiast dwóch podzapytań zmierzył 92,6 ms i został ODRZUCONY: 17 ms nie kupuje dwóch dodatkowych
    złączeń ani niespójności z `n_present`, który stoi obok jako podzapytanie.

    **`id` NIESIE KOLEJNOŚĆ WJAZDU WPISU, NIE BIOGRAFIĘ ŚCIEŻKI** (bramka pakietu, Z6). Wiersz
    `location` nigdy nie jest kasowany (zero `DELETE FROM location` w `repo`), więc niższe `id` to
    rzeczywiście wcześniejszy wpis - ale `relocate_location` zmienia `path` W MIEJSCU, a
    `rebind_location` przepina wpis pod inną klatkę. `vanished_path` znaczy więc „ostatnia znana
    ścieżka najstarszego martwego wpisu", nie „pierwszy adres w historii obrazu".

    **`MIN`, NIE `MAX`, spośród martwych - decyzja, nie przypadek:** przy łańcuchu przeprowadzek
    A→B→C `MIN` odpowiada „gdzie to leżało NA POCZĄTKU", `MAX` - „skąd tu przyjechało". Populacja
    z więcej niż jednym martwym adresem jest dziś ZEROWA, więc pytanie jest teoretyczne; tooltip
    nazywa swój wybór wprost („pierwszy: …"), a przełączenie na `MAX` ma czekać na człowieka, który
    naprawdę o ten drugi adres zapyta.

    `n_present` = liczba obecnych lokalizacji (perspektywa „Duplikaty" = n_present > 1).
    `n_vanished` + `vanished_path` (MIN(id) spośród MARTWYCH) niosą HISTORIĘ PRZEPROWADZKI dla tooltipu
    (`grid._former_tip`): skoro klatka zna oba adresy, stary przestaje być śmieciem do ukrycia i staje się
    widoczną odpowiedzią na pytanie „gdzie to leżało wcześniej". Karmią TOOLTIP, nie nową kolumnę -
    z tego samego powodu, co `object_source` niżej.

    Teleskop przez config→telescope_canonical→kanon (jak `object_frames`). frame_ids jako
    tablica JSON (`json_each`). Zwraca W TEJ KOLEJNOŚCI: frame_id, kind, filetype, filter_canon,
    camera_model, telescope_label, telescop_canon, object_canon, object_raw, object_source,
    object_cleared_id, date_obs, exptime, path, present, last_verified_at, superseded_by, retired_at,
    n_present, n_vanished, vanished_path. Wiersze czyta się po NAZWIE (`sqlite3.Row`), ale kolejność
    w tym zdaniu ma zgadzać się z SELECT-em - rozjazd był zarzutem bramki 0809 i jest tańszy do
    naprawienia niż do wytłumaczenia następnej sesji.

    `object_source` i `object_cleared_id` KARMIĄ POLITYKĘ KOLUMNY (`object_cell`, R-S3-4), a NIE
    nową kolumnę na ekranie: `BASE_COLS` gridu zostaje bez zmian, więc podłoga okna się nie rusza
    (kanon minimalnego wspieranego ekranu). Kosztu nie ma — `frame` jest już w `FROM`.

    `superseded_by` JEST KOLUMNĄ Z TEGO SAMEGO POWODU, CO `present` (F3, decyzja Zdzinia 2026-08-09):
    klatka zastąpiona ZOSTAJE w gridzie i ma być WIDOCZNA JAKO ZASTĄPIONA — w każdej perspektywie,
    nie tylko we własnej. Bez niej wiersz wyglądał identycznie jak żywa klatka bez kopii, a jedyną
    różnicą było puste pole ścieżki, czyli brak informacji udawał informację.

    `last_verified_at` NA WIERSZU `present=0` JEST CHWILĄ ZNIKNIĘCIA: jedyną drogą zapisu `present=0`
    jest `repo.mark_location_vanished`, a ona stempluje tę kolumnę tym samym `now`, którym emituje
    `event(location.vanished)` (`repo.py`). Dla kopii OBECNEJ ta sama kolumna znaczy „ostatnio
    zweryfikowana" — interpretacja należy do wołającego, dlatego alias jest surowy, nie `vanished_at`."""
    return con.execute(
        "SELECT f.id AS frame_id, f.kind, f.filetype, f.filter_canon, "
        "       cam.model_canon AS camera_model, "
        "       t.label AS telescope_label, t.telescop_canon, "
        "       obj.canon AS object_canon, h.object_raw, f.object_source, f.object_cleared_id, "
        "       h.date_obs, h.exptime, loc.path, loc.present, loc.last_verified_at, f.superseded_by, "
        "       f.retired_at, "
        "       (SELECT COUNT(*) FROM location lp WHERE lp.frame_id = f.id AND lp.present = 1) AS n_present, "
        "       (SELECT COUNT(*) FROM location lv WHERE lv.frame_id = f.id AND lv.present = 0) AS n_vanished, "
        "       (SELECT lw.path FROM location lw WHERE lw.frame_id = f.id AND lw.present = 0 "
        "         ORDER BY lw.id LIMIT 1) AS vanished_path "
        "FROM frame f "
        "LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN telescope t ON t.id = tc.canon_id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "LEFT JOIN object obj ON obj.id = f.object_id "
        "LEFT JOIN location loc ON loc.id = COALESCE("
        "        (SELECT MIN(id) FROM location WHERE frame_id = f.id AND present = 1), "
        "        (SELECT MIN(id) FROM location WHERE frame_id = f.id)) "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "ORDER BY f.id",
        (json.dumps(list(frame_ids)),),
    ).fetchall()

# --- TODO-DŁUG (z kolejki sesji, dieta 2026-08-10; pełne brzmienia: archiwum aa) ---
# TODO-DŁUG(W-4): sort kolejki obiektów przy remisie sum jest stringowy (Caldwell 12 przed
#   Caldwell 3). Przy remisie sortuj naturalnie (rozbicie nazwy na człony liczbowe).
# TODO-DŁUG(P4-1): unresolved_reason to werdykt ZAMROŻONY - 11 stosów niosło no_object dobę po
#   nadaniu obiektów ręką. Kubełek liczyć ze STANU (obiekt jest => no_object nie ma prawa się
#   pokazać) albo gest zmieniający fakt sam proponuje przeliczenie (wzorzec taktu 3, b803b5d).
# TODO-DŁUG(R-S4-10): filetype IS NULL wypada z OBU kubełków bezimiennych (NULL IN/NOT IN dają
#   NULL), zostając w review_frame_ids - partycja pękłaby po cichu. Dziś nieosiągalne (tripwire).
