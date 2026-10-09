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
from horreum.lineage import RAW_FLAT_WINDOW_DAYS, raw_flats_for   # surowe flaty teczek wydania
from horreum.naming import header_dt
from horreum.repo import (INPLACE_ISOLATING_PHASES,   # fazy izolujące zapisu w miejscu (0022)
                          INPLACE_OPEN_PHASES,        # ...i ich podzbiór otwarty
                          absorbed_frame_ids,         # wchłonięte szkielety (AR-42)
                          normalize_note)             # postać treści uwagi z klingi (0032)
from horreum.resolve._coerce import _to_float, _to_int, _to_text
from horreum.resolve._text import norm_alnum
from horreum.resolve.frames import LIGHT_KINDS
from horreum.resolve.headers import (COPY_TESTIMONY_KEYWORDS, COPY_TESTIMONY_RULE, FAKTY_BIEZACE,
                                     copy_facts_state, copy_testimony)
from horreum.resolve.objects import CLEARABLE_OBJECT_SOURCES, WEAK_OBJECT_SOURCES
from horreum.resolve.paths import (STACK_KIND, STACKS_DIR, filter_folder_from_path,
                                   object_from_path)
from horreum.resolve.recipe import parse_master_path
from horreum.resolve.stack import read_testimony, signature_timestamp
from horreum.resolver import (NO_OBJECT_CARD_FILETYPES, alias_snapshot, forma_karty_object,
                              path_proposals, resolve_name, review_state)
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

    DRZEWO STOSÓW NAJPIERW (FC-4/D-V-9b): w układzie `STACKS\\<OBIEKT>\\<KONFIG>\\<FILTR>\\plik`
    obiektem jest segment po `STACKS`, a rodzic pliku to FILTR - dawna reguła dawała w podpowiedzi
    `⟨NoFilter⟩`/`⟨Ha⟩`/`⟨OIII⟩` dla 182 ze 193 stosów archiwum. Właścicielem tej reguły jest
    `resolve.paths.object_from_path(…, kind=STACK_KIND)`, bo to samo pytanie zadaje szczebel
    ścieżki resolvera; tutaj jest WOŁANA, nie powtórzona (SPOT - dwie kopie rozjechałyby się przy
    pierwszej zmianie układu drzewa, a podpowiedź mówiłaby co innego niż propozycja do potwierdzenia).

    POZA DRZEWEM STOSÓW: DZIADEK, NIE RODZIC, i to jest zmierzone, nie estetyczne: drzewo WBPP
    kończy się katalogiem `master`, więc rodzic brzmi tak samo u WSZYSTKICH stosów i nie rozróżnia
    niczego (`…\\A7R3_105_LMC\\master\\masterLight_….xisf`). Gdy `master` nie występuje, właściwą
    odpowiedzią jest rodzic — stąd warunek, a nie stałe piętro w górę.

    Powstało z firsthandu 0808: kubełek „bez nazwy, gotowe stosy" daje 18 wierszy, których nie da
    się odróżnić, bo nazwy plików generuje WBPP i sześć stosów LMC czyta się identycznie.
    Tożsamość siedzi WYŁĄCZNIE w tym segmencie ścieżki. JEDEN właściciel reguły, bo pytają o nią
    dwie powierzchnie (kolumna Obiekt w Zbiorach i lista drążenia w Przeglądzie obiektów) —
    dwie kopie rozjechałyby się przy pierwszej zmianie układu drzewa.

    KOTWICA NIE JEST FOLDEREM OBIEKTU: `STACKS\\plik.xisf` (plik wprost pod kotwicą) milczy tak
    samo jak litera dysku niżej - rodzic `STACKS` byłby podpowiedzią bez treści, udającą nazwę."""
    if not path:
        return None
    obiekt = object_from_path(str(path), kind=STACK_KIND)
    if obiekt:
        return obiekt
    czesci = [c for c in re.split(r"[\\/]", str(path)) if c]
    if len(czesci) < 2:
        return None
    rodzic = czesci[-2]
    if rodzic.strip().lower() == STACKS_DIR:
        return None
    if rodzic.lower() == "master" and len(czesci) >= 3:
        dziadek = czesci[-3]
        # KORZEŃ NIE JEST FOLDEREM OBIEKTU (bramka pakietu, zarzut 9): przy układzie
        # `X:\master\plik` dziadkiem jest litera dysku, więc kolumna pokazywałaby `⟨R:⟩` —
        # podpowiedź bez treści, udającą nazwę. Wtedy uczciwiej milczeć.
        return None if dziadek.endswith(":") else dziadek
    return rodzic


def hint_from_stacks_tree(path):
    """Czy podpowiedź `stack_folder` dla tej ścieżki pochodzi z drzewa `STACKS` - pytanie zdania
    podpowiedzi w gridzie. Ta sama reguła, którą `stack_folder` wybiera gałąź (SPOT): w drzewie
    stosów folder NIESIE nazwę i szczebel ścieżki ma propozycję; w układzie WBPP nie niesie."""
    return bool(path) and object_from_path(str(path), kind=STACK_KIND) is not None


OBJECT_CELL_STATES = ("canon", "cleared", "kind", "raw", "hint")
"""Stany komórki „Obiekt" — LUSTRO gałęzi `object_cell`, do bramki parytetu z katalogiem i18n.

Kolejność JEST kolejnością rozstrzygania w `object_cell` i to nie jest przypadek: `cleared` bije
`kind`, a `kind` bije `raw`, bo klatka może spełniać kilka warunków naraz, a powiedzieć ma tę
rzecz, która jest jej NAJŚWIEŻSZYM faktem i tłumaczy pusty facet obok."""

CLEARED_MARK = "↺"
"""Znacznik cofnięcia — TEN SAM, którym kolejka przeglądu znaczy wiersze cofnięte (paczka G3).
Jeden alfabet dla jednego faktu; drugi znak kazałby uczyć się dwa razy tego samego."""

RAW_MARK = "?"
"""Znacznik nazwy NIEROZPOZNANEJ (FC-8) — jedyny z czterech stanów niekanonicznych, który JEST
robotą do wzięcia.

Powód jest z pomiaru, nie z gustu: `kind` (kalibracja, recepta „nie poprawia się wcale") i `raw`
(nazwa nierozpoznana, recepta „popraw w pliku albo wskaż ręką") renderowały się ZNAK W ZNAK tak
samo - ta sama kursywa, ta sama szarość, oba bez znacznika - a rozróżniała je wyłącznie sąsiednia
kolumna „Rodzaj". Dwa stany o PRZECIWNYCH receptach wyglądały identycznie.

Znacznik dostaje `raw`, a nie `kind`, bo alfabet ma znaczyć ROBOTĘ: `↺` (ręka cofnęła), `⟨…⟩`
(podpowiedź ze ścieżki) i `?` (nie wiem, co to jest) niosą po jednym stanie, a stan BEZ znacznika
zostaje jeden i mówi „tu nie ma nic do zrobienia". Populacja `raw` w archiwum jest dziś ZERO
(zmierzone `?mode=ro` 2026-08-15: `kind` 2364, `canon` 14537, reszta 0), więc dzisiejszy ekran ta
zmiana nie rusza - zapala się przy pierwszym pliku z nazwą, której drabina nie rozpozna."""

HINT_MARK = ("⟨", "⟩")
"""Nawiasy PODPOWIEDZI ze ścieżki - trzeci znak alfabetu stanów, obok `CLEARED_MARK` i `RAW_MARK`.

Stała, a nie literał w f-stringu, bo alfabet ma być ROZŁĄCZNY i pilnuje tego bramka - a bramka
trzymająca własny egzemplarz glifu nie pilnuje niczego (bramka pakietu 0815, zarzut 5): zmiana
znaku w jednym miejscu zostawiłaby ją zieloną."""


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

    NAGROBEK POKAZUJE TO, CO ZDJĘŁA RĘKA (FC-1) — `object_cleared_canon` przed `object_raw`.
    Migracja 0017 dołożyła `frame.object_cleared_id` po to, żeby cofnięcie miało drogę powrotu, ale
    read-model tej pamięci nie czytał: firsthand zmierzył **411 z 417 nagrobków renderujących się
    ZNAK W ZNAK identycznie** (sam `↺`), choć baza pamiętała trzy różne obiekty — populacja
    DOMALOWANA na kopii, bo w archiwum nagrobków jest **zero** (akapit o `RAW_MARK` wyżej podaje
    komplet pomiaru; ta paczka zapala się dopiero przy pierwszym cofnięciu). Klatka bez zeznania
    w nagłówku - a takich jest większość, patrz akapit wyżej - nie miała w komórce ANI JEDNEJ
    litery, po której dałoby się poznać, czego dotyczy. Odwrotna kolejność (raw przed pamięcią)
    byłaby gorsza podwójnie: raw jest tym, co drabina ODRZUCIŁA, a pamięć tym, co ręka zdjęła.
    Nagrobek BEZ pamięci zostaje legalny (baza-dawca sprzed 0017, migracja 0017:29) i spada na raw -
    ale wtedy komórka mówi co innego niż w przypadku z pamięcią, więc TOOLTIP rozróżnia oba
    (`grid._cleared_tip`), zamiast twierdzić o nazwie z nagłówka, że to werdykt ręki.

    PODPOWIEDŹ ZE ŚCIEŻKI (`hint`) NIE UDAJE NAZWY: nawiasy kątowe odróżniają ją od kanonu, bo
    wzięcie „tyle wiem z folderu" za „tak się ten obiekt nazywa" byłoby gorsze niż pusta komórka.
    Tylko `master_light`, bo light z akwizycji ma własną drogę (szczebel ścieżki S2 PROPONUJE mu
    kanon). Nic z tego nie trafia do bazy: to warstwa PREZENTACJI, gest osi należy do człowieka.
    Od E3-1 stos w drzewie `STACKS` też dostaje propozycję szczebla ścieżki - podpowiedź czyta
    TEN SAM segment (`stack_folder` → `resolve.paths`), więc komórka i okno „Zatwierdź ze
    ścieżki…" mówią o tym samym folderze: komórka surowy tekst, okno kanon z drabiny nazwy.

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
        nazwa = row.get("object_cleared_canon") or raw       # FC-1: pamięć ręki bije zeznanie pliku
        return (f"{CLEARED_MARK} {nazwa}" if nazwa else CLEARED_MARK), "cleared"
    # STAN TŁUMACZY TEKST, więc bez tekstu nie ma czego tłumaczyć — i dlatego pytanie o ZEZNANIE
    # stoi PRZED pytaniem o rodzaj. Odwrotna kolejność dawała PUSTEJ komórce tooltip „kalibracja
    # obiektu nie ma z definicji" wszędzie tam, gdzie wiersz nie niesie `kind` (a nie niesie go
    # z każdego zapytania gridu) — czyli zdanie o rodzaju, którego ten wiersz nie zna. Złapała to
    # własna bramka tej paczki, nie recenzja.
    if raw:
        rodzaj = row.get("kind")
        if rodzaj is not None and rodzaj not in LIGHT_KINDS:
            return raw, "kind"                     # kalibracja: bez znacznika, bo nie ma tu roboty
        return f"{RAW_MARK} {raw}", "raw"          # FC-8: jedyny stan, który JEST robotą, ma znacznik
    if row.get("kind") == "master_light":
        folder = stack_folder(row.get("path"))
        if folder:
            return f"{HINT_MARK[0]}{folder}{HINT_MARK[1]}", "hint"
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


# ------------------------------------------------------------ stanowisko Z RĘKI (0027)
# Wejście gestu „Wskaż stanowisko…": klatki BEZ stanowiska (brak GPS albo GPS nieparsowalny) i ich
# druga połowa - klatki, którym stanowisko wskazała ręka (tryb ZMIANY i COFNIĘCIA). Lustro pary
# `config_review_frames`/`config_by_hand_frames`: populacje rozłączne, jedna droga zapisu.
# Klatka ZASTĄPIONA i WYCOFANA wypadają z obu list z powodu jak tam (robota przeszła na następczynię
# albo ręka pliku już nie szuka). Rodzaju nie odsiewamy - oś jest KIND-AGNOSTIC.


def observatory_review_frames(con):
    """Klatki bez stanowiska - jeden wiersz na klatkę: frame_id, kind, filetype, path (pierwsza
    OBECNA kopia albo NULL), observatory_label (zawsze NULL - kolumna dla wspólnego składacza)."""
    return con.execute(
        "SELECT f.id AS frame_id, f.kind, f.filetype, l.path, NULL AS observatory_label "
        "FROM frame f "
        "LEFT JOIN location l ON l.id = (SELECT MIN(id) FROM location "
        "                                WHERE frame_id = f.id AND present = 1) "
        "WHERE f.observatory_id IS NULL "
        "  AND f.superseded_by IS NULL "
        "  AND f.retired_at IS NULL "
        "ORDER BY l.path, f.id").fetchall()


def observatory_by_hand_frames(con):
    """Klatki ze stanowiskiem od RĘKI - kolumny jak `observatory_review_frames`, a `observatory_label`
    niesie to, CO DZIŚ STOI (nazwa kanonu albo jego współrzędne): user wraca tu po to, żeby zobaczyć
    własny poprzedni wybór. Etykietę składa SQL, bo kanon rozwiązuje widok `observatory_canonical`."""
    return con.execute(
        "SELECT f.id AS frame_id, f.kind, f.filetype, l.path, "
        "       COALESCE(o.name, printf('%.4f, %.4f', o.lat, o.lon)) AS observatory_label "
        "FROM frame f "
        "JOIN observatory_canonical oc ON oc.id = f.observatory_id "
        "JOIN observatory o ON o.id = oc.canon_id "
        "LEFT JOIN location l ON l.id = (SELECT MIN(id) FROM location "
        "                                WHERE frame_id = f.id AND present = 1) "
        "WHERE f.observatory_source IS NOT NULL "
        "  AND f.superseded_by IS NULL "
        "  AND f.retired_at IS NULL "
        "ORDER BY l.path, f.id").fetchall()


def _grupuj_stanowiska_po_folderze(rows):
    """Grupy **folder** dla gestu stanowiska (SPOT dla obu list). Jednostką jest folder, nie
    folder × kamera jak przy zestawie: stanowisko nie zależy od korpusu, a sesja zdjęciowa leży
    w jednym folderze. `kinds` = `[("rodzaj/format", n)]` malejąco - okno pokazuje, że w grupie
    siedzi np. kalibracja obok RAW-ów; `observatory_label` grupy = wspólna etykieta albo None, gdy
    folder ma klatki pod różnymi stanowiskami."""
    grupy = {}
    for r in rows:
        folder = os.path.dirname(r["path"]) if r["path"] else None
        g = grupy.get(folder)
        if g is None:
            g = grupy[folder] = {"folder": folder, "observatory_label": r["observatory_label"],
                                 "n_frames": 0, "frame_ids": [], "_kinds": {}}
        elif g["observatory_label"] != r["observatory_label"]:
            g["observatory_label"] = None
        klucz = f'{r["kind"]}/{r["filetype"] or "?"}'
        g["_kinds"][klucz] = g["_kinds"].get(klucz, 0) + 1
        g["n_frames"] += 1
        g["frame_ids"].append(r["frame_id"])
    for g in grupy.values():
        g["kinds"] = sorted(g.pop("_kinds").items(), key=lambda kn: (-kn[1], kn[0]))
    return list(grupy.values())


def observatory_review_groups(con):
    """Klatki bez stanowiska pogrupowane po folderze - wejście okna w trybie NADANIA."""
    return _grupuj_stanowiska_po_folderze(observatory_review_frames(con))


def observatory_by_hand_groups(con):
    """Klatki ze stanowiskiem od ręki po folderze - wejście okna w trybie ZMIANY i COFNIĘCIA."""
    return _grupuj_stanowiska_po_folderze(observatory_by_hand_frames(con))


def observatory_site_label(con, observatory_id):
    """Etykieta stanowiska do zdania gestu: `(canon_id, nazwa kanonu | None)`. Liczona przez
    kanon, bo user widzi na liście osi kanon - członek scalony nie ma tam własnego wiersza."""
    r = con.execute(
        "SELECT o.id, o.name FROM observatory_canonical oc JOIN observatory o ON o.id = oc.canon_id "
        "WHERE oc.id = ?", (observatory_id,)).fetchone()
    return (r["id"], r["name"]) if r is not None else (observatory_id, None)


def observatory_live_frames(con, observatory_id):
    """Ile ŻYWYCH klatek (bez `superseded_by`) stoi pod kanonem tego stanowiska - zdanie cofnięcia
    mówi, że stanowisko zostało puste (stanowisko świadomie zostaje: planer go potrzebuje)."""
    return con.execute(
        "SELECT count(*) FROM frame f JOIN observatory_canonical oc ON oc.id = f.observatory_id "
        "WHERE oc.canon_id = (SELECT canon_id FROM observatory_canonical WHERE id = ?) "
        "AND f.superseded_by IS NULL", (observatory_id,)).fetchone()[0]


def frame_ids_by_path_like(con, pattern):
    """`frame_id` klatek z OBECNĄ kopią pod ścieżką `LIKE pattern` (selektor CLI `--path-like`).
    Kopia nieobecna nie wskazuje klatki - gest dotyczy tego, co user widzi na dysku."""
    return {r[0] for r in con.execute(
        "SELECT DISTINCT frame_id FROM location WHERE present = 1 AND path LIKE ?",
        (pattern,)).fetchall()}


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
    klatek po filtrze znika z widoku (poprawne - filtr zawęża). Zwraca: id, canon, catalog, frame_count.
    Porządek NATURALNY (`natural_key`, W-9): `NGC 891` przed `NGC 7000`, nie po znakach."""
    return _po_nazwie_naturalnie(con.execute(
        "SELECT o.id, o.canon, o.catalog, COUNT(f.id) AS frame_count "
        "FROM object o "
        "JOIN frame f ON f.object_id = o.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "WHERE f.kind IN ('light','master_light') "
        "  AND (? IS NULL OR tc.canon_id = ?) "
        "  AND (? IS NULL OR f.camera_id = ?) "
        "  AND (? IS NULL OR f.filter_canon = ?) "
        "GROUP BY o.id",
        (telescope_id, telescope_id, camera_id, camera_id, filter_canon, filter_canon),
    ).fetchall(), "canon")


def library_exposure(con, *, telescope_id=None, camera_id=None, filter_canon=None):
    """Naświetlenie per (obiekt, filtr) pod TYMI SAMYMI filtrami osi co `library_objects` - godziny
    materiału w bibliotece obiektów. Kształt wierszy jak `object_exposure` (object_id, filter_canon,
    secs, n_null), więc sumę, format i rozbicie per filtr robi `portfolio` (SPOT).

    Reguły rachunku jak w `object_exposure`: wyłącznie `kind='light'` (EXPTIME mastera to czas
    ZINTEGROWANY), klatka zastąpiona nie dolicza sekund, light bez `header` wypada JOIN-em,
    `exptime IS NULL` liczone jawnie w `n_null`. Filtry osi jak w bibliotece (teleskop przez
    `telescope_canonical`).

    ⚠ ROZJAZD Z `library_objects` JEST ŚWIADOMY, jak w `object_exposure`: kolumna „Klatki" liczy
    `light` ORAZ `master_light`, także klatki zastąpione, a godziny - wyłącznie lighty niezastąpione
    z nagłówkiem. Master doliczony do godzin podwoiłby rachunek (jego EXPTIME to suma subów), a duch
    zastąpionej klatki doliczałby ekspozycję, którą liczy już jego następczyni. Obiekt z samymi
    masterlightami ma więc klatki i nie ma wiersza tutaj; light bez nagłówka liczy się w „Klatkach",
    a tu nie ma go ani w `secs`, ani w `n_null`."""
    return con.execute(
        "SELECT f.object_id, f.filter_canon, "
        "       SUM(h.exptime)         AS secs, "
        "       SUM(h.exptime IS NULL) AS n_null "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "WHERE f.kind = 'light' AND f.object_id IS NOT NULL "
        "  AND f.superseded_by IS NULL "
        "  AND (? IS NULL OR tc.canon_id = ?) "
        "  AND (? IS NULL OR f.camera_id = ?) "
        "  AND (? IS NULL OR f.filter_canon = ?) "
        "GROUP BY f.object_id, f.filter_canon "
        "ORDER BY f.object_id, secs DESC",
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


_CZLONY_LICZBOWE = re.compile(r"(\d+)")


def natural_key(s):
    """Klucz NATURALNY nazwy: człony liczbowe porównywane jako liczby, tekst bez wielkości liter
    (W-4). Czysta funkcja, zero SQL, zero Qt.

    Istnieje, bo nazwy katalogowe niosą numer, a porządek znaków go nie widzi: `Caldwell 12` stoi
    stringowo przed `Caldwell 3`, `NGC 700` przed `NGC 7000` - kolejność, której oko nie czyta
    jako porządek. SQLite naturalnego sortu nie ma, więc klucz liczy wołający po stronie Pythona.

    `re.split` z grupą przechwytującą zwraca człony NAPRZEMIENNIE, zawsze od tekstu (także
    pustego): tekst, liczba, tekst… Pozycja parzysta jest więc zawsze tekstem, a nieparzysta
    liczbą, i dwa klucze porównują się pozycja w pozycję typ z typem - bez `TypeError` między
    `int` a `str`, bez znaczników typu w krotce. Klucz jest ślepy na wielkość liter, więc dwie
    RÓŻNE nazwy mogą dać klucz równy (`NGC 700` / `ngc 700`) - wołający, który potrzebuje
    porządku całkowitego, dokłada surową nazwę jako człon następny."""
    return tuple(int(czlon) if i % 2 else czlon.casefold()
                 for i, czlon in enumerate(_CZLONY_LICZBOWE.split(s)))


def _po_nazwie_naturalnie(wiersze, pole):
    """Wiersze posortowane naturalnie po polu `pole` (W-9); surowa nazwa jako człon następny
    daje porządek całkowity (`natural_key` jest ślepy na wielkość liter)."""
    return sorted(wiersze, key=lambda r: (natural_key(r[pole] or ""), r[pole] or ""))


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
      - `path_proposed_stack_*`: bliźniak powyższego dla GOTOWYCH STOSÓW z drzewa `STACKS` (E3-1),
        PODZBIÓR `nameless_stacks_count`, tak samo poza partycją. Osobna para, bo wiersz stoi pod
        kubełkiem stosów, a „z tego" ma liczyć wyłącznie jego populację (`PathProposal.stack_tree`).

    Zwraca dict: {object_review: [Row(object_raw, cleared, n, total)], nameless_count: int,
    nameless_cleared_count: int, nameless_raw_count: int, nameless_raw_cleared_count: int,
    nameless_stacks_count: int, nameless_stacks_cleared_count: int,
    path_proposed_names: int, path_proposed_frames: int,
    path_proposed_stack_names: int, path_proposed_stack_frames: int,
    config_review_count: int, headerless_count: int, unreadable_count: int}."""
    object_review = sorted(con.execute(
        "SELECT h.object_raw AS object_raw, "
        "       (f.object_source IS 'user_cleared') AS cleared, COUNT(*) AS n, "
        "       SUM(COUNT(*)) OVER (PARTITION BY h.object_raw) AS total "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind IN ('light','master_light') AND f.object_id IS NULL "
        "  AND f.superseded_by IS NULL "
        "  AND f.retired_at IS NULL "
        "  AND h.object_raw IS NOT NULL "
        "GROUP BY h.object_raw, cleared"
    ).fetchall(),
        # KOLEJNOŚĆ PROWADZI NAZWĄ, NIE POŁÓWKĄ (R-S3-2). `ORDER BY n DESC` sortował POŁÓWKAMI,
        # więc obie połowy tej samej nazwy rozdzielał obcy kubełek: zmierzone `LDN 1174 · 9` →
        # `IC 1805 · 7` → `LDN 1174 · 5 · cofnięte ręką`. Przy 42 obiektach dzieli je cały ekran,
        # a user „załatwia LDN 1174" i zostawia drugą połówkę, nie wiedząc, że istnieje.
        # Klucz pierwszy = SUMA obu połówek (okno nad agregatem, kolumna `total` - pozycja waży
        # tym, ile roboty niesie NAZWA), klucz drugi = nazwa, więc połówki zawsze stoją obok siebie;
        # `cleared` na końcu trzyma nietkniętą PRZED cofniętą, bo podwiersz ma iść pod swoim wierszem.
        #
        # REMIS SUM ROZSTRZYGA KLUCZ NATURALNY NAZWY (W-4), nie porządek znaków: stringowo
        # `Caldwell 12` stał przed `Caldwell 3`, a `NGC 700` przed `NGC 7000` w kolejności, której
        # oko nie czyta jako porządek. SQLite naturalnego sortu nie ma, więc sortuje Python - i SAM
        # (bez `ORDER BY` w literale: dwa miejsca na jedną regułę rozjechałyby się przy pierwszej
        # zmianie). Surowa nazwa stoi ZA kluczem naturalnym, bo ten jest ślepy na wielkość liter:
        # `NGC 700` i `ngc 700` to dwie pozycje GROUP BY o równym kluczu, a bez tego członu ich
        # połówki przeplotłyby się po `cleared` - czyli wróciłby defekt R-S3-2 inną drogą.
        key=lambda r: (-r["total"], natural_key(r["object_raw"]), r["object_raw"], r["cleared"]))
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
    # Dwie populacje propozycji (E3-1), każda PODZBIOREM swojego kubełka: RAW-owe lighty pod RAW-em,
    # stosy z drzewa `STACKS` pod stosami. Jedna suma pod RAW-em kłamałaby „z tego" o stosach.
    try:
        propozycje = path_proposals(con)        # PODZBIORY kubełków RAW i stosów, poza partycją
        raw_p = [p for p in propozycje if not p.stack_tree]
        stos_p = [p for p in propozycje if p.stack_tree]
        prop_names, prop_frames = len(raw_p), sum(p.n_frames for p in raw_p)
        prop_s_names, prop_s_frames = len(stos_p), sum(p.n_frames for p in stos_p)
    except ValueError:
        prop_names = prop_frames = prop_s_names = prop_s_frames = None
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
            "path_proposed_stack_names": prop_s_names,
            "path_proposed_stack_frames": prop_s_frames,
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

    FORMAT NIEZNANY (`filetype IS NULL`) NALEŻY TUTAJ (R-S4-10) - stąd `COALESCE(f.filetype, '')`.
    `NO_OBJECT_CARD_FILETYPES` jest ZAMKNIĘTYM zbiorem formatów, o których WIADOMO, że karty nie
    mają; o formacie nieznanym tego nie wiadomo, więc jego drogą naprawy jest karta albo ręka, jak
    u każdego lighta. Goły `NOT IN` dawał dla NULL-a NULL, lustrzany `IN` w `nameless_raw_frames`
    też: klatka wypadała z OBU kubełków, zostając w `review_frame_ids`, i partycja `review_queue`
    pękała po cichu. `IN` po stronie RAW zostaje bez `COALESCE` - NULL nie pasuje tam nigdy
    i tak ma być. Dziś populacja 0 (`scan.ingest_record` zawsze liczy format), więc to tripwir.
    Lustro rdzenia (`resolver.nameless_lights`) niesie ten sam zapis, bo równość obu pinuje test.

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
    filetype, kind, date_obs, telescope_label, telescop_canon, camera_model, location_id, path,
    n_present.

    `kind` wchodzi do WYNIKU jak w bliźniaku `nameless_stack_frames`: dialog „Napraw nagłówek…"
    wybiera po nim drzewo świadka folderu (`resolver.path_proposal(…, kind=…)`), a oba drążenia
    karmią to samo okno, więc mają nieść tę samą kolumnę."""
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
        "WHERE f.kind = 'light' AND f.object_id IS NULL "
        "  AND f.superseded_by IS NULL "
        "  AND f.retired_at IS NULL "
        "  AND h.object_raw IS NULL "
        "  AND COALESCE(f.filetype, '') NOT IN (SELECT value FROM json_each(?)) "
        "  AND (f.object_source IS 'user_cleared') = ? "
        "ORDER BY l.path, f.id",
        (json.dumps(list(NO_OBJECT_CARD_FILETYPES)), int(cleared))
    ).fetchall()


def nameless_raw_frames(con, cleared=False):
    """Drążenie kubełka „bez nazwy, format bez karty (RAW)" (S4) — bliźniak `nameless_frames`
    o jednym członie różnicy: `filetype IN NO_OBJECT_CARD_FILETYPES` zamiast
    `COALESCE(filetype, '') NOT IN` (format nieznany zostaje po tamtej stronie - R-S4-10).

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
                                # właściciel reguły `label → telescop_canon`: oś bez nazwy usera mówi
                                # kanonem z nagłówka, nie milczy („dziś: —” przy zestawie wskazanym)
                                "telescope_label": telescope_label(r),
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
    path, present, unreadable_since, kind, reason.

    TEN SAM ZAKRES KLATEK CO LICZNIK KUBEŁKA (`resolver.review_state.unreadable`): klatka zastąpiona
    albo wycofana nie wchodzi. Kubełek jest listą ROBOTY, a robotę zastąpionej przejęła następczyni,
    wycofanej zamknęła ręka (ten sam argument, co przy `G2-6d`). Bez tego predykatu drążenie
    pokazywało kopie klatek, których licznik wiersza nie liczył - „1 klatka", a pod kliknięciem
    dwie różne.

    `kind` (`'io'|'parse'|'db'|None`) i `reason` („Typ: opis") czytamy z KOLUMN kopii (P4-2,
    `location.unreadable_kind`/`unreadable_reason`) - kolumna jest JEDYNYM właścicielem tego faktu.
    Do P4-2 powód szukano w dzienniku, ostatnim `frame.review` po parze `sha1:` + `payload.path`,
    i to źródło gubiło się dokładnie tam, gdzie powód był najbardziej potrzebny: payload trzyma
    ścieżkę z CHWILI awarii, więc kopia przemianowana po oznaczeniu traciła powód, a rodzaju awarii
    dziennik nie niósł wcale. Stan przeżywa przemianowanie, bo `path` i powód mieszkają w jednym
    wierszu. `kind` `None` = rodzaj nieznany: wiersz sprzed 0019 ALBO wyjątek bez kodu systemu,
    którego nie dało się rozstrzygnąć; `None` w obu = wiersz sprzed 0019 (powierzchnia pokazuje
    wtedy myślnik `copy.no_reason`)."""
    return con.execute(
        "SELECT l.frame_id, f.sha1_data, l.volume, l.path, l.present, l.unreadable_since, "
        "       l.unreadable_kind AS kind, l.unreadable_reason AS reason "
        "FROM location l JOIN frame f ON f.id = l.frame_id "
        "WHERE l.unreadable_since IS NOT NULL "
        "AND f.superseded_by IS NULL AND f.retired_at IS NULL "
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
    return _po_nazwie_naturalnie(con.execute(
        "SELECT id, canon FROM object WHERE canon IN (SELECT value FROM json_each(?))",
        (json.dumps(list(canons)),),
    ).fetchall(), "canon")


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
    datetime (granice liczy `filter_engine.night_bounds`); klatka bez header/date_obs nie wpada.
    `rel_camera` = `frame.camera_id` (liść zestawu w Znajdź, bez grupy w listwie)."""
    if kind == "rel_object":
        cur = con.execute("SELECT id FROM frame WHERE object_id = ?", (p1,))
    elif kind == "rel_filter":
        cur = con.execute("SELECT id FROM frame WHERE filter_canon = ?", (p1,))
    elif kind == "rel_channel":
        cur = con.execute("SELECT id FROM frame WHERE channel = ?", (p1,))
    elif kind == "rel_kind":
        cur = con.execute("SELECT id FROM frame WHERE kind = ?", (p1,))
    elif kind == "rel_camera":
        # Kamera klatki, nie configu: `zestaw:` Znajdź składa teleskop (facet) z tym liściem,
        # a klatka bez configu (review) też niesie swoją kamerę.
        cur = con.execute("SELECT id FROM frame WHERE camera_id = ?", (p1,))
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
    JOIN-em (kalibracja bez obiektu - poprawnie poza listą). Porządek naturalny po canon (lista
    pod szukajkę, W-9). Zwraca: id, canon, n."""
    return _po_nazwie_naturalnie(con.execute(
        "SELECT o.id, o.canon, COUNT(*) AS n "
        "FROM frame f JOIN object o ON o.id = f.object_id "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "GROUP BY o.id",
        (json.dumps(list(frame_ids)),),
    ).fetchall(), "canon")


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


def alias_header_forms(con):
    """Mapa `alias_norm → brzmienie z nagłówka` dla aliasów, które przyszły z karty `OBJECT` (AR-15).

    `object_alias` trzyma wyłącznie klucz (`ELEPHANTSTRUNKNEBULA`, `KSIEZYC`), a czytelne brzmienie
    leży w tym samym miejscu, z którego reszta UI pokazuje nazwę obiektu z pliku: `header.object_raw`.
    Klucz zostaje kluczem - ta mapa służy wyłącznie do pokazania aliasu, niczego nie dopasowuje.

    Forma = brzmienie NAJCZĘSTSZE wśród zeznań o tym kluczu (tak user podpisuje klatki), remis
    rozstrzyga pierwsze spotkane (`MIN(frame_id)`) - deterministycznie, bez skaczącej etykiety.
    Normalizacja `norm_alnum` w Pythonie, bo SQL jej nie zna; zakres = klucze obecne w `object_alias`.
    Alias bez zeznania (gest ręki na RAW, wpis słownika) w mapie nie ma wpisu."""
    klucze = {r[0] for r in con.execute("SELECT alias_norm FROM object_alias")}
    if not klucze:
        return {}
    najlepsze = {}
    for raw, n, pierwsza in con.execute(
            "SELECT object_raw, COUNT(*) AS n, MIN(frame_id) AS pierwsza FROM header "
            "WHERE object_raw IS NOT NULL GROUP BY object_raw").fetchall():
        klucz = norm_alnum(str(raw))
        if klucz not in klucze:
            continue
        ranga = (-n, pierwsza)
        if klucz not in najlepsze or ranga < najlepsze[klucz][0]:
            najlepsze[klucz] = (ranga, str(raw).strip())
    return {k: forma for k, (_r, forma) in najlepsze.items()}


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


def facet_channels(con, frame_ids):
    """Kubełki facetu Kanał: `frame.channel` (0028, kanał kamery kolorowej z nazwy stosu) w zbiorze
    + liczność; JAWNIE `IS NOT NULL` (F4R#10) - mono, obraz pełnokolorowy i light kanału nie mają
    i kubełka „(bez kanału)" nie dostają. Porządek STAŁY R, G, B (kolejność kanałów obrazu, nie
    liczności: trzy kanały jednej sesji mają zwykle tę samą liczbę i sortowanie po `n` tasowałoby
    je między przeładowaniami). Zwraca: channel, n."""
    return con.execute(
        "SELECT channel, COUNT(*) AS n FROM frame "
        "WHERE channel IS NOT NULL "
        "  AND id IN (SELECT value FROM json_each(?)) "
        "GROUP BY channel ORDER BY instr('RGB', channel)",
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
    zarówno licznik Porządków (`tasks_state`), jak i trim gridu - jak `dup_frame_ids`. Zwraca set[int].

    KLATKA ZASTĄPIONA WYPADA (G2-6d) z tego samego powodu, co wycofana: perspektywa jest listą
    ROBOTY, a jej gestem jest wycofanie - klinga (`repo._retire_verdict`) klatkę zastąpioną
    ODRZUCA, bo jej treść niesie następczyni. Bez guardu powierzchnia pokazywała klatkę, której
    jedyny gest tej listy nie zamknie. Stan jest osiągalny, nie hipotetyczny: `repo.mark_superseded`
    odmawia wyłącznie przy kopii OBECNEJ, więc „zastąpiona z martwą kopią" powstaje zwykłą drogą.
    Guard dostają za darmo wszyscy trzej konsumenci predykatu (trim gridu, licznik Porządków
    i `frames_without_copy` w podsumowaniu passa obecności), a klatka nie znika z oczu - ma własną
    perspektywę „Zastąpione" (`superseded_frame_ids`). Ten sam guard niosą od G2-5d
    `delta_report` i `LightClosure`."""
    return {int(r[0]) for r in con.execute(
        "SELECT f.id FROM frame f "
        "WHERE f.retired_at IS NULL "
        "  AND f.superseded_by IS NULL "
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
    „Zniknięte" i zamienił listę „nic nie zginęło" w listę „poszukaj plików". Zastąpiona wypada,
    bo jej historię zamknęła następczyni (a z obecną kopią istnieć nie powinna: skan gasi wtedy
    oznaczenie, `repo.clear_superseded`).

    WYCOFANA ZOSTAJE - świadomie (D-V-9d). Klatka wycofana, której plik wrócił, a jedna z kopii
    dalej leży martwa, JEST klatką z brakującą kopią: fakt „kopia zniknęła" jest prawdziwy
    niezależnie od gestu ręki. Guard `retired_at IS NULL` wycinał ją, a tooltip „wcześniejszy
    adres" (`grid._former_tip`) ją pokazywał - dwie powierzchnie opisywały dwa różne zbiory.
    Wiersz tłumaczy się na ekranie własnym znacznikiem wycofania w komórce ścieżki, a licznik
    Porządków czyta ten sam predykat, więc liczba i lista liczą to samo.

    Zwraca set[int]."""
    return {int(r[0]) for r in con.execute(
        "SELECT f.id FROM frame f "
        "WHERE f.superseded_by IS NULL "
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

    WCHŁONIĘTY SZKIELET NIE JEST ZASTĄPIENIEM (AR-42, `repo.absorbed_frame_ids`): plik spod jego
    ścieżki wyzdrowiał, treść się nie zmieniła, a obejrzeć nie ma czego - klatka bez zeznania nie
    niesie ani jednej wartości. Ogniwo zostaje (trzyma szkielet poza kubełkami roboty), perspektywa
    pokazuje wyłącznie podmiany treści.

    JEDEN właściciel predykatu dla licznika Porządków i trimu gridu — jak `vanished_frame_ids`
    i `dup_frame_ids`. Zwraca set[int]."""
    return {int(r[0]) for r in con.execute(
        "SELECT f.id FROM frame f WHERE f.superseded_by IS NOT NULL"
    ).fetchall()} - absorbed_frame_ids(con)


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
    to samo; por. `base_rows` n_present). Zwraca set[int].

    KLATKA WYCOFANA I ZASTĄPIONA WYPADAJĄ (G2-10d) - ta sama figura, co `G2-6d` w
    `vanished_frame_ids`: perspektywa jest listą ROBOTY („która kopia zbędna"), a klatka wycofana
    ma jedną robotę pierwszeństwa - rozstrzygnąć werdykt ręki, którego przesłanka upadła. Stan
    jest osiągalny zwykłą drogą: wycofanie wymaga braku obecnej kopii w chwili zapisu, a re-skan
    potrafi potem przywrócić DWIE. Klatka nie znika z oczu: prowadzi do niej wiersz Porządków
    „Wycofane, a plik wrócił" (`retired_conflict_frame_ids`). Zastąpiona z obecnymi kopiami
    istnieć nie powinna (skan gasi oznaczenie, `repo.clear_superseded`; inwariant
    `audit.supersede_invariants` liczy ją jako naruszenie) - guard stoi, żeby przy takim
    naruszeniu „Duplikaty" nie podsuwały gestu na klatce, której treść niesie następczyni,
    i żeby trzy predykaty żywotności miały jeden kształt. Licznik Porządków czyta ten predykat."""
    return {int(r[0]) for r in con.execute(
        "SELECT l.frame_id FROM location l JOIN frame f ON f.id = l.frame_id "
        "WHERE l.present = 1 AND f.retired_at IS NULL AND f.superseded_by IS NULL "
        "GROUP BY l.frame_id HAVING COUNT(*) > 1"
    ).fetchall()}


# POLA, W KTÓRYCH KOPIE JEDNEJ KLATKI MOGĄ MÓWIĆ RÓŻNIE (0021) - kolumna `location` → etykieta.
# Etykietą zeznania jest nazwa KEYWORDA z pliku (fakt domenowy, nie napis UI - D-L3), a faktów
# obrazów - klucz sentinelowy `COPY_IMAGES`, który powierzchnia tłumaczy sama. Kolejność = kolejność
# pokazywania w podpowiedzi.
COPY_IMAGES = "images"
_COPY_DIVERGENCE_FIELDS = (*COPY_TESTIMONY_KEYWORDS,
                           ("image_count", COPY_IMAGES), ("image_roles", COPY_IMAGES))

# POLA Z NAZWY I ŚCIEŻKI KOPII (AR-1) - klucze sentinelowe jak `COPY_IMAGES`, tłumaczy je
# powierzchnia. Kolejność = kolejność pokazywania, po polach zeznania i obrazach.
COPY_FLATGRP = "flatgrp"
COPY_NAME_FILTER = "name_filter"
COPY_FILTER_DIR = "filter_dir"
COPY_NAME_FIELDS = (COPY_FLATGRP, COPY_NAME_FILTER, COPY_FILTER_DIR)


def copy_name_facts(path):
    """Fakty NAZWY i ŚCIEŻKI jednej kopii - `{klucz sentinelowy: surowy tekst albo None}`. Czysta
    funkcja; jedna derywacja dla porównania (`copy_divergence`) i dla wartości w podpowiedziach.
    Parserów tu nie ma: tokeny nazwy daje wzorzec assetu (`recipe.parse_master_path`, grupy
    `flatgrp`/`filter`), folder filtra - reguła pozycyjna (`paths.filter_folder_from_path`)."""
    nazwa = parse_master_path(path)
    return {COPY_FLATGRP: nazwa.get("flatgrp"),
            COPY_NAME_FILTER: nazwa.get("filter_name"),
            COPY_FILTER_DIR: filter_folder_from_path(path)}


def present_copy_facts(con, frame_ids):
    """OBECNE kopie klatek z ich faktami z nagłówka (0021) - jedno wejście dla predykatu Porządków
    (`copy_conflict_frame_ids`) i dla podpowiedzi „×N" w Zbiorach, więc liczba wiersza i opis
    pod kursorem czytają ten sam stan. frame_ids jako TABLICA JSON (`json_each`, jeden param).
    ORDER BY frame_id, id - kolejność kopii jest kolejnością WJAZDU wpisu, ta sama, którą
    `base_rows` wybiera adres pokazywany w komórce. Zwraca: frame_id, location_id, path,
    image_count, image_roles, hdr_filter, hdr_imagetyp, hdr_object, hdr_telescop, hdr_instrume,
    hdr_exptime, hdr_xbinning, hdr_date_obs, hdr_hash, hdr_rule."""
    return con.execute(
        "SELECT l.frame_id, l.id AS location_id, l.path, l.image_count, l.image_roles, "
        "       l.hdr_filter, l.hdr_imagetyp, l.hdr_object, l.hdr_telescop, l.hdr_instrume, "
        "       l.hdr_exptime, l.hdr_xbinning, l.hdr_date_obs, l.hdr_hash, l.hdr_rule "
        "FROM location l "
        "WHERE l.present = 1 AND l.frame_id IN (SELECT value FROM json_each(?)) "
        "ORDER BY l.frame_id, l.id",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def copy_divergence(copies):
    """Rozjazd zeznań KOPII jednej klatki - czysta funkcja, zero SQL. `copies` = wiersze
    `present_copy_facts` jednej klatki. Zwraca `{location_id: (etykieta, …)}` - pola, w których
    kopie się NIE ZGADZAJĄ, przypięte do KAŻDEJ kopii (każda pokaże w nich własną wartość); pusty
    słownik = kopie mówią to samo.

    JEDEN WŁAŚCICIEL REGUŁY dla dwóch wołających o różnych stawkach: wiersz Porządków pyta, CZY
    klatka należy do listy, podpowiedź „×N" - CO i gdzie się różni. Reguła w Pythonie, nie w SQL,
    z tego samego powodu co `lineage_reason_stale`: literału nie da się współdzielić, a druga
    siedziba reguły rozjechałaby się przy pierwszym nowym polu.

    PORÓWNUJEMY WYŁĄCZNIE KOPIE Z ZEBRANYM ZEZNANIEM (`hdr_hash` niepusty). Kopia bez faktów nie
    mówi „inaczej" - mówi „nie wiem", a lista rozjazdów ma nieść wyłącznie rozjazd DOWIEDZIONY.
    Mniej niż dwie takie kopie = nie ma czego z czym porównać.

    ZEZNANIE INNEJ REGUŁY KOERCJI TO TEŻ „NIE WIEM" (0025, AR-33): kopia, której `hdr_rule` nie jest
    bieżącym `COPY_TESTIMONY_RULE` (NULL - reguła nieznana, albo inna), wypada z porównania jak kopia
    bez faktów. Dwie kopie zebrane różnymi rzutami mogą różnić się samym rzutem (`'1.34 '` obok
    `'1.34'`), czyli rozjazdem, którego w plikach nie ma - a lista ma nieść rozjazd DOWIEDZIONY.
    Nie porównujemy też kopii starej reguły między sobą: klatka o kopiach mieszanych dostawałaby
    werdykt cząstkowy, migający w miarę postępu uzupełnienia. Kopię reguły starszej licznik „nie
    wiem" widzi jako kandydata sterownika (`scan.copy_facts_candidates`), a najbliższa Dostawa
    dociąga ją regułą bieżącą - wtedy wraca do porównania. Kopię reguły NOWSZEJ niż kod licznik też
    widzi (tryb `porownywalne`), ale sterownik jej nie nadpisuje - stan rozstrzyga `copy_facts_state`.

    Wartość obecna obok brakującej (NULL) JEST rozjazdem: nagłówek, który zeznaje `OBJECT`, i nagłówek,
    który go nie ma, mówią o klatce różne rzeczy. Porównanie idzie po wartościach PO koercji
    (`copy_testimony`), więc XISF-owy tekst i FITS-owa liczba tego samego pomiaru nie rozjeżdżają się.

    FAKTY Z NAZWY I ŚCIEŻKI KOPII (AR-1, decyzja Zdzinia 2026-10-07): token FLATGRP, filtr w nazwie
    i folder filtra (`copy_name_facts`). Kopie o identycznych nagłówkach potrafią różnić się samą
    nazwą (FLATGRP 202203240 obok 202203250) - to też rozjazd, który rozstrzyga człowiek. Inna
    reguła udziału niż przy zeznaniu: ścieżkę baza zna zawsze, więc do porównania wchodzi każda
    obecna kopia, ale wyłącznie z WARTOŚCIĄ - brak tokenu (nazwa spoza wzorca, ścieżka spoza drzewa
    flatów) mówi „nie wiem", nie „inaczej". Porównanie bez wielkości liter, jak wzorzec assetu
    i ścieżki Windows. Etykieta trafia do kopii, które w tym polu MAJĄ wartość."""
    zeznane = [c for c in copies
               if copy_facts_state(c["hdr_hash"], c["hdr_rule"]) == FAKTY_BIEZACE]
    out = {}
    if len(zeznane) >= 2:
        rozne = []
        for kolumna, etykieta in _COPY_DIVERGENCE_FIELDS:
            if len({c[kolumna] for c in zeznane}) > 1 and etykieta not in rozne:
                rozne.append(etykieta)
        if rozne:
            out = {c["location_id"]: list(rozne) for c in zeznane}
    nazwy = [(c["location_id"], copy_name_facts(c["path"])) for c in copies]
    for pole in COPY_NAME_FIELDS:
        z_wartoscia = [(lid, f[pole]) for lid, f in nazwy if f[pole] is not None]
        if len({v.casefold() for _, v in z_wartoscia}) > 1:
            for lid, _ in z_wartoscia:
                out.setdefault(lid, []).append(pole)
    return {lid: tuple(pola) for lid, pola in out.items()}


def copy_conflict_frame_ids(con):
    """Zbiór frame_id perspektywy „Kopie niezgodne ze sobą" (0021): klatki z ≥2 OBECNYMI kopiami,
    których zeznania nagłówków różnią się w którymkolwiek przechowanym polu albo których nazwy
    i ścieżki różnią się tokenem FLATGRP, filtrem w nazwie lub folderem filtra (`copy_divergence`).

    PODZBIÓR `dup_frame_ids` Z KONSTRUKCJI - kandydaci biorą się z tamtego predykatu, więc guardy
    żywotności (wycofana i zastąpiona wypadają) są te same, a „niezgodne" nigdy nie pokażą klatki,
    której nie ma na liście „Duplikaty". Druga kopia tych guardów byłaby SIN-DUP-em.

    JEDEN właściciel predykatu dla licznika Porządków i trimu gridu - jak `dup_frame_ids`.
    Zwraca set[int]."""
    kopie = {}
    for r in present_copy_facts(con, dup_frame_ids(con)):
        kopie.setdefault(int(r["frame_id"]), []).append(r)
    return {fid for fid, rows in kopie.items() if copy_divergence(rows)}


def orphan_testimony_copies(con):
    """ZEZNANIE Z NIEOBECNEJ KOPII: `{frame_id: [obecne kopie]}` klatek, których `header` nie zgadza
    się z ŻADNĄ obecną kopią. JEDEN właściciel predykatu dla etapu przejęcia zeznania w Dostawie
    (`scan.adopt_orphan_testimony`, przez podział `orphan_testimony_routes`) i dla wiersza Porządków
    (`orphan_testimony_frame_ids`, całość). Kopie: `location_id`, `path`, `header_hash`,
    w kolejności wjazdu (`ORDER BY l.id`).

    SKĄD TEN STAN (dług AR-5, zmierzony 2026-09-26): `header` pochodzi z JEDNEJ kopii (reguła
    N-lokacji). Skasowanie tej kopii zdejmuje jej obecność (`presence`), ale zeznanie zostaje, a skan
    pomija ocalałą kopię (mtime bez zmian) - więc klatka pokazuje filtr pliku, którego nie ma, a lista
    „Kopie niezgodne ze sobą" pustoszeje, bo porównuje wyłącznie kopie obecne.

    PORÓWNANIE - OSIEM PÓL ZEZNANIA KOPII (`COPY_TESTIMONY_KEYWORDS`: FILTER, IMAGETYP, OBJECT,
    TELESCOP, INSTRUME, EXPTIME, XBINNING, DATE-OBS) liczonych JEDNĄ derywacją po obu stronach:
    strona kopii to kolumny `hdr_*` (`copy_testimony` przy odczycie pliku), strona klatki to
    `copy_testimony(raw_json)` - ten sam kod na tym samym nagłówku, więc typ (XISF-owy tekst vs FITS-owa
    liczba) i normalizacja (`''` → None) nie mogą udawać rozjazdu. Kolumny gorące `header` nie są
    drugim źródłem: zmierzone 2026-09-26 na 16 900 zeznaniach żywej bazy - zero różnic między nimi
    a `extract_header(raw_json)`. IMAGETYP nie ma kolumny w `header`, stąd `raw_json`.

    Dwa etapy, jeden werdykt: SQL wybiera kandydatów po kolumnach gorących (`IS` - równość świadoma
    NULL-a) i IMAGETYP z `json_extract` - zbiór NADMIAROWY, bo SQL nie zna rzutu `_to_text`; Python
    rozstrzyga `copy_testimony`. Pełna derywacja na 16,9 tys. zeznań kosztowałaby ~0,26 s przy każdym
    odświeżeniu Porządków, a kandydatów po SQL jest tyle, ile realnych rozjazdów.

    KLATKA WCHODZI WYŁĄCZNIE, GDY KAŻDA OBECNA KOPIA MA ZEBRANE ZEZNANIE (`hdr_hash`) BIEŻĄCEJ
    REGUŁY KOERCJI (`hdr_rule` == `COPY_TESTIMONY_RULE`, AR-33). Kopia bez faktów mówi „nie wiem",
    a nie „inaczej" - mogła być źródłem `header`, więc klatka z taką kopią nie należy do predykatu
    (ta sama zasada co `copy_divergence`). Fakty starej reguły porównane z `copy_testimony` liczonym
    regułą bieżącą dałyby fałszywe „zeznanie z nieobecnej kopii", a etap przejęcia przepisałby
    `header` - są więc „nie wiem" do czasu dociągnięcia przez sterownik uzupełnienia. Brak obecnej kopii = inna robota
    („Zniknięte"); brak `header` = frame-szkielet (kubełek `headerless` kolejki przeglądu).

    Guardów żywotności (wycofana, zastąpiona) predykat NIE nosi: mówi o prawdzie zeznania, a nie
    o liście roboty. Zastąpiona obecnej kopii mieć nie powinna (skan gasi oznaczenie), a wycofanej
    z plikiem na dysku przejęcie niczego nie odbiera - poprawia fakt z pliku, werdykt ręki zostaje.
    Guardy listy roboty niesie `orphan_testimony_frame_ids`."""
    kandydaci = {int(r["frame_id"]): r["raw_json"] for r in con.execute(
        "SELECT h.frame_id, h.raw_json FROM header h "
        "WHERE EXISTS (SELECT 1 FROM location l WHERE l.frame_id = h.frame_id AND l.present = 1) "
        "  AND NOT EXISTS (SELECT 1 FROM location l WHERE l.frame_id = h.frame_id "
        "                   AND l.present = 1 AND (l.hdr_hash IS NULL OR l.hdr_rule IS NOT ?)) "
        "  AND NOT EXISTS (SELECT 1 FROM location l WHERE l.frame_id = h.frame_id "
        "                   AND l.present = 1 "
        "                   AND l.hdr_filter IS h.filter_raw AND l.hdr_object IS h.object_raw "
        "                   AND l.hdr_telescop IS h.telescop AND l.hdr_instrume IS h.instrume "
        "                   AND l.hdr_exptime IS h.exptime AND l.hdr_xbinning IS h.xbinning "
        "                   AND l.hdr_date_obs IS h.date_obs "
        "                   AND l.hdr_imagetyp IS NULLIF(json_extract(h.raw_json, '$.IMAGETYP'), ''))",
        (COPY_TESTIMONY_RULE,)).fetchall()}
    if not kandydaci:
        return {}
    kopie = {}
    for r in con.execute(
            "SELECT l.frame_id, l.id AS location_id, l.path, l.header_hash, "
            "       l.hdr_filter, l.hdr_imagetyp, l.hdr_object, l.hdr_telescop, l.hdr_instrume, "
            "       l.hdr_exptime, l.hdr_xbinning, l.hdr_date_obs "
            "FROM location l "
            "WHERE l.present = 1 AND l.frame_id IN (SELECT value FROM json_each(?)) "
            "ORDER BY l.frame_id, l.id",
            (json.dumps(list(kandydaci)),)):
        kopie.setdefault(int(r["frame_id"]), []).append(r)
    wynik = {}
    for fid, rows in kopie.items():
        zeznanie = copy_testimony(json.loads(kandydaci[fid]))
        if not any(all(r[k] == v for k, v in zeznanie.items()) for r in rows):
            wynik[fid] = rows
    return wynik


def hand_testimony_frame_ids(con, frame_ids):
    """Które z `frame_ids` mają zeznanie napisane RĘKĄ - najnowszy zapis `header` w dzienniku
    (target `frame:<id>`) ma aktora `user:*`. Zwraca set[int]. Nowa droga zapisu `header` musi
    dopisać swój czasownik do literału niżej - inaczej jej zapis nie przesłoni wcześniejszego
    zapisu ręki i klatka zostanie „z ręki" na zawsze.

    SKĄD TO WIADOMO (zmierzone 2026-09-26 na kopii żywej bazy, 137 486 zdarzeń): `header` piszą
    wyłącznie trzy klingi i każda zostawia jedno zdarzenie w tej samej transakcji - `header.recorded`
    (skan `scan`, drogi stosów `stacks`, import `import:fitsmirror`), `header.refreshed` (skan przy
    zmianie odcisku, `backfill:xisf` i RE-SYNC writebacku z aktorem `user:local`: 606 zdarzeń -
    „Napraw nagłówek…", zapis makra i ich cofnięcia, `writeback._resync`) oraz `header.adopted`
    (etap przejęcia i gest „Ta kopia prowadzi", `lead_copy`). Najnowsze po `id` jest więc bieżącym
    zeznaniem, a aktor mówi, czyj to był gest. Cofnięcie zapisu (`writeback.undo`) też liczy się jako
    ręka - to także decyzja człowieka o treści nagłówka, więc etap ma jej nie przestawiać.

    DRUGA DROGA - KOPIA WIODĄCA WSKAZANA RĘKĄ (AR-4): najnowsze `header.adopted` klatki ma aktora
    `user:*`. Wybór trwa, choć wskazana kopia zmieniła potem nagłówek na dysku (`header.refreshed`
    skanu): odświeżenie zeznania przepuszcza wtedy WYŁĄCZNIE tę kopię
    (`repo.hand_lead_location`), więc późniejsze zapisy zeznania niosą dalej głos wybranej kopii.
    Bez tej drogi zwykła zmiana pliku wiodącego kasowałaby fakt ręki z osi `testimony_hand`.

    Zapytanie po indeksie `idx_event_target` (target = `frame:<id>` ze stałego literału `json_each`),
    wołane wyłącznie dla klatek predykatu - czyli dla garstki, nie dla archiwum."""
    if not frame_ids:
        return set()
    return {int(r[0]) for r in con.execute(
        "SELECT CAST(substr(e.target, 7) AS INTEGER) FROM event e "
        "WHERE e.id IN (SELECT MAX(id) FROM event "
        "               WHERE target IN (SELECT 'frame:' || value FROM json_each(?1)) "
        "                 AND verb IN ('header.recorded', 'header.refreshed', 'header.adopted') "
        "               GROUP BY target "
        "               UNION "
        "               SELECT MAX(id) FROM event "
        "               WHERE target IN (SELECT 'frame:' || value FROM json_each(?1)) "
        "                 AND verb = 'header.adopted' "
        "               GROUP BY target) "
        "  AND e.actor LIKE 'user:%'",
        (json.dumps(sorted(frame_ids)),)).fetchall()}


def orphan_testimony_routes(con):
    """PODZIAŁ predykatu `orphan_testimony_copies` na dwie drogi naprawy - JEDEN właściciel tej
    decyzji dla etapu Dostawy (wiersz Porządków liczy całość predykatu, obie drogi - docstring
    `orphan_testimony_frame_ids`). Zwraca `(dla_etapu, dla_czlowieka)`:
    `dla_etapu` = `{frame_id: jedyna obecna kopia}`, `dla_czlowieka` = set[int].

    ETAP (`scan.adopt_orphan_testimony`) dostaje klatkę WYŁĄCZNIE, gdy ma jedną obecną kopię ORAZ jej
    zeznania nie napisała ręka. Wtedy jest dokładnie jedna prawdziwa odpowiedź i nikt jej nie wybierał.
    CZŁOWIEK dostaje resztę (AR-4: „gdy kopie mówią różnie, Horreum pyta, zaznacza człowiek"):
      * ≥2 obecne kopie - kopię wiodącą wskazuje człowiek;
      * zeznanie z RĘKI (`hand_testimony_frame_ids`) - nawet przy jednej obecnej kopii. „Napraw
        nagłówek…" pisze plik kopii A i `header`; kopia B, która doszła później albo wróciła po
        zniknięciu, niesie stary głos (reguła N-lokacji). Gdy potem zniknie A, etap przepisałby
        zeznanie głosem B i poprawka ręki przepadłaby bez śladu - więc to jest pytanie, nie robota
        etapu.
    Guardów żywotności podział nie nosi - niesie je lista roboty (`orphan_testimony_frame_ids`)."""
    kopie = orphan_testimony_copies(con)
    reka = hand_testimony_frame_ids(con, kopie)
    dla_etapu = {fid: rows[0] for fid, rows in kopie.items() if len(rows) == 1 and fid not in reka}
    return dla_etapu, set(kopie) - set(dla_etapu)


def orphan_testimony_frame_ids(con):
    """Zbiór frame_id wiersza Porządków „Zeznanie z nieobecnej kopii": WSZYSTKIE klatki predykatu
    `orphan_testimony_copies` - obie połowy podziału `orphan_testimony_routes`.

    DLACZEGO TEŻ POŁOWA ETAPU. Klatkę o jednej obecnej kopii i zeznaniu spoza ręki naprawia etap
    przejęcia bez pytania - ale wyłącznie pod korzeniem, po którym właśnie chodzi (Dostawa, droga
    „Stosy", ogon „Oznacz zniknięte"). Ocalała kopia poza tym korzeniem, a także kopia, której etap
    odmówił (inna treść pod ścieżką, zmieniona od skanu, nieczytelna), czekałaby NIEWIDOCZNA do
    dostawy, której nikt nie zrobi. Robota człowieka przy niej jest realna: puścić Dostawę na
    korzeniu ocalałej kopii albo wskazać kopię wiodącą. W zwykłym przebiegu klatka jest tu chwilę -
    ogon „Oznacz zniknięte" przejmuje zeznanie w tym samym wątku, w którym zdjął obecność.

    GUARDY ŻYWOTNOŚCI jak w „Duplikatach" (`dup_frame_ids`): wycofana i zastąpiona wypadają - ich
    robotą jest werdykt ręki albo następczyni. Klatka o jednej kopii NIE jest duplikatem, więc guard
    stoi tu jako warunek, nie jako przecięcie z `dup_frame_ids`.
    JEDEN właściciel dla licznika Porządków i trimu gridu. Zwraca set[int]."""
    kopie = orphan_testimony_copies(con)
    if not kopie:
        return set()
    return {int(r[0]) for r in con.execute(
        "SELECT id FROM frame WHERE id IN (SELECT value FROM json_each(?)) "
        "AND retired_at IS NULL AND superseded_by IS NULL",
        (json.dumps(sorted(kopie)),)).fetchall()}


def path_header_conflict_frame_ids(con):
    """NAGŁÓWEK MÓWI CO INNEGO NIŻ ZATWIERDZONY FOLDER (E5-2): klatki z obiektem potwierdzonym ze
    ścieżki (`object_source IN WEAK_OBJECT_SOURCES`), których `header.object_raw` jest niepusty,
    a drabina nazwy przebiegu (`resolver.resolve_name`) nie daje TEGO SAMEGO obiektu - daje inny
    albo żaden. JEDEN właściciel predykatu dla licznika Porządków i trimu gridu. Zwraca set[int].

    DLACZEGO ZE STANU, A NIE Z PRZEBIEGU. Nazwa NIEROZPOZNANA zostawia klatkę przy obiekcie
    z folderu (gałąź przeglądu przebiegu wymaga `object_id IS NULL`, a region nad potwierdzeniem nie
    gra), więc żaden kubełek jej nie widział - rozjazd pliku z bazą był niewidoczny. Nazwa
    rozpoznana jako INNY obiekt jest tu tylko do najbliższego „Rozwiąż", który ją przepina
    (header-primary, głośno - ślad w `object.unassigned`); po nim wypada, bo źródło przestaje być
    słabe. Nazwa, która daje TEN SAM obiekt, nie jest rozjazdem i nie wchodzi.

    PORÓWNANIE PO KANONIE, bo tak tożsamość buduje przebieg (`upsert_object` po `canon`); trafienie
    aliasu też niesie kanon. Drabina ta sama, co w przebiegu i w dialogu (SPOT `resolve_name`),
    na migawce aliasów z JEDNEGO SELECT-a - zero zapytań w pętli. Region świadomie poza: przebieg
    nie pyta go o klatkę ze źródłem słabym, więc predykat też nie.

    RODZAJ = `LIGHT_KINDS`, bo tylko tam przebieg rozstrzyga obiekt: kalibracja nie ma obiektu
    z definicji, więc jej karta `OBJECT` niczemu nie przeczy (źródło `path` na kalibracji to osobny
    defekt - następczyni w `repo.transfer_human_facts` - nie robota dla tego wiersza).

    Guardy listy roboty jak w sąsiadach: wycofana i zastąpiona wypadają."""
    rows = con.execute(
        "SELECT f.id AS fid, h.object_raw AS raw, o.canon AS canon "
        "FROM frame f JOIN header h ON h.frame_id = f.id JOIN object o ON o.id = f.object_id "
        "WHERE f.object_source IN (SELECT value FROM json_each(?)) "
        "AND f.kind IN (SELECT value FROM json_each(?)) "
        "AND h.object_raw IS NOT NULL "
        "AND f.retired_at IS NULL AND f.superseded_by IS NULL",
        (json.dumps(sorted(WEAK_OBJECT_SOURCES)), json.dumps(sorted(LIGHT_KINDS)))).fetchall()
    if not rows:
        return set()
    lookup = alias_snapshot(con).get
    wynik = set()
    for r in rows:
        if _to_text(r["raw"]) is None:              # pusta karta nie zeznaje (jak w przebiegu)
            continue
        ident, _ = resolve_name(lookup, r["raw"])
        if ident is None or ident.canon != r["canon"]:
            wynik.add(int(r["fid"]))
    return wynik


def torn_write_frame_ids(con):
    """PLIK PO PRZERWANYM ZAPISIE (0022, Q8): klatki, których kopia ma OTWARTĄ operację zapisu
    w miejscu (`inplace_op.phase` w `repo.INPLACE_OPEN_PHASES`) - nagłówek mógł zostać rozdarty,
    więc kopia jest izolowana od skanu (`scan._isolated`). Robota człowieka: odzysk
    (`writeback.recover_torn`) albo jawne zwolnienie (`repo.release_inplace_op`) po własnym
    rozstrzygnięciu. JEDEN właściciel predykatu dla licznika Porządków i trimu gridu. Guardów
    żywotności (wycofana, zastąpiona) brak świadomie: rozdarty plik jest faktem o dysku, nie
    o liście roboty klatki. Zwraca set[int]."""
    return {int(r[0]) for r in con.execute(
        "SELECT DISTINCT l.frame_id FROM inplace_op o JOIN location l ON l.id = o.location_id "
        "WHERE o.phase IN (SELECT value FROM json_each(?))",
        (json.dumps(list(INPLACE_OPEN_PHASES)),)).fetchall()}


# Fazy IZOLUJĄCE, które nie są otwarte: plik zapisany i zweryfikowany, a kontrola danych i re-sync
# bazy jeszcze się nie udały (dziś jedna faza, `written`). Liczone z dwóch zbiorów `repo`, a nie
# wpisane literałem: właścicielem nazw faz jest dziennik zapisu, a ten zbiór jest ich RÓŻNICĄ.
INPLACE_PENDING_FINISH_PHASES = tuple(p for p in INPLACE_ISOLATING_PHASES
                                      if p not in INPLACE_OPEN_PHASES)


def pending_finish_frame_ids(con):
    """ZAPIS CZEKA NA DOKOŃCZENIE (warunek wsadu AR-17 (1)): klatki, których kopia ma operację zapisu
    w miejscu w fazie `INPLACE_PENDING_FINISH_PHASES` - plik ma już nowy nagłówek, ale baza jeszcze
    go nie wciągnęła, więc kopia jest izolowana od skanu tak samo jak po przerwanym zapisie, tylko
    że robotą jest DOKOŃCZENIE (`writeback.finish_inplace`), nie odzysk. Bez tego wiersza lokacja
    w tej fazie była dla użytkownika GUI niewidoczna i zablokowana: skan ją pomija, a
    `torn_write_frame_ids` widzi wyłącznie fazy otwarte.

    JEDEN właściciel predykatu dla licznika Porządków i trimu gridu. Guardów żywotności brak z tego
    samego powodu co u sąsiada wyżej: izolacja jest faktem o pliku, nie o liście roboty klatki.
    Zwraca set[int]."""
    return {int(r[0]) for r in con.execute(
        "SELECT DISTINCT l.frame_id FROM inplace_op o JOIN location l ON l.id = o.location_id "
        "WHERE o.phase IN (SELECT value FROM json_each(?))",
        (json.dumps(list(INPLACE_PENDING_FINISH_PHASES)),)).fetchall()}


def isolated_inplace_ops(con, frame_ids):
    """Operacje zapisu w miejscu, które IZOLUJĄ kopie wskazanych klatek (`INPLACE_ISOLATING_PHASES`)
    - cel gestów „Dokończ zapis" / „Przywróć nagłówek sprzed zapisu" / „Zwolnij plik do skanu…"
    w Zbiorach. Lista dict `{op_id, location_id, frame_id, phase, kind, path}` w kolejności klatki
    i operacji. Lokacja ma najwyżej jedną taką operację (`repo._refuse_if_isolated` nie otwiera
    nowej przy izolującej), więc wiersz = jedna kopia do rozstrzygnięcia.

    Faza jest tu PREZENTACJĄ (uczciwe wygaszenie gestu): prawdę rozstrzyga pisarz pod blokadą pliku,
    bo między pokazaniem menu a gestem faza mogła się zmienić."""
    ids = sorted({int(f) for f in frame_ids})
    if not ids:
        return []
    return [dict(r) for r in con.execute(
        "SELECT o.id AS op_id, o.location_id AS location_id, l.frame_id AS frame_id, "
        "o.phase AS phase, o.kind AS kind, l.path AS path "
        "FROM inplace_op o JOIN location l ON l.id = o.location_id "
        "WHERE l.frame_id IN (SELECT value FROM json_each(?)) "
        "AND o.phase IN (SELECT value FROM json_each(?)) "
        "ORDER BY l.frame_id, o.id",
        (json.dumps(ids), json.dumps(list(INPLACE_ISOLATING_PHASES)))).fetchall()]


# Powód pominięcia w planie ujednolicenia karty `OBJECT` (`object_card_form_rows`): stała, bo czyta
# go też test i podpowiedź powierzchni - tekst mówi, co zrobić, żeby klatka wróciła do planu.
SKIP_COPY_WITHOUT_FACTS = ("kopia bez zebranych faktów przy klatce z nieobecną kopią - zbierze je "
                           "„Przyjmij nowe”, gdy plik jest na dysku i nie czeka na dokończenie "
                           "przerwanego zapisu")


def object_card_form_rows(con):
    """KARTA `OBJECT` W INNEJ FORMIE (O5, 2026-09-26): klatki, których karta `OBJECT` wskazuje TEN
    SAM obiekt co klatka, ale innym zapisem niż jedna forma karty (`resolver.forma_karty_object` -
    ta sama funkcja, której używają gesty GUI piszące kartę):
    `NGC6992` → `NGC 6992`, `M 106` → `NGC 4258`, `ksiezyc` → `Moon`. JEDEN właściciel predykatu
    dla planu ujednolicenia (`macro.plan_object_card_form`) i dla wiersza Porządków
    (`object_card_form_frame_ids`).

    PREDYKAT (klatka wchodzi): rodzaj z `LIGHT_KINDS`, obiekt przypisany, karta `OBJECT` niepusta,
    drabina nazwy przebiegu (`resolver.resolve_name` na migawce aliasów - ta sama co w przebiegu
    i w `path_header_conflict_frame_ids`) daje TEN SAM kanon co obiekt klatki, a karta różni się od
    formy karty kanonu. Karta wskazująca INNY obiekt albo nierozpoznana nie jest „inną formą",
    tylko innym zeznaniem - tu nie wchodzi (to robota E5-2). Wycofana i zastąpiona wypadają.
    Wchodzą też komety, Księżyc, nazwy zwyczajowe i klatki z obiektem nadanym ręką - decyzja
    usera 2026-09-26: „jedna wersja na obiekt", „przestaw jednakowo" (odwrócone D-PD-9).

    BRAMKI CELU (klatka zostaje w wyniku z `skip` = powód, żeby podgląd powiedział, czego NIE
    ruszamy) - wzorzec `macro.resolve_target`, plus trzy własne:
      * RAW (read-only, #2), obiekt z REGIONU (współrzędne, nie karta), brak obecnej kopii albo
        wiele obecnych (D-W1), skompresowany master (T6), degenerat tożsamości (D-X-13), brak
        `header_hash` (brak kontroli zapisu);
      * kopia oznaczona jako nieczytelna (`unreadable_since`, #13) - jej `header_hash` jest
        z ostatniego UDANEGO odczytu, więc kotwica zapisu mogłaby kłamać;
      * więcej niż jedna karta `OBJECT` - zeznanie bierze ostatnią (`_put`), a zapis musiałby
        zgadywać, którą ujednolicić;
      * kopia bez zebranych faktów (`hdr_hash` NULL), gdy klatka ma kopię NIEOBECNĄ
        (`SKIP_COPY_WITHOUT_FACTS`) - karty klatki mogły przyjść ze skasowanego pliku, a strażnik
        niżej bez faktów jest ślepy; fakty dociąga etap Dostawy (`scan.backfill_copy_facts`);
      * kopia zeznaje INNĄ kartę niż klatka (`location.hdr_object`, gdy fakty kopii są zebrane) -
        karty w `cards` należą do KLATKI i mogą pochodzić z innej kopii;
      * forma nie wraca do kanonu (`forma_karty_object` → None: kanon znany tylko z aliasu) -
        karta z nią wypchnęłaby klatkę do nierozpoznanych (kimi Z1);
      * sklejka oznaczeń (`NGC4631_PGC42637`), której NIE KAŻDY człon wskazuje ten sam kanon -
        forma zastąpiłaby zeznanie o dwóch obiektach jednym (kimi Z2c);
      * karta `OBJECT` nietekstowa (`value_type` ≠ 'str') - forma jest tekstem (kimi Z5);
      * FITS z kartą `CHECKSUM`/`DATASUM` - zapis nagłówka unieważniłby sumę (astra Z5).

    Karta i komentarz pochodzą z `cards` (idx 0), bo tam jest też `value_type` i komentarz, z których
    plan przewiduje drogę zapisu. Zwraca listę dict: `frame_id`, `location_id`, `path`,
    `filetype`, `header_hash`, `canon`, `card`, `form`, `value_type`, `comment`, `skip`."""
    rows = con.execute(
        "SELECT f.id AS fid, f.filetype, f.sha1_data_uncomputable AS degen, "
        "       f.object_source AS osrc, o.canon AS canon, "
        "       c.value_raw AS card, c.value_type AS vtype, c.comment AS comment, "
        "       (SELECT count(*) FROM cards c2 WHERE c2.frame_id = f.id "
        "          AND c2.keyword = 'OBJECT') AS n_cards, "
        "       (SELECT count(*) FROM location l2 WHERE l2.frame_id = f.id "
        "          AND l2.present = 1) AS n_present, "
        "       (SELECT count(*) FROM location l4 WHERE l4.frame_id = f.id "
        "          AND l4.present = 0) AS n_absent, "
        "       (SELECT count(*) FROM cards c3 WHERE c3.frame_id = f.id "
        "          AND c3.keyword IN ('CHECKSUM', 'DATASUM')) AS n_sum, "
        "       l.id AS lid, l.path, l.header_hash, l.compressed, l.unreadable_since, "
        "       l.hdr_hash, l.hdr_rule, l.hdr_object "
        "FROM frame f "
        "JOIN object o ON o.id = f.object_id "
        "JOIN cards c ON c.frame_id = f.id AND c.keyword = 'OBJECT' AND c.idx = 0 "
        "LEFT JOIN location l ON l.frame_id = f.id AND l.present = 1 "
        "WHERE f.kind IN (SELECT value FROM json_each(?)) "
        "  AND f.retired_at IS NULL AND f.superseded_by IS NULL "
        "ORDER BY f.id, l.id",
        (json.dumps(sorted(LIGHT_KINDS)),)).fetchall()
    if not rows:
        return []
    lookup = alias_snapshot(con).get
    formy: dict[str, str | None] = {}

    def _kanon(tekst):
        trafienie = resolve_name(lookup, tekst)[0] if tekst else None
        return trafienie.canon if trafienie is not None else None

    wynik, widziane = [], set()
    for r in rows:
        fid = int(r["fid"])
        if fid in widziane:                     # druga obecna kopia - klatka już opisana
            continue
        widziane.add(fid)
        card = _to_text(r["card"])
        if card is None:                        # pusta karta nie zeznaje (jak w przebiegu)
            continue
        ident, _ = resolve_name(lookup, card)
        if ident is None or ident.canon != r["canon"]:
            continue
        if r["canon"] not in formy:
            formy[r["canon"]] = forma_karty_object(con, r["canon"], lookup=lookup)
        form = formy[r["canon"]]
        if form is not None and card == form:
            continue
        czlony = [c.strip() for c in card.split("_")] if "_" in card else []
        # Fakty kopii zebrane starszą regułą koercji (AR-33) to „nie wiem", jak brak faktów.
        fakty_biezace = copy_facts_state(r["hdr_hash"], r["hdr_rule"]) == FAKTY_BIEZACE
        if r["filetype"] == "raw":
            skip = "plik RAW (DSLR) - Horreum go nie zapisuje"
        elif r["osrc"] == "region":
            skip = "obiekt z regionu (współrzędne), nie z karty"
        elif r["n_present"] == 0:
            skip = "brak obecnej kopii"
        elif r["n_present"] > 1:
            skip = f"wiele obecnych kopii ({r['n_present']})"
        elif r["compressed"]:
            skip = "skompresowany master"
        elif r["degen"]:
            skip = "tożsamość nieobliczalna (degenerat) - zapis rozdwoiłby klatkę"
        elif r["header_hash"] is None:
            skip = "brak header_hash - brak kontroli zapisu"
        elif r["unreadable_since"] is not None:
            skip = "kopia oznaczona jako nieczytelna"
        elif r["n_cards"] > 1:
            skip = f"wiele kart OBJECT ({r['n_cards']})"
        elif not fakty_biezace and r["n_absent"]:
            skip = SKIP_COPY_WITHOUT_FACTS
        elif fakty_biezace and _to_text(r["hdr_object"]) != card:
            skip = "kopia zeznaje inną kartę OBJECT niż klatka"
        elif form is None:
            skip = "forma karty nie wraca do kanonu (kanon znany tylko z aliasu)"
        elif czlony and not all(_kanon(c) == r["canon"] for c in czlony):
            skip = "sklejka oznaczeń - nie każdy człon wskazuje ten obiekt"
        elif r["vtype"] != "str":
            skip = f"karta OBJECT nietekstowa ({r['vtype']})"
        elif r["filetype"] == "fits" and r["n_sum"]:
            skip = "FITS z sumą kontrolną (CHECKSUM/DATASUM)"
        else:
            skip = None
        wynik.append({
            "frame_id": fid, "location_id": r["lid"], "path": r["path"] or "",
            "filetype": r["filetype"], "header_hash": r["header_hash"], "canon": r["canon"],
            "card": card, "form": form, "value_type": r["vtype"], "comment": r["comment"],
            "skip": skip})
    return wynik


def object_card_form_frame_ids(con):
    """Klatki do ujednolicenia karty `OBJECT` - wiersze `object_card_form_rows` BEZ powodu
    pominięcia (licznik i trim wiersza Porządków „Karta OBJECT w innej formie"). Zwraca set[int]."""
    return {r["frame_id"] for r in object_card_form_rows(con) if r["skip"] is None}


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


# ============================================================ WERSJE STOSÓW (perspektywa „Wersje stosów")
# Ten sam materiał zintegrowany kilka razy. Duplikatami w sensie Horreum te pliki NIE są - inne
# piksele to inna klatka (`sha1_data`), więc „Duplikaty" ich nie widzą - a user chce je sprzątać.
# Horreum niczego nie kasuje ani nie przenosi: read-model ustawia wersje obok siebie z faktami do
# decyzji, a usuwa człowiek, poza programem.

WERSJA_INNA = "inna"
"""Rodzaj członka grupy: jest DOWÓD odrębnego przebiegu integracji względem co najmniej jednego sąsiada."""
WERSJA_POCHODNA = "pochodna"
"""Rodzaj członka: dowodu odrębności brak, jest dowód wspólnego pochodzenia z sąsiadem."""
WERSJA_NIEUSTALONA = "nieustalone"
"""Rodzaj członka: baza nie niesie świadka ani odrębności, ani pochodzenia."""

# ŚWIADKOWIE - tokeny zdania powierzchni (`grid.version.why.<token>`), w porządku SIŁY: gdy
# członek ma kilku, pokazujemy najmocniejszego. Parytet z katalogiem pinuje test.
SWIADEK_HISTORIA = "declared"
SWIADEK_SYGNATURA = "tool"
SWIADEK_POMIARY = "measure"
SWIADEK_TA_SAMA_SYGNATURA = "same_tool"
SWIADEK_TE_SAME_POMIARY = "same_measure"
VERSION_WITNESSES = (SWIADEK_HISTORIA, SWIADEK_SYGNATURA, SWIADEK_POMIARY,
                     SWIADEK_TA_SAMA_SYGNATURA, SWIADEK_TE_SAME_POMIARY)

_POMIAR_RX = re.compile(r"^(NOISE|PSF)")
_KANAL_RX = re.compile(r"(\d\d)$")


def _pomiary_obrazu(raw_json):
    """Pomiary obrazu z nagłówka - karty `NOISE*`/`PSF*` o wartości LICZBOWEJ, `{karta: float}`.

    Te karty pisze proces, który MIERZY piksele (szum i sygnał PSF integracji), a procesy pochodne
    (łączenie kanałów, wyrównanie, przycięcie) przepisują je bez zmian. Stąd ich siła jako świadka
    - zmierzona na 112 parach bliźniaków żywego archiwum (2026-09-26): 101 par różni się we
    WSZYSTKICH wspólnych kartach, 10 zgadza się we wszystkich, a jedyna para mieszana (29 z 30
    różnych) ma jedną zbieżność przypadkową. Etykiety algorytmu (`NOISEA00 = MRS`,
    `PSFSGTYP = Moffat4`) nie są pomiarem i odpadają same, bo nie są liczbą.

    KOERCJA PRZY WEJŚCIU (`_to_float`), nie porównanie tekstów: nagłówek XISF niesie liczby jako
    napisy (`'1.4035e+03'`), a ten sam pomiar zapisany inną drogą mógłby przyjść jako `1403.5` -
    słownik napisów rozjechałby dwie identyczne wartości w „różne pomiary". Nieczytelny JSON
    → `{}` (brak świadka, nie wyjątek)."""
    try:
        karty = json.loads(raw_json or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(karty, dict):
        return {}
    out = {}
    for klucz, wartosc in karty.items():
        if _POMIAR_RX.match(str(klucz)):
            liczba = _to_float(wartosc)
            if liczba is not None:
                out[str(klucz)] = liczba
    return out


def _kanaly(pomiary):
    """Kanały, na których zmierzono obraz - sufiksy `00`/`01`/`02` kart pomiaru (`frozenset`)."""
    return frozenset(m.group(1) for m in (_KANAL_RX.search(k) for k in pomiary) if m)


def _ten_sam_kanal(a, b, mono):
    """Czy dwa stosy grupy przedstawiają TEN SAM kanał - warunek każdego dowodu odrębności.

    Kamera MONO: kanałem jest filtr, a filtr stoi w kluczu grupy - więc zawsze tak. Kamera
    KOLOROWA rozbija jedną sesję na kanały: zmierzone na NGC4826 (2025-04) - trzy stosy `R`/`G`/`B`
    mają trzy RÓŻNE sygnatury integracji w odstępie dwóch minut i tę samą liczbę wejść (190), bo
    WBPP integruje każdy kanał osobno. Różne sygnatury znaczą tam „trzy kanały", nie „trzy
    wersje", a nagłówek nie mówi, który kanał jest który. Dla kamery kolorowej wiemy to wyłącznie
    o obrazach PEŁNOKOLOROWYCH: oba zmierzone na tych samych co najmniej dwóch kanałach.
    Kamera nieznana (`is_mono` NULL) idzie drogą kolorowej - brak faktu nie może poszerzać dowodu.

    KANAŁ Z NAZWY (`frame.channel`, 0028) domyka tę lukę dla stosów POJEDYNCZYCH kanałów: dwa stosy
    `B` jednej grupy to ten sam kanał, więc różne sygnatury czy pomiary znaczą tam dwa przebiegi
    integracji (NGC3034 RC8 600 s: kanały przebiegu `WBPP2` wobec kanałów `WBPP@@1` - do 0028 grupa
    „pochodna", odrębność widziała wyłącznie nazwa pliku). Stosy RÓŻNYCH kanałów dalej nie mają
    wspólnego kanału i dowodu odrębności nie dostaną - kanał przyspiesza dowód, nie poszerza go."""
    if mono:
        return True
    if a.get("kanal") is not None and a.get("kanal") == b.get("kanal"):
        return True
    return len(a["kanaly"]) >= 2 and a["kanaly"] == b["kanaly"]


def _para_pochodna(a, b):
    """Świadek WSPÓLNEGO POCHODZENIA dwóch stosów - token albo `None`.

    Ta sama sygnatura integracji to ten sam przebieg (dziś populacja zerowa: 71 sygnatur
    w archiwum, wszystkie różne). Identyczne pomiary to nagłówek skopiowany z jednego obrazu -
    zmierzone na parach `R` + `combined_RGB` (LMC, NGC1976, NGC7635): obraz połączony dziedziczy
    karty kanału `R` znak w znak, razem z pomiarem szumu, którego żadna odrębna integracja nie
    powtórzy co do czwartej cyfry."""
    if a["tool"] and a["tool"] == b["tool"]:
        return SWIADEK_TA_SAMA_SYGNATURA
    if a["pomiary"] and a["pomiary"] == b["pomiary"]:
        return SWIADEK_TE_SAME_POMIARY
    return None


def _para_odrebna(a, b, mono):
    """Świadek ODRĘBNEGO PRZEBIEGU integracji dwóch stosów tego samego kanału - token albo `None`.

    Trzej świadkowie, każdy z bazy, żaden z nazwy pliku:
      * HISTORIA - `declared_rows` różne: plik zeznaje inny zbiór wejść, więc to inna integracja
        (IC1795 Ha: 33 wejścia wobec 31);
      * SYGNATURA - różne `tool` (`PCL:Signature:Integration`): dwa przebiegi ImageIntegration;
      * POMIARY - różne karty szumu i PSF: dwa różne zdarzenia pomiaru na dwóch różnych obrazach.
        Jedyny świadek stosów sprzed modułu XISF 1.1.2 (marzec 2025), które sygnatury nie mają.
        Zgadza się z sygnaturą i historią tam, gdzie są wszystkie trzy (IC1795 Ha i OIII).

    POCHODZENIE BIJE ODRĘBNOŚĆ: gdy para ma świadka wspólnego pochodzenia, odrębności nie
    orzekamy - pomyłka w tę stronę chowa grupę, a w przeciwną podsuwa do skasowania pochodną
    zostawianej wersji."""
    if _para_pochodna(a, b) or not _ten_sam_kanal(a, b, mono):
        return None
    if a["declared"] is not None and b["declared"] is not None and a["declared"] != b["declared"]:
        return SWIADEK_HISTORIA
    if a["tool"] and b["tool"] and a["tool"] != b["tool"]:
        return SWIADEK_SYGNATURA
    if a["pomiary"] and b["pomiary"] and a["pomiary"] != b["pomiary"]:
        return SWIADEK_POMIARY
    return None


def classify_stack_versions(czlonkowie, *, mono):
    """Rodzaj każdego członka jednej grupy bliźniaków - `{frame_id: (rodzaj, świadek|None)}`.

    Czysta funkcja, zero SQL. `czlonkowie` = dicty z kluczami `frame_id`, `tool`, `declared`
    (int albo None - koercja jest sprawą wołającego), `pomiary` (`_pomiary_obrazu`), `kanaly`
    (`_kanaly`) i opcjonalnie `kanal` (`frame.channel`). Rodzaj jest PARAMI, nie po cesze członka: „inna integracja" znaczy „odrębna od
    co najmniej jednego sąsiada", a relacja odrębności jest symetryczna - dlatego grupa ma albo
    zero, albo co najmniej dwóch członków tego rodzaju. Świadek to najmocniejszy z par
    (`VERSION_WITNESSES` w porządku siły)."""
    wynik = {}
    for a in czlonkowie:
        inni = [b for b in czlonkowie if b["frame_id"] != a["frame_id"]]
        odrebne = [s for s in (_para_odrebna(a, b, mono) for b in inni) if s]
        if odrebne:
            wynik[a["frame_id"]] = (WERSJA_INNA, min(odrebne, key=VERSION_WITNESSES.index))
            continue
        pochodne = [s for s in (_para_pochodna(a, b) for b in inni) if s]
        wynik[a["frame_id"]] = ((WERSJA_POCHODNA, min(pochodne, key=VERSION_WITNESSES.index))
                                if pochodne else (WERSJA_NIEUSTALONA, None))
    return wynik


def _rodzaj_grupy(rodzaje):
    """Rodzaj CAŁEJ grupy: wersje, gdy są co najmniej dwie z dowodem odrębności; pochodna, gdy dowodu
    odrębności nie ma, a jest dowód pochodzenia; w pozostałych przypadkach nieustalone."""
    if sum(1 for r in rodzaje if r == WERSJA_INNA) >= 2:
        return WERSJA_INNA
    if WERSJA_POCHODNA in rodzaje:
        return WERSJA_POCHODNA
    return WERSJA_NIEUSTALONA


def _stack_version_rows(con):
    """Stosy-kandydaci do grup wersji: gotowy obraz z integracją, żywy (nie wycofany, nie zastąpiony)
    i z OBECNĄ kopią. Warunek obecności jest treścią, nie ostrożnością: po usunięciu wersji poza
    programem i skanie jej klatka traci ostatnią kopię, a grupa ma wtedy zniknąć z listy roboty.
    Klatka bez kopii ma własną perspektywę („Zniknięte") i tam jest jej gest.

    Teleskop KANONICZNY przez `config → telescope_canonical` (jak `base_rows`): scalenie teleskopów
    nie rozcina grupy, a `telescope_id` NULL znaczy „config nieznany".
    Werdykt „zostawiam wszystkie" (0026) przychodzi LEFT JOIN-em: `kept_key`/`kept_at` NULL = brak.

    OKNA TU NIE MA - liczy je `_grupy_wersji` z ŻYWEGO `header` (AR-22 (2)). Z głowy `integration`
    idą wyłącznie fakty HISTORII pliku (`tool`, `declared_rows`, `creation_time`), których zapis
    nagłówka nie zmienia; okno to karty `DATE-OBS`/`DATE-END`, a głowa trzyma je zamrożone do
    „Policz rodowód stosów".
    Zwraca: frame_id, object_id, object_canon, camera_id, camera_model, telescope_id,
    telescope_label, telescop_canon, is_mono, filter_canon, channel, exptime, raw_json, tool,
    declared_rows, creation_time, kept_key, kept_at, ra_deg, dec_deg."""
    return con.execute(
        "SELECT f.id AS frame_id, f.object_id, obj.canon AS object_canon, f.camera_id, "
        "       cam.model_canon AS camera_model, tc.canon_id AS telescope_id, "
        "       t.label AS telescope_label, t.telescop_canon, f.channel, "
        "       cam.is_mono, f.filter_canon, h.exptime, h.raw_json, h.ra_deg, h.dec_deg, "
        "       i.tool, i.declared_rows, i.creation_time, "
        "       k.group_key AS kept_key, k.decided_at AS kept_at "
        "FROM frame f JOIN integration i ON i.master_frame_id = f.id "
        "LEFT JOIN stack_version_kept k ON k.frame_id = f.id "
        "LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN telescope t ON t.id = tc.canon_id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "LEFT JOIN object obj ON obj.id = f.object_id "
        "WHERE f.retired_at IS NULL AND f.superseded_by IS NULL "
        "  AND EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id AND l.present = 1) "
        "ORDER BY f.id").fetchall()


def _grupy_wersji(con):
    """Grupy bliźniaków z co najmniej dwoma stosami - `[(klucz, wiersze, mono, członkowie, rodzaje)]`.

    KLUCZ = (obiekt, kamera, teleskop kanoniczny, filtr, ekspozycja, początek okna, koniec okna).
    Okno co do sekundy przypina zbiór subów. Zestaw podwójny (dwa teleskopy tej samej nocy) rozcina
    TELESKOP, nie kamera: tabela `camera` jest per MODEL, nie per egzemplarz, więc dwa zestawy
    z kamerą tego samego modelu mają ten sam `camera_id` (zmierzone 2026-10-02 na kopii archiwum:
    4 noce z dwoma configami jednego modelu kamery). Stos z NIEZNANYM configiem nie orzeka
    wspólnego materiału z nikim - dostaje klucz własny, więc nie trafia do żadnej grupy: podsunięcie
    do skasowania stosu z innego zestawu jest pomyłką droższą niż przeoczenie wersji.

    EKSPOZYCJA PRZEZ KOERCJĘ I RÓWNOŚĆ, NIE PRZEZ `stacks.exposure_matches`. Próg D-DR-2 nie jest
    przechodni (`90~91`, `91~92`, a `90≁92`), więc grupowanie po nim zlepiałoby łańcuchem stosy,
    które się nie dopasowują - jego właściciel zakazuje tego wprost. Próg odpowiada też na inne
    pytanie (sub-lustrzanki wobec mastera: pomiar), a tu po obu stronach stoi zeznanie mastera
    z tych samych subów. Zmierzone 2026-09-26: w 31 grupach (obiekt, kamera, filtr, okno) nie ma
    ANI JEDNEJ różnicy ekspozycji, więc równość i próg dają dziś ten sam podział. Koercja zostaje
    bramką na pułapkę formatu: nagłówek XISF niesie `'600.00'`, a porównanie SQLite z kolumną to
    maskuje, słownik Pythona - nie.

    Okno idzie z ŻYWEGO `header` przez `resolve.stack.read_testimony` (karty `DATE-OBS`/`DATE-END`,
    parser `naming.header_dt` - SPOT): zapis z ułamkiem sekundy i bez niego ma dać ten sam klucz.
    Głowa `integration` okna NIE daje (AR-22 (2)): zamarza do „Policz rodowód stosów", a reszta
    klucza jest żywa - przejęcie zeznania albo zapis nagłówka mastera rozjeżdżały te dwie połowy.

    KANAŁ (`frame.channel`, 0028) NIE stoi w kluczu - świadomie. Kanały jednej sesji kamery
    kolorowej to ten sam materiał (te same suby), a grupa niesie też fakty o pochodzeniu MIĘDZY
    kanałem a obrazem złożonym (`combined_RGB` dziedziczy pomiary kanału `R` znak w znak - świadek
    `same_measure`). Kanał w kluczu rozcinałby te pary: zmierzone 2026-10-04 na kopii archiwum -
    31 grup → 28, z czego 8 grup „pochodna" topnieje do 3, a `combined_RGB` LMC traci świadka.
    Kanał działa PARAMI, w `_ten_sam_kanal`: dwa stosy tego samego kanału mogą mieć dowód odrębnej
    integracji, stosy różnych kanałów - nigdy."""
    grupy = {}
    for r in _stack_version_rows(con):
        # OKNO Z ŻYWEGO ZEZNANIA (AR-22 (2)), tą samą derywacją co rodowód (`read_testimony`, SPOT):
        # obiekt, filtr i ekspozycja klucza też są żywe, więc przejęcie zeznania albo zapis
        # nagłówka mastera nie zostawia już okna ze starego zeznania obok nowego obiektu.
        t = read_testimony(json.loads(r["raw_json"]) if r["raw_json"] else {})
        start, koniec = t.window_start, t.window_end
        if start is None or koniec is None:
            continue
        r = {**dict(r), "window_start": start.isoformat(), "window_end": koniec.isoformat()}
        teleskop = (r["telescope_id"] if r["telescope_id"] is not None
                    else ("bez-configu", r["frame_id"]))
        klucz = (r["object_id"], r["camera_id"], teleskop, r["filter_canon"],
                 _to_float(r["exptime"]), start, koniec)
        grupy.setdefault(klucz, []).append(r)
    out = []
    for klucz, wiersze in grupy.items():
        if len(wiersze) < 2:
            continue
        mono = bool(wiersze[0]["is_mono"])
        czlonkowie = []
        for r in wiersze:
            pomiary = _pomiary_obrazu(r["raw_json"])
            czlonkowie.append({"frame_id": int(r["frame_id"]), "tool": r["tool"] or None,
                               "declared": _to_int(r["declared_rows"]),
                               "pomiary": pomiary, "kanaly": _kanaly(pomiary),
                               "kanal": r["channel"],
                               "created": r["creation_time"] or None,
                               "kept_key": r["kept_key"], "kept_at": r["kept_at"],
                               "srodek": ((r["ra_deg"], r["dec_deg"])
                                          if r["ra_deg"] is not None and r["dec_deg"] is not None
                                          else None)})
        out.append((klucz, wiersze, mono, czlonkowie,
                    classify_stack_versions(czlonkowie, mono=mono)))
    return out


def _id_grupy_wersji(klucz):
    """Stabilny identyfikator grupy wersji - napis z KLUCZA (`_grupy_wersji`), nie z opisu: dwie
    grupy o tym samym opisie (obiekt · filtr · ekspozycja · okno, inne zestawy) mają różne id, a ta
    sama grupa ma to samo id w każdym przeładowaniu. Widok grupuje po nim, belkę podpisuje opisem."""
    obiekt, kamera, teleskop, filtr, exp, start, koniec = klucz
    return "|".join(str(v) for v in (obiekt, kamera, teleskop, filtr, exp,
                                     start.isoformat(), koniec.isoformat()))


def _grupa_zostawiona(czlonkowie):
    """Czy grupa ma werdykt „zostawiam wszystkie" (0026): KAŻDY bieżący członek ma wiersz werdyktu
    i wszystkie wiersze niosą JEDEN klucz gestu. Nowy stos w grupie (bez wiersza) albo zlanie dwóch
    grup z osobnymi werdyktami (dwa klucze) cofa grupę do roboty - człowiek nie widział tego zbioru.
    Klucza nie porównujemy z bieżącym identyfikatorem grupy: scalenie teleskopu zmienia identyfikator,
    a zbiór stosów zostaje ten sam (powód w 0026)."""
    klucze = {c["kept_key"] for c in czlonkowie}
    return None not in klucze and len(klucze) == 1


def _srodki_grupy(czlonkowie):
    """Etykiety ŚRODKA KADRU członków (`header.ra_deg`/`dec_deg`) - `{frame_id: 'A'|'B'|…}` albo `{}`.

    FAKT DO ROZRÓŻNIENIA, NIE ŚWIADEK WERSJI (AR-10). Kanały kamery kolorowej z dwóch przebiegów
    (NGC3034 RC8 600 s: `_X_WBPP2` wobec `_X`) rozróżniała dotąd tylko nazwa pliku; zmierzone na
    kopii archiwum 2026-10-03: trzy stosy `_WBPP2` mają jeden środek, cztery pozostałe (z
    `combined_RGB`) drugi, a każda karta poza pomiarami i środkiem jest wspólna. Świadkiem
    odrębności środek NIE jest: kanały jednej integracji LMC (5 środków na 6 stosów) i NGC4826
    (4 na 4) też mają różne - więc „inny środek" nie znaczy „inny przebieg", a tylko „inny kadr
    w nagłówku". Dlatego etykieta, nie werdykt, i tylko tam, gdzie dzieli grupę NIETRYWIALNIE:
    co najmniej dwa środki i co najmniej jeden wspólny dla dwóch stosów (wszystkie różne albo
    wszystkie równe nic człowiekowi nie mówią). Równość dokładna: obie wartości pochodzą z tego
    samego zapisu nagłówka, a zaokrąglenie skleiłoby kadry różniące się o ułamek sekundy łuku.
    Litery w porządku `frame_id` pierwszego stosu danego środka - stabilne między przeładowaniami."""
    srodki = {}
    for c in sorted(czlonkowie, key=lambda c: c["frame_id"]):
        if c["srodek"] is not None:
            srodki.setdefault(c["srodek"], []).append(c["frame_id"])
    if len(srodki) < 2 or all(len(f) < 2 for f in srodki.values()):
        return {}
    return {fid: chr(ord("A") + i) for i, fids in enumerate(srodki.values()) for fid in fids}


def _chwila_wersji(c):
    """Chwila integracji członka i jej źródło - `(napis ISO, 'signature'|'created')` albo
    `(None, None)`. Sygnatura bije `XISF:CreationTime`: to chwila przebiegu ImageIntegration, a druga
    to chwila zapisu pliku (zaraz po integracji, ale jednak inny fakt - powierzchnia mówi, który
    pokazuje). Druga jest jedyną datą stosów sprzed modułu XISF 1.1.2 (AR-10)."""
    podpis = signature_timestamp(c["tool"])
    if podpis:
        return podpis, "signature"
    if c.get("created"):
        return c["created"], "created"
    return None, None


def stack_version_groups(con):
    """Grupy bliźniaków (ten sam materiał, co najmniej dwa stosy) z rodzajem grupy i członków.

    Zwraca listę dictów, po grupie: `group_id` (stabilny identyfikator z klucza, `_id_grupy_wersji`),
    `object_canon`, `filter_canon`, `exptime` (float), `window_start`, `window_end` (ISO z żywego
    `header`, `_grupy_wersji`), `telescope` (nazwa teleskopu kanonicznego, `telescope_label`), `camera` (model
    kamery), `mono`, `kind` (`WERSJA_*`), `kept` (werdykt „zostawiam wszystkie", `_grupa_zostawiona`),
    `kept_at` (chwila werdyktu albo None) oraz `members` - dicty `frame_id`, `kind`, `witness` (token
    `VERSION_WITNESSES` albo None), `timestamp` + `timestamp_source` (`_chwila_wersji`: sygnatura,
    `XISF:CreationTime` albo None), `center` (etykieta środka kadru, `_srodki_grupy`, albo None),
    `center_radec` (`(ra, dec)` albo None), `declared_rows`; grupa niesie też `centers` (ile różnych
    środków). Porządek: obiekt, filtr, ekspozycja, okno,
    teleskop, kamera - ten sam, w którym powierzchnia ustawia nagłówki grup.

    Read-model milczy tekstem UI (zdanie składa widok z katalogu i18n) i nie filtruje po rodzaju:
    perspektywa bierze grupy wersji, raport pomiaru bierze wszystkie."""
    out = []
    for klucz, wiersze, mono, czlonkowie, rodzaje in _grupy_wersji(con):
        r0 = wiersze[0]
        srodki = _srodki_grupy(czlonkowie)
        out.append({
            "group_id": _id_grupy_wersji(klucz),
            "telescope": telescope_label(r0), "camera": r0["camera_model"],
            "object_canon": r0["object_canon"], "filter_canon": r0["filter_canon"],
            "exptime": _to_float(r0["exptime"]),
            "window_start": r0["window_start"], "window_end": r0["window_end"], "mono": mono,
            "kind": _rodzaj_grupy([rodzaje[c["frame_id"]][0] for c in czlonkowie]),
            "kept": _grupa_zostawiona(czlonkowie),
            "kept_at": (max(c["kept_at"] for c in czlonkowie)
                        if _grupa_zostawiona(czlonkowie) else None),
            "centers": len({c["srodek"] for c in czlonkowie if c["srodek"] is not None}),
            "members": [{"frame_id": c["frame_id"], "kind": rodzaje[c["frame_id"]][0],
                         "witness": rodzaje[c["frame_id"]][1],
                         "timestamp": _chwila_wersji(c)[0],
                         "timestamp_source": _chwila_wersji(c)[1],
                         "center": srodki.get(c["frame_id"]), "center_radec": c["srodek"],
                         "declared_rows": c["declared"]} for c in czlonkowie],
        })
    out.sort(key=lambda g: (natural_key(g["object_canon"] or ""), g["filter_canon"] or "",
                            g["exptime"] if g["exptime"] is not None else -1.0,
                            str(g["window_start"]), g["telescope"] or "", g["camera"] or ""))
    return out


def stack_version_frame_ids(con):
    """Zbiór frame_id perspektywy „Wersje stosów": WSZYSCY członkowie grup, w których co najmniej dwa
    stosy mają dowód odrębnej integracji.

    JEDEN właściciel predykatu dla trimu gridu i licznika Porządków - jak `dup_frame_ids`. Członek
    bez dowodu (pochodna, nieustalony) zostaje w zbiorze, bo NALEŻY do grupy: człowiek decyduje
    o całej grupie i ma widzieć także to, czego maszyna nie umiała rozstrzygnąć. Grupy wyłącznie
    pochodne i nieustalone wypadają - rozbicie jednej integracji na kanały (LMC: `R`/`G`/`B`,
    `combined_RGB`, `drizzle`) nie jest wersją do sprzątania. Zwraca set[int].

    Grupy z werdyktem „zostawiam wszystkie" ZOSTAJĄ w zbiorze: perspektywa jest jedynym miejscem,
    gdzie werdykt widać i skąd się go cofa. Robotę (plakietkę) liczy `stack_version_open_frame_ids`."""
    return _zbiory_wersji(con)[0]


def stack_version_open_frame_ids(con):
    """Podzbiór `stack_version_frame_ids` w grupach BEZ werdyktu „zostawiam wszystkie" - ROBOTA
    wiersza Porządków (AR-10). Zwraca set[int]."""
    return _zbiory_wersji(con)[1]


def _zbiory_wersji(con):
    """Oba zbiory wersji - `(wszystkie, otwarte)` - z JEDNEGO przebiegu `_grupy_wersji`, więc
    otwarte są podzbiorem z konstrukcji. Dwa niezależne przebiegi rozjeżdżały się przy etapie
    piszącym w tle (Stosy dopisują integracje między nimi): wiersz Porządków mówił „6 z 5",
    a podpowiedź liczyła ujemną liczbę stosów z werdyktem. `tasks_state` woła to raz."""
    wszystkie, otwarte = set(), set()
    for _k, _w, _m, czlonkowie, rodzaje in _grupy_wersji(con):
        if _rodzaj_grupy([rodzaje[c["frame_id"]][0] for c in czlonkowie]) != WERSJA_INNA:
            continue
        ids = {c["frame_id"] for c in czlonkowie}
        wszystkie |= ids
        if not _grupa_zostawiona(czlonkowie):
            otwarte |= ids
    return wszystkie, otwarte


def stack_version_group_of(con, frame_id):
    """Grupa wersji stosu `frame_id` pod gest werdyktu - dict `group_id`, `frame_ids` (posortowane),
    `kind` (`WERSJA_*`), `kept` - albo `None`, gdy stos nie należy do żadnej grupy bliźniaków.
    Liczona od nowa w chwili gestu, jak `keep_version_plan`: między pokazaniem menu a kliknięciem
    mógł przejść skan."""
    for klucz, _w, _m, czlonkowie, rodzaje in _grupy_wersji(con):
        ids = sorted(c["frame_id"] for c in czlonkowie)
        if frame_id in ids:
            return {"group_id": _id_grupy_wersji(klucz), "frame_ids": ids,
                    "kind": _rodzaj_grupy([rodzaje[i][0] for i in ids]),
                    "kept": _grupa_zostawiona(czlonkowie)}
    return None


def keep_version_plan(con, frame_id):
    """Plan gestu „Zostaw tę wersję": ścieżki OBECNYCH kopii pozostałych wersji z grupy stosu
    `frame_id` - albo `None`, gdy stos nie należy do żadnej grupy bliźniaków.

    „Pozostała wersja" to członek z dowodem odrębności WZGLĘDEM ZOSTAWIANEGO (`_para_odrebna`), nie
    członek z etykietą „inna integracja" w ogóle: pochodna zostawianej wersji należy do niej i do
    schowka nie trafia, a członek bez dowodu względem niej też nie - ścieżka w schowku jest
    podpowiedzią do skasowania, a podpowiadać wolno wyłącznie z dowodem. Pominiętych liczymy, żeby
    zdanie po geście powiedziało, czego NIE skopiowano i dlaczego.

    Wszystkie obecne kopie, nie jedna: wersja z dwiema kopiami zostaje na dysku, dopóki leży
    którakolwiek z nich. Zwraca dict: `paths` (w porządku frame_id, location.id), `stacks` (ile
    stosów pozostałych wersji), `unknown` (ilu członków bez dowodu względem zostawianego),
    `derived` (ile pochodnych zostawianej wersji), `kept` (grupa ma werdykt „zostawiam wszystkie" -
    z tego samego przebiegu, bo gest przy werdykcie przeczyłby mu i ma odmówić)."""
    for _klucz, _wiersze, mono, czlonkowie, _rodzaje in _grupy_wersji(con):
        zostaje = next((c for c in czlonkowie if c["frame_id"] == frame_id), None)
        if zostaje is None:
            continue
        inni = [c for c in czlonkowie if c["frame_id"] != frame_id]
        wersje = [c["frame_id"] for c in inni if _para_odrebna(zostaje, c, mono)]
        pochodne = sum(1 for c in inni if _para_pochodna(zostaje, c))
        sciezki = [r["path"] for r in con.execute(
            "SELECT path FROM location WHERE present = 1 "
            "AND frame_id IN (SELECT value FROM json_each(?)) ORDER BY frame_id, id",
            (json.dumps(wersje),)).fetchall()]
        return {"paths": sciezki, "stacks": len(wersje), "derived": pochodne,
                "unknown": len(inni) - len(wersje) - pochodne,
                "kept": _grupa_zostawiona(czlonkowie)}
    return None


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
    więc pomija je bez wyjątku (§4.3 briefu) - ale od D-V-9f NIE bez słowa: pasek kryteriów
    nazywa pominięte warunki (`grid._nieznane_warunki`), bo pominięcie poszerza zbiór."""
    out = []
    for r in _po_nazwie_naturalnie(
            con.execute("SELECT name, spec_json FROM saved_query").fetchall(), "name"):
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

    `raw_unreferenced` (G2-1d, 0020) to UWAGA obok werdyktu: ile RAW-ów przebieg nie umiał
    umieścić w czasie przy stosie, którego werdykt mówi co innego (pula mieszana RAW+FITS).

    Zwraca: integration_id, unresolved_reason, degenerate, ambiguous, telescope_mismatch,
    declared_rows, drizzle_inputs, disabled_inputs, tool, window_start, window_end,
    utc_offset_min, raw_unreferenced, inputs, excluded, secs, sources (rozdzielone przecinkiem
    źródła pewności wejść), twins, shared."""
    return con.execute(
        "SELECT i.id AS integration_id, i.unresolved_reason, i.degenerate, i.ambiguous, "
        "       i.telescope_mismatch, i.declared_rows, i.drizzle_inputs, i.disabled_inputs, "
        "       i.tool, i.window_start, i.window_end, i.utc_offset_min, i.raw_unreferenced, "
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
    Zwraca dict `{klucz wiersza Porządków: liczba}` - po jednym liczniku na wiersz `tasks._TASKS`
    (liczby kluczy tu nie podajemy: rośnie z każdym wierszem, a zapisana raz rozjeżdżała się
    z kodem; komplet pinuje `test_tasks_state_liczniki_na_s8_obj` w `tests/test_gui_queries.py`).

    Licznika `xisf_frames` NIE MA od P6c: był informacją „nagłówków XISF nie umiemy zapisać", a ta
    przestała być prawdziwa razem z pisarzem — licznik samego formatu nie jest ani zadaniem, ani
    osobliwością (liczbę plików XISF pokazuje facet formatu w Zbiorach)."""
    telescopes_unlabeled = con.execute(
        "SELECT COUNT(*) FROM telescope WHERE label IS NULL AND merged_into IS NULL"
    ).fetchone()[0]
    observatories_unnamed = con.execute(
        "SELECT COUNT(*) FROM observatory WHERE name IS NULL AND merged_into IS NULL"
    ).fetchone()[0]
    wersje, wersje_otwarte = _zbiory_wersji(con)
    return {
        "unresolved_lights": len(review_frame_ids(con)),
        # Nagłówek mówi co innego niż zatwierdzony folder (E5-2) - robota: plik przeczy gestowi
        # człowieka, a rozstrzyga człowiek (makro karty w pliku albo „Przypisz obiekt"). Ten sam
        # predykat, co trim perspektywy.
        "path_header_conflict_frames": len(path_header_conflict_frame_ids(con)),
        # 0022/Q8: kopia po przerwanym zapisie w miejscu - izolowana od skanu do odzysku albo
        # zwolnienia ręką. Ten sam predykat co trim perspektywy.
        "torn_write_frames": len(torn_write_frame_ids(con)),
        # Warunek wsadu AR-17 (1): plik zapisany i zweryfikowany, baza jeszcze nie - kopia izolowana
        # do dokończenia (albo powrotu / zwolnienia ręką). Ten sam predykat co trim perspektywy.
        "pending_finish_frames": len(pending_finish_frame_ids(con)),
        "stacks_lineage_pending": len(lineage_pending_frame_ids(con)),
        "dup_frames": len(dup_frame_ids(con)),
        # Kopie niezgodne ze sobą (0021) - podzbiór duplikatów, ten sam predykat co trim perspektywy.
        # JEST robotą (poza `tasks._BEZ_ROBOTY`): oś klatki zależy od tego, która kopia wygrała
        # w `header`, a sprzeczność rozstrzyga wyłącznie człowiek.
        "copy_conflict_frames": len(copy_conflict_frame_ids(con)),
        # Zeznanie z nieobecnej kopii - robota: `header` mówi głosem pliku, którego nie ma. Kopię
        # wiodącą wskazuje człowiek (AR-4) przy ≥2 obecnych kopiach albo zeznaniu z ręki; resztę
        # naprawia etap Dostawy, ale tylko pod swoim korzeniem - więc liczone są wszystkie.
        "orphan_testimony_frames": len(orphan_testimony_frame_ids(con)),
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
        # Wersje stosów - liczba STOSÓW perspektywy (ten sam predykat, co trim), nie liczba grup:
        # wiersz i lista pod klikiem liczą to samo.
        "stack_versions": len(wersje),
        # DRUGA LICZBA TEGO SAMEGO WIERSZA (AR-10), nie osobny wiersz: ile z tych stosów stoi
        # w grupach BEZ werdyktu „zostawiam wszystkie". Ona rozstrzyga, czy wiersz jest robotą
        # (plakietka, pogrubienie) - lista pod klikiem dalej pokazuje wszystkie, bo tam werdykt
        # się widzi i cofa. Podzbiór pierwszej z konstrukcji - obie z jednego przebiegu grup.
        "stack_versions_open": len(wersje_otwarte),
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

    Zwraca `(grupy, pominiete)`, gdzie grupa to dict `{object_id, canon, catalog, kind,
    frame_ids}` — po jednej na OBIEKT, bo klinga osi przyjmuje jeden kanon na wywołanie, a masowe
    cofnięcie potrafi objąć klatki kilku różnych obiektów naraz. `object_id` jedzie w grupie nie
    dla zapisu (klinga pisze po KANONIE), tylko jako ZAMROŻONY STAN dla guardu dryfu
    (`repo.user_assign_object(expected_cleared_id=…)`, bramka pakietu 0810). `pominiete` to dict
    `{skipped_kind, skipped_nothing, skipped_no_memory}` - reszta zaznaczenia rozbita per fakt.

    KLASYFIKUJE CAŁE ZAZNACZENIE, NIE SAME NAGROBKI (FC-6, R-S2b-13). Oba sąsiednie gesty tej osi
    dostają całe zaznaczenie i odsiewają je licznikami klingi, więc ich „N z M" liczy M po
    zaznaczeniu. Ten gest podawał klindze wyłącznie klatki z grup, więc jego „z M" liczyło same
    nagrobki z pamięcią - firsthand zmierzył na jednym zrzucie „120 zaznaczonych" obok „30 z 30",
    gdy sąsiad w tej samej sytuacji mówi „6 z 354". Klatki spoza grup nie liczyły się nigdzie.
    Klasyfikacja siedzi TUTAJ, a nie w klindze, bo do klingi przywracania trafiają wyłącznie grupy.
    Kolejność guardów jak u obu sąsiadów: rodzaj rozstrzyga PIERWSZY (kalibracja obiektu nie ma
    z definicji, więc pytanie o nagrobek byłoby przy niej bez przedmiotu), potem „czy to nagrobek"
    (`skipped_nothing` - nie było czego przywrócić), potem „czy pamięta przedmiot"
    (`skipped_no_memory` - baza-dawca sprzed migracji 0017).

    DICT, NIE `repo.ObjectGesture`: read-model nie importuje warstwy zapisu, więc oddaje same
    liczby pod NAZWAMI PÓL gestu, a wołający składa z nich gest (`ObjectGesture(**pominiete)`).

    ID SPOZA `frame` TO `ValueError`, NIE CISZA (EXPECT): niezmiennik `assigned + skipped ==
    len(ids)` nie ma prawa trzymać się na id, którego baza nie zna - i obie sąsiednie klingi osi
    rzucają przy takim id ten sam wyjątek.

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
    ids = list(frame_ids)
    rows = con.execute(
        "SELECT f.id AS frame_id, f.kind AS frame_kind, f.object_source, "
        "       o.id AS object_id, o.canon, o.catalog, o.kind "
        "FROM frame f LEFT JOIN object o ON o.id = f.object_cleared_id "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "ORDER BY o.canon, f.id",
        (json.dumps(ids),)).fetchall()
    if len(rows) < len(set(ids)):
        brak = sorted(set(ids) - {r["frame_id"] for r in rows})
        raise ValueError(f"frame nie istnieje - id: {', '.join(str(i) for i in brak)}")
    grupy = {}
    pominiete = {"skipped_kind": 0, "skipped_nothing": 0, "skipped_no_memory": 0}
    for r in rows:
        if r["frame_kind"] not in LIGHT_KINDS:
            pominiete["skipped_kind"] += 1
            continue
        if r["object_source"] != "user_cleared":
            pominiete["skipped_nothing"] += 1
            continue
        if r["object_id"] is None:
            pominiete["skipped_no_memory"] += 1
            continue
        g = grupy.setdefault(r["object_id"], {"object_id": r["object_id"], "canon": r["canon"],
                                              "catalog": r["catalog"], "kind": r["kind"],
                                              "frame_ids": []})
        g["frame_ids"].append(r["frame_id"])
    return _po_nazwie_naturalnie(grupy.values(), "canon"), pominiete


def rename_frame_targets(con, frame_ids):
    """Dla zbioru frame_id: fakty do `compose_name` (kind/filter_canon/object_canon/object_raw/
    sha1_data/date_obs/exptime — frame+header) + KAŻDA OBECNA (`present=1`) location z `path`+`mtime`
    (kotwica anty-stale renamu). Frame BEZ obecnej kopii → wiersz z location_id NULL (silnik odróżni
    „brak kopii" od wielu, licząc wiersze per frame). Rename DOZWOLONY dla XISF (nie tyka nagłówka),
    więc BEZ `header_hash`/`compressed` (nieistotne). frame_ids jako TABLICA JSON (`json_each`, jeden
    param — §4). ORDER BY frame_id, location_id. Zwraca: frame_id, filetype, kind, filter_canon,
    sha1_data, object_canon, object_raw, date_obs, exptime, location_id, path, mtime, flat_master_id,
    flat_paths. Ogniwo flatu (token flatgrp) idzie PODZAPYTANIAMI skalarnymi, nie JOIN-em: wiele kopii
    mastera nie mnoży wierszy frame'a (silnik czyta liczbę wierszy jako liczbę kopii LIGHTA).
    `flat_paths` = tablica JSON ścieżek obecnych kopii mastera flat (`[]` gdy brak)."""
    return con.execute(
        "SELECT f.id AS frame_id, f.filetype, f.kind, f.filter_canon, f.sha1_data, "
        "       obj.canon AS object_canon, h.object_raw, h.date_obs, h.exptime, "
        "       l.id AS location_id, l.path, l.mtime, "
        "       (SELECT c.master_frame_id FROM calibration c "
        "         WHERE c.light_frame_id = f.id AND c.relation = 'flat') AS flat_master_id, "
        "       (SELECT json_group_array(fl.path) FROM calibration c "
        "          JOIN location fl ON fl.frame_id = c.master_frame_id AND fl.present = 1 "
        "         WHERE c.light_frame_id = f.id AND c.relation = 'flat') AS flat_paths "
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


def pending_cards_for_run(con, run_id):
    """Oczekujące wpisy stagingu przebiegu z klatką pod ich LOCATION - jednym zapytaniem (podgląd
    szuflady po edycji komórki, AR-61; dawniej osobny `frame_for_location` na każdy wpis, czyli
    koszt rosnący kwadratowo z serią edycji). Kopia bez wiersza `location` wypada (INNER JOIN), jak
    wypadała przy mapowaniu pojedynczym. Kolejność `id` = kolejność stagingu. Zwraca: frame_id,
    keyword, op, old_value, new_value, new_comment."""
    return con.execute(
        "SELECT l.frame_id, p.keyword, p.op, p.old_value, p.new_value, p.new_comment "
        "FROM pending_changes p JOIN location l ON l.id = p.location_id "
        "WHERE p.run_id = ? AND p.status = 'pending' ORDER BY p.id",
        (run_id,)).fetchall()


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


# --- WYDANIE OBIEKTU: teczki gotowości (okno wyboru „Wydaj obiekt…") ---

def readiness_pct(n, total):
    """Procent na ekran teczek: 0 i 100 WYŁĄCZNIE wtedy, gdy są prawdą, środek ścięty do 1..99.
    Zwykłe zaokrąglenie dałoby „100" przy 344 z 345 lightów obok bursztynowej kropki (stan liczy się
    z liczb, nie z procentu) i „0" przy jednym lighcie z tysiąca - a kolumna ma odróżniać „nic" od
    „prawie nic", bo to dwie różne roboty przed WBPP."""
    if not total or not n:
        return 0
    if n >= total:
        return 100
    return min(max(n * 100 // total, 1), 99)


def release_readiness(con, *, window_days=RAW_FLAT_WINDOW_DAYS):
    """Teczki wydania obiektu do WBPP - jeden wiersz na obiekt z AKTYWNYMI lightami, godzinami
    malejąco (pierwsze na liście to obiekty, na które jest najwięcej materiału).

    Populacja ta sama co `projection.plan_object` (`kind='light'`, obiekt, bez `retired_at`
    i `superseded_by`; obecność kopii NIE odsiewa - plan kładzie taki light do `skipped`, więc teczka
    i podgląd wydania liczą tych samych ludzi). Noc z definicji facetu Noc (`date(date_obs,
    '-12 hours')`, D-UX-1). Zestaw to folder wydania, nie config: tożsamość (teleskop kanoniczny,
    kamera) bierze się z mapy planisty (`projection.zestawy_configow`), bo configi scalonego teleskopu
    przy tej samej kamerze lądują w JEDNYM folderze, a goły DISTINCT `config_id` policzyłby je dwa
    razy; light bez configu to jeden zestaw `_UNSET`, jak w planie. Import leniwy - `projection`
    importuje ten moduł. Master flat i master dark ze STANU `calibration`; surowe flaty i `pending`
    z `lineage.raw_flats_for` - tej samej derywacji, którą wydanie potem pakuje, nie z przybliżenia.

    `pending` (master JEST, rodowód go nie przeliczył) ma własne pole i NIGDY nie wlicza się do
    braku flatu: zakup klatek i jedno kliknięcie w Dostawie to dwie różne wiadomości. Stan: `green`
    = każdy light ma master flat i master dark; `red` = żaden nie ma flatu (mastera, surowych ani
    `pending`) i żaden nie ma darka; reszta `amber`. Stan liczy się z LICZB, procenty
    (`readiness_pct`) są tylko do ekranu.

    Koszt stały w liczbie zapytań: jedno po lighty archiwum, jedno po tabelę `config` (mapa zestawów)
    i jedno wywołanie `raw_flats_for` na lightach bez master flatu (ono samo ma stałą liczbę zapytań);
    zmierzone na kopii żywej `pf4` (73 obiekty, 2026-10-09) ~120 ms. Zwraca listę dictów: object_id,
    canon, lights, hours, nights, zestawy, n_master_flat, n_master_dark, n_raw_flat, n_pending,
    pct_master_flat, pct_master_dark, pct_raw_flat, pct_pending, last_night, stan."""
    rows = con.execute(
        "SELECT f.id AS frame_id, f.object_id, o.canon, f.config_id, h.exptime, "
        "       date(h.date_obs, '-12 hours') AS night, "
        "       EXISTS (SELECT 1 FROM calibration c WHERE c.light_frame_id = f.id "
        "               AND c.relation = 'flat') AS master_flat, "
        "       EXISTS (SELECT 1 FROM calibration c WHERE c.light_frame_id = f.id "
        "               AND c.relation = 'dark') AS master_dark "
        "FROM frame f JOIN object o ON o.id = f.object_id "
        "LEFT JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind = 'light' AND f.retired_at IS NULL AND f.superseded_by IS NULL "
        "ORDER BY f.object_id, f.id").fetchall()
    picks = raw_flats_for(con, [r["frame_id"] for r in rows if not r["master_flat"]],
                          window_days=window_days)
    from horreum import projection                     # leniwie: projection importuje queries
    zestaw_configu = projection.zestawy_configow(con)
    teczki = {}
    for r in rows:
        t = teczki.setdefault(r["object_id"], {
            "canon": r["canon"], "lights": 0, "secs": 0.0, "nights": set(), "zestawy": set(),
            "mf": 0, "md": 0, "raw": 0, "pending": 0})
        t["lights"] += 1
        t["secs"] += float(r["exptime"] or 0.0)
        t["zestawy"].add(zestaw_configu.get(r["config_id"], (None, None))[0])
        if r["night"] is not None:
            t["nights"].add(r["night"])
        t["md"] += bool(r["master_dark"])
        if r["master_flat"]:
            t["mf"] += 1
            continue
        pick = picks.get(r["frame_id"])
        if pick is not None and pick.frame_ids:
            t["raw"] += 1
        elif pick is not None and pick.gap == "pending":
            t["pending"] += 1
    out = []
    for oid, t in teczki.items():
        n = t["lights"]
        if t["mf"] == n and t["md"] == n:
            stan = "green"
        elif not (t["mf"] or t["raw"] or t["pending"] or t["md"]):
            stan = "red"
        else:
            stan = "amber"
        out.append({
            "object_id": oid, "canon": t["canon"], "lights": n, "hours": t["secs"] / 3600.0,
            "nights": len(t["nights"]), "zestawy": len(t["zestawy"]),
            "n_master_flat": t["mf"], "n_master_dark": t["md"], "n_raw_flat": t["raw"],
            "n_pending": t["pending"],
            "pct_master_flat": readiness_pct(t["mf"], n), "pct_master_dark": readiness_pct(t["md"], n),
            "pct_raw_flat": readiness_pct(t["raw"], n), "pct_pending": readiness_pct(t["pending"], n),
            "last_night": max(t["nights"]) if t["nights"] else None, "stan": stan})
    out.sort(key=lambda r: (-r["hours"], r["canon"].lower(), r["object_id"]))
    return out


def sole_light_object(con, frame_ids):
    """Obiekt, którego lighty niesie zbiór gridu, gdy jest DOKŁADNIE jeden - inaczej `None`.
    Karmi preselekcję okna teczek: user, który właśnie patrzy na NGC6992, nie ma go szukać drugi
    raz. Lighty bez obiektu nie głosują (nie należą do żadnej teczki); dwa obiekty w zbiorze to
    wybór, którego okno nie zgaduje."""
    rows = con.execute(
        "SELECT DISTINCT f.object_id FROM frame f "
        "WHERE f.kind = 'light' AND f.object_id IS NOT NULL "
        "AND f.id IN (SELECT value FROM json_each(?)) LIMIT 2",
        (json.dumps(list(frame_ids)),)).fetchall()
    return rows[0]["object_id"] if len(rows) == 1 else None


def object_canon(con, object_id):
    """Kanon obiektu po id albo `None`, gdy takiego obiektu nie ma. Nagłówek okna wydania mówi, CO
    wydaje, zanim policzy się plan: ten czeka na cel i sondę, a nazwa obiektu ani jednego, ani
    drugiego nie potrzebuje."""
    row = con.execute("SELECT canon FROM object WHERE id = ?", (object_id,)).fetchone()
    return None if row is None else row["canon"]


def copy_facts_class(con, *, porownywalne=False) -> list[int]:
    """KLASA KANDYDATA uzupełnienia faktów kopii (0021) - id klatek (rosnąco), których kopie
    uzupełnienie w ogóle czyta: XISF (liczba i role obrazów żyją tylko tam; nie w trybie
    `porownywalne`) albo klatka z więcej niż jedną lokacją OGÓŁEM (tylko tam jest z czym porównywać
    zeznanie). Pojedynczy FITS do klasy nie należy - fakty dostaje przy najbliższym odczycie skanem.

    JEDYNY LITERAŁ TEJ REGUŁY (SPOT, AR-35): czyta go `scan.copy_facts_candidates` (etap Dostawy,
    liczniki „nie wiem") i read-model gridu (`base_rows`, flaga `copy_facts_class` → „?" w kolumnie
    „Obrazy"). Dawniej komórka liczyła klasę lustrem po stronie Pythona - etap, który fakty zbiera,
    i komórka, która mówi „jeszcze nie wiem", mogły rozjechać się co do tego, kto czeka.

    Mieszka w read-modelu, nie w `scan`: predykat jest czystym odczytem, a `scan` ciągnie numpy
    i astropy - import stąd łamałby konwencję „queries bez astropy" (konsumenci CLI: `sky`,
    `targets`, `presence`, `projection`). `scan` importuje ten moduł leniwie (wzór
    `orphan_testimony_routes`)."""
    return [r[0] for r in con.execute(
        "SELECT f.id FROM frame f "
        "WHERE (f.filetype = 'xisf' AND ? = 0) OR f.id IN ("
        "       SELECT frame_id FROM location GROUP BY frame_id HAVING COUNT(*) > 1) "
        "ORDER BY f.id",
        (int(porownywalne),))]


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
    object_cleared_canon, date_obs, exptime, path, present, last_verified_at, superseded_by,
    retired_at, n_present, n_vanished, vanished_path, image_count, copy_facts_class, absorbed, night,
    note. Wiersze czyta
    się po NAZWIE (`sqlite3.Row`), ale kolejność w tym zdaniu ma zgadzać się z SELECT-em - rozjazd
    był zarzutem bramki 0809 i jest tańszy do naprawienia niż do wytłumaczenia następnej sesji.

    `night` i `note` karmią prosty zestaw kolumn prezentacji Znajdź (Noc, Uwagi) i stoją NA KOŃCU
    SELECT-u: konsumenci spoza gridu (`app`, `projection`) czytają po nazwie, więc dopisane kolumny
    nie zmieniają ich zachowania. Noc tą samą derywacją co facet Noc (`facet_nights`) - kolumna
    i kubełek listwy nie mogą nazwać tej samej klatki dwiema różnymi nocami. Uwaga to wiersz
    `frame_note` (0032, PK = klatka), więc LEFT JOIN nie mnoży wierszy.

    `copy_facts_class` (0/1, AR-35) = klatka należy do KLASY kandydata uzupełnienia faktów kopii
    (`copy_facts_class`: XISF albo >1 lokacja ogółem) - komórka „Obrazy" mówi przy niej „?"
    zamiast pustki. Zbiór klatek liczy JEDEN literał (`copy_facts_class`), tu jest tylko przynależność;
    dawniej komórka powtarzała ten predykat lustrem po stronie Pythona (SIN-DUP). Koszt: jeden
    SELECT klasy (~550 klatek kopii archiwum, ~9 ms na kopii żywej bazy) na wywołanie.

    `image_count` (0021) to liczba obrazów POKAZANEJ kopii - karmi kolumnę „Obrazy". Klatka z kilkoma
    obecnymi kopiami dostaje w gridzie wszystkie różne wartości z `present_copy_facts` (osobne, wąskie
    zapytanie tylko o duplikaty), więc ta kolumna mówi prawdę dla reszty archiwum bez drugiego
    podzapytania na 16 tys. wierszy.

    KOPIA NIEOBECNA NIE ZEZNAJE: klatka bez obecnej kopii pokazuje adres martwej (historia
    przeprowadzki), ale jej `image_count` to zeznanie pliku, którego już nie ma - kolumna „Obrazy"
    mówiłaby o stanie dysku nieprawdę. Dlatego `CASE present = 1`: wiersz pokazany z martwej kopii
    dostaje NULL, czyli „nie wiem", a nie liczbę po pliku, który zniknął.

    `object_source` i `object_cleared_canon` KARMIĄ POLITYKĘ KOLUMNY (`object_cell`, R-S3-4), a NIE
    nową kolumnę na ekranie: `BASE_COLS` gridu zostaje bez zmian, więc podłoga okna się nie rusza
    (kanon minimalnego wspieranego ekranu). Kosztu nie ma — `frame` jest już w `FROM`.

    KANON, NIE `object_cleared_id` (FC-1): do tej paczki jechał tu goły FK i zapis ten twierdził,
    że KARMI politykę kolumny - a polityka go nie czytała, bo do narysowania nagrobka potrzebna jest
    NAZWA, nie klucz. Efekt: 417 nagrobków renderowało się jednakowo, choć baza pamiętała, co każdy
    z nich zdjął. JOIN po kluczu głównym `object`, więc kosztu na 16 901 wierszach nie widać;
    `object_cleared_id` nie miał w tym zapytaniu ANI JEDNEGO czytelnika (grep `horreum/` + testy).

    `superseded_by` JEST KOLUMNĄ Z TEGO SAMEGO POWODU, CO `present` (F3, decyzja Zdzinia 2026-08-09):
    klatka zastąpiona ZOSTAJE w gridzie i ma być WIDOCZNA JAKO ZASTĄPIONA — w każdej perspektywie,
    nie tylko we własnej. Bez niej wiersz wyglądał identycznie jak żywa klatka bez kopii, a jedyną
    różnicą było puste pole ścieżki, czyli brak informacji udawał informację.

    `absorbed` (0/1, AR-42) = klatka zastąpiona jest WCHŁONIĘTYM szkieletem (`repo.absorbed_frame_ids`,
    ten sam predykat, który zdejmuje ją z perspektywy „Zastąpione") - komórka mówi wtedy „wchłonięta
    przez #N", nie „zastąpiona": plik wyzdrowiał, treść się nie zmieniła. Ogniwo do następczyni
    zostaje w zdaniu. Koszt jak `copy_facts_class`: jeden SELECT zbioru na wywołanie.

    `last_verified_at` NA WIERSZU `present=0` JEST CHWILĄ ZNIKNIĘCIA: jedyną drogą zapisu `present=0`
    jest `repo.mark_location_vanished`, a ona stempluje tę kolumnę tym samym `now`, którym emituje
    `event(location.vanished)` (`repo.py`). Dla kopii OBECNEJ ta sama kolumna znaczy „ostatnio
    zweryfikowana" — interpretacja należy do wołającego, dlatego alias jest surowy, nie `vanished_at`."""
    return con.execute(
        "SELECT f.id AS frame_id, f.kind, f.filetype, f.filter_canon, "
        "       cam.model_canon AS camera_model, "
        "       t.label AS telescope_label, t.telescop_canon, "
        "       obj.canon AS object_canon, h.object_raw, f.object_source, "
        "       ocl.canon AS object_cleared_canon, "
        "       h.date_obs, h.exptime, loc.path, loc.present, loc.last_verified_at, f.superseded_by, "
        "       f.retired_at, "
        "       (SELECT COUNT(*) FROM location lp WHERE lp.frame_id = f.id AND lp.present = 1) AS n_present, "
        "       (SELECT COUNT(*) FROM location lv WHERE lv.frame_id = f.id AND lv.present = 0) AS n_vanished, "
        "       (SELECT lw.path FROM location lw WHERE lw.frame_id = f.id AND lw.present = 0 "
        "         ORDER BY lw.id LIMIT 1) AS vanished_path, "
        "       CASE WHEN loc.present = 1 THEN loc.image_count END AS image_count, "
        "       f.id IN (SELECT value FROM json_each(?)) AS copy_facts_class, "
        "       f.id IN (SELECT value FROM json_each(?)) AS absorbed, "
        "       date(h.date_obs, '-12 hours') AS night, fn.body AS note "
        "FROM frame f "
        "LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN telescope t ON t.id = tc.canon_id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "LEFT JOIN object obj ON obj.id = f.object_id "
        "LEFT JOIN object ocl ON ocl.id = f.object_cleared_id "
        "LEFT JOIN frame_note fn ON fn.frame_id = f.id "
        "LEFT JOIN location loc ON loc.id = COALESCE("
        "        (SELECT MIN(id) FROM location WHERE frame_id = f.id AND present = 1), "
        "        (SELECT MIN(id) FROM location WHERE frame_id = f.id)) "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "ORDER BY f.id",
        (json.dumps(copy_facts_class(con)), json.dumps(sorted(absorbed_frame_ids(con))),
         json.dumps(list(frame_ids))),
    ).fetchall()


# ---- Znajdź i Uwagi: read-model (zapis uwag wyłącznie klingą `repo`) ----

def notes_for(con, frame_ids):
    """Bieżące uwagi zaznaczenia - `{frame_id: treść}`, klatka bez uwagi nie ma wpisu. Czyta je gest
    „Uwagi…" przed oknem (okno bazy nie dotyka) i recepta cofnięcia, która żyje, dopóki uwagi celu
    są wciąż tymi, które gest zostawił."""
    return {int(r[0]): r[1] for r in con.execute(
        "SELECT frame_id, body FROM frame_note WHERE frame_id IN (SELECT value FROM json_each(?))",
        (json.dumps(list(frame_ids)),)).fetchall()}


def note_hits(con, text):
    """Klatki, których uwaga ZAWIERA `text` - bez wielkości liter, posortowane po `frame_id`.

    Porównanie w Pythonie (`casefold`) po CAŁEJ tabeli, nie `LIKE`/`lower()`: SQLite składa wielkość
    liter wyłącznie w ASCII, więc „Łuna" nie trafiałoby „łuna" - a uwagi pisze się po polsku. Tabela
    jest mała (jedna krótka uwaga na klatkę z ręki). Igła przechodzi TĘ SAMĄ normalizację co treść
    w klindze zapisu (`repo.normalize_note`), więc podwójna spacja w polu Znajdź nie gubi trafienia."""
    igla = normalize_note(text).casefold()
    return sorted(int(fid) for fid, body in con.execute(
        "SELECT frame_id, body FROM frame_note").fetchall() if igla in str(body).casefold())


def find_rigs(con):
    """Zestawy (teleskop kanoniczny + kamera) z etykietą `<teleskop>_<kamera>` - słownik tokenu
    `zestaw:` w Znajdź. Lista dictów `label, telescope_id, telescope_label, camera_id, camera`,
    jeden wpis na tożsamość zestawu.

    ETYKIETA TA SAMA, CO NAZWA FOLDERU ZESTAWU W WYDANIU (`projection.zestawy_configow`, SPOT):
    user wpisuje to, co widzi w celu wydania, a druga reguła etykiety rozjechałaby się z nią przy
    pierwszej kolizji nazw (`_cfgN`). Config bez teleskopu albo bez kamery nie jest zestawem, który
    da się wskazać - wypada (JOIN)."""
    from horreum import projection                     # leniwie: projection importuje queries
    foldery = projection.zestawy_configow(con)
    out, widziane = [], set()
    for r in con.execute(
            "SELECT c.id AS config_id, tc.canon_id AS telescope_id, c.camera_id AS camera_id, "
            "       t.label AS telescope_label, t.telescop_canon, cam.model_canon AS camera_model "
            "FROM config c "
            "JOIN telescope_canonical tc ON tc.id = c.telescope_id "
            "JOIN telescope t ON t.id = tc.canon_id "
            "JOIN camera cam ON cam.id = c.camera_id "
            "ORDER BY c.id").fetchall():
        klucz = (r["telescope_id"], r["camera_id"])
        if klucz in widziane or r["config_id"] not in foldery:
            continue
        widziane.add(klucz)
        out.append({"label": foldery[r["config_id"]][0], "telescope_id": r["telescope_id"],
                    "telescope_label": telescope_label(r), "camera_id": r["camera_id"],
                    "camera": r["camera_model"] or ""})
    return out

# --- DOM: „Co mam" i ostatni gest ręki (ekran `gui/home.py`) ---

def home_summary(con):
    """„Co mam" na Domu - jedna linia sum archiwum: obiekty, lighty, godziny, noce, ostatnia noc.

    POPULACJA TA SAMA, CO TECZKI WYDANIA (`release_readiness`): aktywny light (`kind='light'`, bez
    `retired_at` i `superseded_by`) Z OBIEKTEM. Obie liczby stoją na jednym ekranie, więc liczone
    po różnych zbiorach przeczyłyby sobie nawzajem; light bez obiektu nie ma teczki i czeka
    w Porządkach. Noc z definicji facetu Noc (`date(date_obs, '-12 hours')`, D-UX-1), DISTINCT
    po całym archiwum - nie suma nocy teczek, bo noc przy dwóch obiektach to jedna noc przy
    teleskopie.

    Jeden SELECT na wątku GUI: zmierzone na żywej `pf4` (`?mode=ro`, 2026-10-09) ~50 ms przy
    14 337 lightach. Zwraca dict: objects, lights, hours, nights, last_night (`None` bez lightów)."""
    r = con.execute(
        "SELECT COUNT(DISTINCT f.object_id) AS objects, COUNT(*) AS lights, "
        "       COALESCE(SUM(h.exptime), 0) AS secs, "
        "       COUNT(DISTINCT date(h.date_obs, '-12 hours')) AS nights, "
        "       MAX(date(h.date_obs, '-12 hours')) AS last_night "
        "FROM frame f JOIN object o ON o.id = f.object_id "
        "LEFT JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind = 'light' AND f.retired_at IS NULL AND f.superseded_by IS NULL").fetchone()
    return {"objects": r["objects"], "lights": r["lights"], "hours": float(r["secs"]) / 3600.0,
            "nights": r["nights"], "last_night": r["last_night"]}


def last_hand_gesture(con):
    """Ostatni gest RĘKI z dziennika - zdanie Domu „Ostatnio (…): …", gdy w sesji nie ma recepty.

    GEST TO NIE JEDEN EVENT. Klinga zapisuje gest jednym `now`, więc wszystkie jego eventy mają
    wspólny `ts`; gest na wielu klatkach albo cofnięcie uwag mieszanego zaznaczenia emituje ich
    naraz kilka, czasem różnych czasowników. Gest = wszystkie eventy z tym samym `ts` i `actor`, co
    ostatni event ręki (`actor LIKE 'user%'` - klingi piszą `user:<uid>`, oś piksela kamery goły
    `user`). Ostatni po `id DESC`, nie po `ts`: `id` rośnie z zapisem, a tabela ma indeks wyłącznie
    na `target`, więc drugi SELECT przechodzi dziennik w całości (~60 ms na 164 tys. eventów żywej
    `pf4`, 2026-10-09).

    Zwraca `None` (dziennik bez gestów ręki) albo dict: ts, actor, verbs (`{verb: liczba}`,
    alfabetycznie), n (wszystkie eventy gestu)."""
    last = con.execute(
        "SELECT ts, actor FROM event WHERE actor LIKE 'user%' ORDER BY id DESC LIMIT 1").fetchone()
    if last is None:
        return None
    verbs = {r["verb"]: r["n"] for r in con.execute(
        "SELECT verb, COUNT(*) AS n FROM event WHERE ts = ? AND actor = ? "
        "GROUP BY verb ORDER BY verb", (last["ts"], last["actor"]))}
    return {"ts": last["ts"], "actor": last["actor"], "verbs": verbs, "n": sum(verbs.values())}

# --- TODO-DŁUG (z kolejki sesji, dieta 2026-08-10; pełne brzmienia: archiwum aa) ---
# TODO-DŁUG(P4-1): unresolved_reason to werdykt ZAMROŻONY - 11 stosów niosło no_object dobę po
#   nadaniu obiektów ręką. Kubełek liczyć ze STANU (obiekt jest => no_object nie ma prawa się
#   pokazać) albo gest zmieniający fakt sam proponuje przeliczenie (wzorzec taktu 3, b803b5d).
