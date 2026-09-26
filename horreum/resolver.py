"""Krok ZBIORCZY po skanie — resolver osi OBIEKT + filtr (PLAN §Etap 6, OSTATNI pierwszego przebiegu).

Domyka płaskie sortowanie o dwie interpretacje pochodne (jak grouper domknął teleskop/config):
czyta przez SELECT, rozwiązuje, a WSZYSTKIE zapisy idą przez `repo` (jedna klinga) — ten moduł nie
wykonuje DML. (Nazwa: `resolver` = orkiestracja; czyste funkcje wiedzy mieszkają w pakiecie
`resolve.*`, tak jak grouper↔`resolve.telescopes`.)

KIND-AWARENESS (firsthand Zdzinia): OBIEKT dotyczy WYŁĄCZNIE light/master_light — kalibracja
(flat/dark/bias/master_*) nie ma obiektu z definicji, więc jej `object_id=NULL` to POPRAWNY STAN, nie
delta (inaczej ~2333 FlatWizard-flatów = fałszywe „nierozwiązane"). Light nierozpoznany = delta: stan
(`object_id NULL`) jest deltą zapytywalną wprost; do tego JEDEN zbiorczy `object.review_summary`
(audyt bez szumu, jak backfill focratio). FILTR jest kind-AGNOSTYCZNY (flat też ma filtr) → backfill
zbiorczy `frame.filter_canon`; brak/pusty → NULL (W2, bez kanału review).
"""
import dataclasses
import json
from dataclasses import dataclass, field

from . import repo
from .grouper import NO_TELESCOPE_KINDS
from .resolve._coerce import _to_text
from .resolve._text import norm_alnum
from .resolve.catalog import catalog_canon
from .resolve.filters import normalize_filter
from .resolve.objects import (STICKY_OBJECT_SOURCES, WEAK_OBJECT_SOURCES, ObjectIdentity,
                              load_own_objects, resolve_object)
from .resolve.observatory import site_coords
from .resolve.paths import STACK_KIND, object_folder, object_from_path, filename_tokens
from .resolve.regions import resolve_region
from .resolve.solar import resolve_solar

# Klatki, które MAJĄ obiekt nieba — fakt przeniesiony do liścia `resolve.frames` (S2b), bo guard
# rodzaju musi go wziąć w `repo`, a stamtąd import `resolver` byłby cyklem. Re-eksport, żeby
# dotychczasowi wołający `resolver.LIGHT_KINDS` nie musieli wiedzieć o przeprowadzce.
from .resolve.frames import LIGHT_KINDS      # noqa: F401  (re-eksport — jeden właściciel faktu)


@dataclass
class ResolveSummary:
    """Zliczenia jednego przebiegu `run_resolver` — do firsthand-weryfikacji."""
    frames: int = 0                       # wszystkie frame'y z nagłówkiem
    light_frames: int = 0                 # light/master_light (kandydaci osi OBIEKT)
    objects_new: int = 0                  # nowe wiersze object (distinct kanon)
    objects_assigned: int = 0             # light'y z przypisanym object_id
    objects_by_alias: int = 0             # z tego: przypisane przez ZAPISANY ALIAS (#8, P4)
    objects_by_region: int = 0            # z tego: przypisane ze WSPÓŁRZĘDNYCH (kompleks, #5)
    objects_review: int = 0               # light'y obecne-ale-nierozpoznane (delta, per-frame)
    objects_user_cleared: int = 0         # klatki z NAGROBKIEM ręki (S2b) — przebieg ich NIE tyka
    objects_unresolved_distinct: int = 0  # distinct object_raw w delcie
    filters_set: int = 0                  # frame'y z niepustym filter_canon
    observatories_new: int = 0            # nowe stanowiska (seed z propose_observatory, created=True)
    observatories_assigned: int = 0       # klatki z przypisanym observatory_id
    gps_unparseable: int = 0              # klatki z GPS OBECNYM ale nieparsowalnym (→ review_summary)
    own_aliases_seeded: int = 0           # nowe równoważności ze słownika obiektów własnych (S1)
    own_aliases_retired: int = 0          # równoważności zdjęte po edycji słownika (migracja)
    own_frames_unassigned: int = 0        # klatki odpięte razem z wycofaną równoważnością
    own_alias_conflicts: int = 0          # nazwy zajęte przez INNY obiekt (pominięte, → review)
    # SZCZEBEL ŚCIEŻKI (S2, D-OW-2/B) — PROPOZYCJE, nie zapisy. Przebieg nie rusza ani jednego
    # wiersza osi obiektu z tego tytułu; te dwie liczby są jedynym śladem szczebla w raporcie.
    path_proposed_frames: int = 0         # klatki, którym ścieżka proponuje kanon (do potwierdzenia)
    path_proposed_names: int = 0          # …zgrupowane po NAZWIE (jednostka przeglądu człowieka)


def sync_own_aliases(con, now, s=None):
    """Zsynchronizuj `object_alias` ze słownikiem obiektów własnych — DIFF-FIRST (D-OW-4/A′).

    Nazwy potoczne z assetu (`n`) stają się równoważnościami, żeby szukajka i „Napraw nagłówek…"
    znały „Large Magellanic Cloud", nie tylko kanon `LMC`. Zasiew jest przywiązany do TOŻSAMOŚCI,
    nie do szczebla: liczy się to, że obiekt o tym kanonie ISTNIEJE — nieważne, którędy jego klatki
    kanon dostały.

    ZAKRES = OBIEKTY ISTNIEJĄCE, nigdy wpisy assetu (`object_alias.object_id` to `NOT NULL
    REFERENCES object(id)` przy `foreign_keys=ON`): dopóki żadna klatka nie ma `LMC`, nie ma czego
    aliasować i nie ma to skutku — asset opisuje klasę, baza opisuje archiwum.

    DIFF-FIRST, nie kasuj-i-wstaw: liczymy zestaw docelowy, porównujemy z istniejącym i przy zerowej
    różnicy NIE wykonujemy DML ani nie emitujemy (wzorzec `repo.backfill_filter_canon`). Naiwne
    DELETE+INSERT emitowałoby przy każdym przebiegu i churnowało `id`.

    KOLIZJA MA TRZY GAŁĘZIE, NIE WYJĄTEK: `alias_norm` jest UNIQUE i może już należeć do TEGO
    obiektu (zostaw — nic do zrobienia) albo do INNEGO (pomiń + jeden ZBIORCZY event przeglądu).
    Sprawdzamy to SELECT-em PRZED `repo.add_object_alias`, bo ta funkcja zwraca istniejący wiersz
    BEZ porównania `object_id` — „jest idempotentna, więc wystarczy ją zawołać" nigdy nie odpaliłoby
    gałęzi kolizji i przegrany ginąłby cicho. Wyjątku tu nie rzucamy: ta funkcja biegnie w passie
    masowym Dostawy, a `gui/pipeline` zamieniłby go w `failed` i urwał `calibrate`/`lineage`/`delta`
    z powodu danych, które user miał prawo stworzyć."""
    s = s if s is not None else ResolveSummary()

    obiekty = {r["canon"]: r["id"] for r in con.execute("SELECT id, canon FROM object").fetchall()}
    chciane = {}                                   # alias_norm -> object_id (tylko istniejące obiekty)
    for rec in load_own_objects():
        oid = obiekty.get(_to_text(rec.get("c")))
        if oid is None:
            continue
        for name in (rec.get("c"), *(rec.get("n") or ())):
            key = norm_alnum(name or "")
            if key:
                chciane[key] = oid

    istniejace = {r["key"]: r["oid"] for r in con.execute(
        "SELECT alias_norm AS key, object_id AS oid FROM object_alias").fetchall()}
    zasiane = {r["key"]: r["oid"] for r in con.execute(
        "SELECT alias_norm AS key, object_id AS oid FROM object_alias "
        "WHERE source = 'curated'").fetchall()}

    kolizje = []
    for key, oid in sorted(chciane.items()):
        czyj = istniejace.get(key)
        if czyj == oid:
            continue                               # już jest (nasz albo cudzym szczeblem) — zostaw
        if czyj is not None:
            kolizje.append([key, czyj, oid])       # nazwa zajęta przez INNY obiekt — pomiń
            continue
        _, created = repo.add_object_alias(con, alias_norm=key, object_id=oid,
                                           source="curated", now=now)
        s.own_aliases_seeded += created

    # WYCOFANIE: równoważności zasiane wcześniej, których asset już nie zna. Grupujemy po obiekcie,
    # bo klinga odpina klatki tego obiektu jednym przebiegiem.
    zbedne = {}
    for key, oid in sorted(zasiane.items()):
        if chciane.get(key) != oid:
            zbedne.setdefault(oid, []).append(key)
    for oid, keys in zbedne.items():
        wycofane, odpiete = repo.retire_alias_and_unassign(
            con, object_id=oid, alias_norms=keys, now=now)
        s.own_aliases_retired += wycofane
        s.own_frames_unassigned += odpiete

    if kolizje:
        s.own_alias_conflicts += len(kolizje)
        repo.flag_object_alias_conflicts(con, kolizje, now)
    return s


# ═══════════════════════════════════════════ DRABINA NAZWY — JEDEN WŁAŚCICIEL (S2, D-OW-2 pkt 5)

def resolve_name(lookup, text, *, from_path=False):
    """Drabina zależna od NAZWY → `(ObjectIdentity | None, object_id | None)`. Read-only.

    JEDEN właściciel kolejności szczebli dla WSZYSTKICH trzech miejsc wołania: passu masowego
    (`run_resolver`), walidacji dialogu „Napraw nagłówek…" (`name_resolves`) i szczebla ŚCIEŻKI.
    Dopóki każde z nich miało własną kopię, ekran i baza odpowiadały różnie na to samo pytanie —
    dialog milczał o `LMC` i `_SOLAR\\Moon`, choć przebieg je nazywał.

    Szczeble, w kolejności przebiegu: `resolve_solar` → `resolve_object` (katalog/xref → `_COMMON`
    → słownik obiektów własnych) → **ALIAS** (`object_alias` — jawna wiedza usera). REGION świadomie
    POZA drabiną: rozpoznaje ze WSPÓŁRZĘDNYCH, więc od tekstu nie zależy i wołający dokłada go sam.

    `lookup` = CALLABLE `alias_norm → wiersz|None` z polami `object_id`/`canon`/`catalog`/`kind`.
    Pass masowy podaje `.get` snapshotu (zero SELECT-ów w pętli), walidacja dialogu — domknięcie na
    jednym SELECT-cie po UNIQUE (zero budowania snapshotu przy każdym naciśnięciu klawisza).
    Wiersz MUSI nieść kanon, nie samo `object_id`: bez niego nie ma z czego zbudować tożsamości
    dla trafienia aliasu, a `ObjectIdentity` id nie ma.

    DRUGI CZŁON KROTKI JEST NIEPUSTY WYŁĄCZNIE PRZY TRAFIENIU ALIASU — mówi „ten obiekt JUŻ
    ISTNIEJE, nie rób upsertu". Przy każdym innym szczeblu wołający sam zakłada/odnajduje obiekt.

    `from_path=True` (JEDEN przełącznik trybu ścieżki, D-OW-2 pkt 5/5a) implikuje DWIE rzeczy naraz:
      * `split=False` w gramatyce katalogowej — folder SPRZĘTU nie udaje oznaczenia;
      * `alias_norm=None` w wyniku — segment ścieżki NIE trafi żadnego przyszłego `object_raw`,
        więc równoważności z niego nie robimy. Bez tego naiwna kompozycja szczebla wsypałaby ~35
        aliasów, których re-derywacja słownika (zakres `curated`) nigdy by nie usunęła, a żadna
        bramka by się nie zaczerwieniła: alias i event idą parą, więc `§5.9` się domyka.
        Zakaz dotyczy aliasu Z SEGMENTU — nazwy potoczne wpisu słownika zasiewa `sync_own_aliases`,
        także gdy kanon przyszedł ścieżką."""
    ident = resolve_solar(text) or resolve_object(text, split=not from_path)
    key = ident.alias_norm if ident is not None else norm_alnum(text)
    row = lookup(key) if key else None      # pusty klucz łapałby KAŻDĄ niealfanumeryczną nazwę

    # SŁOWNIK USTĘPUJE RĘCE (R-S1-2): szczebel słownika stoi WYŻEJ niż alias, więc dla nazwy, którą
    # user przypisał wcześniej pod własnym kanonem, przejąłby jego klatki i ROZSZCZEPIŁ grupę
    # (`object_source='user'` chroni tylko klatkę dotkniętą ręką, rodzeństwo szłoby pod nowy kanon).
    # Ustępujemy WYŁĄCZNIE CUDZEMU obiektowi — porównanie po KANONIE, bo po pierwszym przebiegu
    # słownik zasiewa własny alias i warunek „alias istnieje" przemalowywałby `curated` → `alias`
    # przy każdym kolejnym przebiegu, wywracając idempotencję na własnej obronie.
    # Gramatyki katalogowej to NIE dotyczy: nazwa katalogowa jest faktem o niebie, nie zdaniem
    # człowieka o archiwum, więc tam szczebel stoi ponad aliasem i ta precedencja jest zamierzona.
    if ident is not None and ident.source == "curated" and row is not None \
            and row["canon"] != ident.canon:
        ident = None

    oid = None
    if ident is None:
        if row is None:
            return None, None
        # Trafienie aliasu: obiekt i równoważność ISTNIEJĄ z definicji — wołający pomija upsert
        # i zapis aliasu. `source='alias'` (D-P4-6): klatka z aliasu zostaje re-derywowalna,
        # `user` rezerwuje się dla jawnego gestu człowieka.
        ident, oid = ObjectIdentity(canon=row["canon"], catalog=row["catalog"], kind=row["kind"],
                                    source="alias", alias_norm=key), row["object_id"]

    # Zerowanie klucza obejmuje OBIE gałęzie — trafienie aliasu też wraca ze ścieżki bez niego.
    # Wyjęcie go za `if` było kontraktem połowicznym: druga droga wychodziła z pełnym `alias_norm`,
    # a pin bramki §4/4(c) podawał lookup, który NIGDY nie trafia, więc nie miał jak tego złapać.
    if from_path and ident is not None:
        ident = dataclasses.replace(ident, alias_norm=None)
    return ident, oid


def alias_lookup(con):
    """Domknięcie `alias_norm → wiersz|None` na JEDNYM SELECT-cie po UNIQUE — `lookup` drabiny dla
    wołających spoza passu masowego (walidacja dialogu, szczebel ścieżki liczony na żądanie).

    `JOIN object` jest KONIECZNY, nie ozdobny: bez kanonu drabina nie ma z czego zbudować tożsamości
    dla trafienia aliasu i musiałaby oddać samo `object_id`, czyli mniej, niż obiecuje kontrakt."""
    def _lookup(key):
        return con.execute(
            "SELECT a.object_id AS object_id, o.canon AS canon, o.catalog AS catalog, "
            "       o.kind AS kind "
            "FROM object_alias a JOIN object o ON o.id = a.object_id "
            "WHERE a.alias_norm = ?", (key,)).fetchone()
    return _lookup


def alias_snapshot(con):
    """Snapshot WSZYSTKICH równoważności raz na przebieg: `alias_norm → wiersz` (jak wyżej).

    Snapshot ze STARTU przebiegu jest bezpieczny (R#12): alias zapisany W TYM przebiegu dotyczy
    nazwy, którą wcześniejszy szczebel trafił deterministycznie."""
    return {r["key"]: r for r in con.execute(
        "SELECT a.alias_norm AS key, a.object_id AS object_id, o.canon AS canon, "
        "       o.catalog AS catalog, o.kind AS kind "
        "FROM object_alias a JOIN object o ON o.id = a.object_id").fetchall()}


# ═══════════════════════════════════════════ SZCZEBEL ŚCIEŻKI — PROPOZYCJA, NIE ZAPIS (D-OW-2/B)

@dataclass(frozen=True)
class PathProposal:
    """Jedna pozycja do potwierdzenia: KANON + klatki, które go dostaną. Jednostką przeglądu jest
    NAZWA, nie klatka (707 klatek ⇒ ≈35 pozycji) — inaczej „Zatwierdź wszystko" byłoby listą,
    której nikt nie przeczyta."""
    canon: str
    catalog: object
    kind: str
    folder: str          # folder OBIEKTU pierwszej klatki grupy — skąd wzięła się nazwa
    frame_ids: tuple
    is_new: bool         # kanonu NIE MA jeszcze w bazie (to te pozycje mają przejść przez oko)
    # Populacja pozycji (E3-1): False = RAW-owe lighty (podzbiór kubełka RAW), True = gotowe stosy
    # z drzewa `STACKS` (podzbiór kubełka stosów). Osobne pozycje, nie wspólna grupa po kanonie:
    # kolejka pokazuje każdą populację POD jej kubełkiem („…z tego ze ścieżki"), więc liczba spod
    # kubełka RAW nie może zawierać stosów, a folder przy pozycji ma być świadkiem TEJ populacji.
    stack_tree: bool = False

    @property
    def n_frames(self):
        return len(self.frame_ids)


def path_proposals(con):
    """Kandydaci szczebla ŚCIEŻKI, POGRUPOWANI PO KANONIE — read-only, ZERO zapisu (D-OW-2/B).

    JEDEN właściciel derywacji dla dwóch wołających: przebiegu (który tylko LICZY propozycje
    w podsumowaniu) i powierzchni potwierdzania (która pokazuje je do zatwierdzenia). Dwie kopie
    tego samego rozumowania dałyby licznik mówiący co innego niż lista, którą otwiera.

    ZAKRES — trzy warunki naraz, każdy z ceną nazwaną:
      * `filetype IN NO_OBJECT_CARD_FILETYPES` (nie literał `'raw'`) — szczebel odzywa się WYŁĄCZNIE
        tam, gdzie format NIE MA JAK zeznać o obiekcie. Szerszy zakres opróżniałby kotwicę nawrotu
        `nameless_lights` NAPRAWĄ NAZWY zamiast naprawą PLIKU (P-D naprawiła 25 plików na `R:`);
      * `object_raw IS NULL` — równość z kubełkiem `nameless_raw_lights` ma być STRUKTURALNA,
        a nie oparta na obietnicy semantycznej stałej;
      * `object_id IS NULL` (STICKY) — klatka, która obiekt JUŻ ma, nie zostanie przemalowana po
        przenosinach plików (konsolidacja stosów przeniesie ich setki). Cena: kanon może się
        zdezaktualizować, a wykrycie tego rozjazdu jest POZA tą paczką;
      * `object_source IS NULL` (S2b) — NAGROBEK RĘKI wyklucza propozycję. Przy `object_id IS NULL`
        niepuste źródło znaczy dokładnie jedno: `user_cleared`. Bez tego członu klatka cofnięta
        wracała do kubełka „ze ścieżki — do potwierdzenia" i JEDNO „Zatwierdź wszystko" cofało
        cofnięcie — przy `run_resolver` poprawnie ją omijającym, więc bramka nagrobka świeciła
        zielono. Zaczerwieniło to dopiero pytanie o PROPOZYCJE, nie o zapis (§4/14b).

    KOPIA: osobny SELECT z `MIN(id) … present = 1` (wzorzec `resolve_observatory`) — NIGDY
    `LEFT JOIN location` w pętli `run_resolver`. Brak obecnej kopii ⇒ ścieżki nie ma ⇒ szczebel
    MILCZY (`path` NULL wypada na `object_from_path`).

    Klatka-szkielet (bez wiersza `header`) nie odezwie się nigdy — `JOIN header` jak w kubełku,
    którego ta populacja jest podzbiorem. Dziś koszt 0 (763/763 RAW ma `header`); nazwane, bo to ta
    sama klasa cichej luki, co marker korzenia.

    DRUGA POPULACJA: GOTOWE STOSY Z DRZEWA `STACKS` (E3-1). Warunek dowodowy jest INNY niż u RAW-a
    i to jest sedno: XISF stosu MOŻE nieść `OBJECT`, więc o propozycji nie rozstrzyga format, tylko
    FAKT milczenia nagłówka. Człony: `kind='master_light'`, `object_raw IS NULL` (nagłówek NIE
    zeznaje; zeznanie nierozpoznane idzie do `object_review`, nie tutaj), `object_id IS NULL`
    (STICKY jak wyżej, także obiekt z REGIONU, który stoi w drabinie przed ścieżką),
    `object_source IS NULL` (nagrobek ręki wyklucza propozycję, jak wyżej) oraz kotwica `STACKS`
    w ścieżce OBECNEJ kopii (`paths.object_from_path(…, kind=STACK_KIND)` milczy poza tym drzewem:
    układ WBPP `…\\master\\…` nazwy obiektu nie niesie w żadnym stałym segmencie). Zmierzone na 193
    stosach: segment po `STACKS` zgadza się z kanonem osi 187 razy, rozjeżdża 0 razy.
    RÓŻNICA WOBEC LIGHTÓW FITS JEST ŚWIADOMA: tam szczebel milczy, żeby kotwica `nameless_lights`
    pilnowała naprawy PLIKU. Stos dostaje propozycję, bo drzewo `STACKS` jest jedną regułą
    pozycyjną z pomiarem bez rozjazdu, a nie dowolnym folderem archiwum. Cena nazwana: gest
    potwierdzenia nazywa stos w BAZIE, a plik dalej milczy - droga karty („Napraw nagłówek…")
    zostaje otwarta, a karta wpisana później WYGRYWA, bo `path` nie jest STICKY i przebieg
    rozstrzyga nagłówkiem przed ścieżką.

    ŚWIADKIEM STOSU SĄ WSZYSTKIE OBECNE KOPIE, NIE `MIN(id)`. Stos bywa w archiwum dwa razy (128
    gotowych obrazów dostało drugi adres przy wjeździe stosów, D-V-9), a kopia o najniższym id to
    kolejność WJAZDU, nie prawda o obiekcie - dwie kopie pod `STACKS\\vdB30` i `STACKS\\NGC7000`
    dawałyby propozycję zależną od tego, która wjechała pierwsza. Reguła:
      * głos oddaje kopia, której segment po `STACKS` ROZWIĄZUJE się drabiną nazwy;
      * kopie o RÓŻNYCH kanonach = sprzeczność świadków, szczebel MILCZY (decyzja zostaje u
        człowieka - ręka albo karta w pliku);
      * kopia bez kotwicy `STACKS` (układ WBPP, `_WBPP`, dowolny folder roboczy) głosu NIE oddaje
        i nie blokuje: poza drzewem stosów żaden stały segment nie niesie nazwy obiektu, więc taka
        kopia nie zeznaje niczego, czemu segment po `STACKS` mógłby przeczyć. Tak samo kopia pod
        `STACKS` z nazwą, której drabina nie zna - milczy, jak jedyna kopia z takim folderem;
      * folderem pozycji jest folder obiektu pierwszej głosującej kopii (`ORDER BY f.id, l.id`).
    Droga RAW zostaje przy `MIN(id)` wśród obecnych - lighty z lustrzanki nie mają drugich kopii
    w zmierzonym archiwum, a zmiana jej reguły nie należy do tej poprawki."""
    lookup = alias_snapshot(con).get
    kanony = {r["canon"] for r in con.execute("SELECT canon FROM object").fetchall()}
    rows = con.execute(
        "SELECT f.id AS fid, l.path AS path FROM frame f JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN location l ON l.id = (SELECT MIN(id) FROM location "
        "                                WHERE frame_id = f.id AND present = 1) "
        "WHERE f.kind = 'light' AND f.object_id IS NULL "
        "  AND f.superseded_by IS NULL "
        "  AND f.retired_at IS NULL "
        "  AND h.object_raw IS NULL "
        "  AND f.object_source IS NULL "
        "  AND f.filetype IN (SELECT value FROM json_each(?)) "
        "ORDER BY f.id",
        (json.dumps(list(NO_OBJECT_CARD_FILETYPES)),)).fetchall()
    kopie_stosow = con.execute(
        "SELECT f.id AS fid, l.path AS path FROM frame f JOIN header h ON h.frame_id = f.id "
        "JOIN location l ON l.frame_id = f.id AND l.present = 1 "
        "WHERE f.kind = 'master_light' AND f.object_id IS NULL "
        "  AND f.superseded_by IS NULL "
        "  AND f.retired_at IS NULL "
        "  AND h.object_raw IS NULL "
        "  AND f.object_source IS NULL "
        "ORDER BY f.id, l.id").fetchall()

    grupy = {}                       # (drzewo stosów?, kanon) -> [ident, folder, [frame_id, …]]

    def _dopisz(drzewo, fid, ident, folder):
        wpis = grupy.get((drzewo, ident.canon))
        if wpis is None:            # folder liczymy RAZ na grupę, nie raz na klatkę (763 wywołania
            wpis = grupy[(drzewo, ident.canon)] = [ident, folder(), []]          # na odświeżenie)
        wpis[2].append(fid)

    for r in rows:
        seg = object_from_path(r["path"])
        if not seg:
            continue
        ident, _ = resolve_name(lookup, seg, from_path=True)
        if ident is not None:
            _dopisz(False, r["fid"], ident, lambda p=r["path"]: object_folder(p))

    glosy = {}                       # frame_id -> {kanon: (ident, ścieżka pierwszej kopii)}
    for r in kopie_stosow:
        seg = object_from_path(r["path"], kind=STACK_KIND)
        ident = resolve_name(lookup, seg, from_path=True)[0] if seg else None
        glos = glosy.setdefault(r["fid"], {})
        if ident is not None and ident.canon not in glos:
            glos[ident.canon] = (ident, r["path"])
    for fid, glos in glosy.items():
        if len(glos) != 1:          # zero głosów = milczenie; dwa kanony = sprzeczność = milczenie
            continue
        ident, sciezka = next(iter(glos.values()))
        _dopisz(True, fid, ident, lambda p=sciezka: object_folder(p, kind=STACK_KIND))
    # Porządek po NAZWIE, populacja drugim kluczem: ta sama nazwa z obu drzew stoi obok siebie.
    return tuple(
        PathProposal(canon=canon, catalog=ident.catalog, kind=ident.kind, folder=folder,
                     frame_ids=tuple(fids), is_new=canon not in kanony, stack_tree=drzewo)
        for (drzewo, canon), (ident, folder, fids)
        in sorted(grupy.items(), key=lambda kv: (kv[0][1], kv[0][0])))


def path_proposal(con, path, kind="light"):
    """Propozycja kanonu ze ścieżki dla dialogu „Napraw nagłówek…" (P-D) — albo None.

    `kind` wybiera DRZEWO świadka folderu (`paths.object_from_path`): light czyta pozycję po
    markerze rodzaju, `master_light` segment po `STACKS`. Drugi świadek (człon nazwy pliku) i reguła
    zgodności są dla obu drzew TE SAME - stos nazwany `vdB30_…xisf` w `STACKS\\vdB30\\…` dostaje
    propozycję dokładnie tak, jak light. Domyślny light zostawia dotychczasowych wołających
    bez zmian.

    TA SAMA DRABINA co szczebel przebiegu (SPOT — do S2 repo miało DWIE reguły ścieżki i ekran
    odpowiadał inaczej niż baza), ale reguła świadka jest OSTRZEJSZA i to jest różnica ZAMIERZONA:
    tu zapis idzie do PLIKU i jest nieodwracalny bez kopii bajtowej, więc wymagamy ZGODNEGO
    zeznania DWÓCH świadków (folder obiektu ∧ człon nazwy pliku). Szczebel przebiegu tylko
    PROPONUJE do bazy, więc stać go na jednego świadka — dwaj zgodni łapią 31 klatek z 763.

    ZWRACA FORMĘ SPRZED `xref` — to druga zamierzona różnica wobec szczebla (§4 wiersz 16 wypisuje
    obie jawnie): do PLIKU idzie konwencja USERA (folder `M82` → karta `M82`), a nie kanon bazy
    (`NGC3034`). Drabina odpowiada tu na pytanie „czy ta nazwa się rozwiąże", a nie „jak ją zapisać"
    — inaczej naprawa nagłówka przepisywałaby użytkownikowi jego własne archiwum (D-PD-9)."""
    seg = object_from_path(path, kind=kind)
    if not seg:
        return None
    lookup = alias_lookup(con)
    ident, _ = resolve_name(lookup, seg, from_path=True)
    if ident is None:
        return None
    for token in filename_tokens(path):
        drugi, _ = resolve_name(lookup, token, from_path=True)
        if drugi is not None and drugi.canon == ident.canon:
            return catalog_canon(seg, split=False) or seg.strip()
    return None


def run_resolver(con, now):
    """Po skanie: dla każdego frame'a z nagłówkiem rozwiąż OBIEKT (tylko light/master_light) i FILTR
    (wszystkie). Obiekt rozpoznany → `upsert_object`+`assign_object` (+`add_object_alias`, gdy
    rozpoznanie pochodzi z NAZWY — region rozpoznaje ze współrzędnych i aliasu nie ma). Drabina
    szczebli: `resolve_solar`/`resolve_object` (header-primary ŚWIĘTE) → **ALIAS** (`object_alias`
    zapisany wcześniej — #8, P4; jawna wiedza o nazwie, `object_source='alias'`) → `resolve_region`
    (inferencja z geometrii, ostatni). **`object_source='user'` pomija CAŁĄ drabinę** (P4): decyzja
    człowieka nie jest re-derywowana ani nadpisywana przez żaden szczebel automatyczny. Light
    nierozpoznany → delta (jeden zbiorczy `object.review_summary`, liczony ze STANU
    `object_id IS NULL` — D5); kalibracja → pomijana (poprawny NULL). Filtr → backfill zbiorczy
    `filter_canon`. Zwraca `ResolveSummary`. Idempotentny.

    SŁOWNIK OBIEKTÓW WŁASNYCH siedzi WEWNĄTRZ `resolve_object` (ostatni jego szczebel), więc stoi
    przed aliasem i regionem — jest jawną wiedzą o NAZWIE, jak `_COMMON`, a nie inferencją. Dzięki
    temu widzi go też `name_resolves`, czyli walidacja dialogu „Napraw nagłówek…". Zasiew nazw
    potocznych tego słownika domyka przebieg (`sync_own_aliases`)."""
    s = ResolveSummary()
    rows = con.execute(
        "SELECT f.id AS fid, f.kind AS kind, f.object_id AS oid, f.object_source AS osrc, "
        "h.object_raw AS obj, h.filter_raw AS filt, h.ra_deg AS ra, h.dec_deg AS dec "
        "FROM frame f JOIN header h ON h.frame_id = f.id").fetchall()
    s.frames = len(rows)

    # Szczebel ALIASU (P4, D-P4-1): preload WSZYSTKICH aliasów raz na przebieg — drabina dostaje go
    # jako `lookup`, więc w pętli nie ma ANI JEDNEGO SELECT-a.
    lookup = alias_snapshot(con).get

    unresolved = {}        # object_raw -> liczba (tylko light/master_light, obecny-nierozpoznany)
    filter_items = []      # (frame_id, filter_canon) do backfillu zbiorczego
    for r in rows:
        # --- oś OBIEKT: kind-aware (kalibracja nie ma obiektu z definicji) ---
        if r["kind"] in LIGHT_KINDS:
            s.light_frames += 1
            if r["osrc"] in STICKY_OBJECT_SOURCES:
                # PRECEDENCJA ZEZNANIA CZŁOWIEKA na WSZYSTKIE szczeble (P4 + S2b): ręczne
                # przypisanie pomija drabinę — frame zachowuje obiekt usera, zero re-derywacji,
                # zero nadpisywania. (Wcześniej guard obejmował tylko region; uogólniony na
                # solar/deep-sky/alias/region.)
                #
                # NAGROBEK `user_cleared` idzie TĄ SAMĄ gałęzią i to jest sedno odwracalności:
                # klatka cofnięta ma `object_id IS NULL`, więc bez tego guardu najbliższy przebieg
                # przypisałby ją PONOWNIE tym samym szczeblem, który człowiek odrzucił. Nie liczymy
                # jej też do `unresolved` — to nie jest nierozpoznane zeznanie, tylko werdykt.
                s.objects_user_cleared += r["osrc"] == "user_cleared"
            else:
                # CAŁA drabina zależna od nazwy (solar → katalog/słownik → alias) siedzi w JEDNYM
                # właścicielu: `resolve_name`. Drugi człon krotki niepusty ⇒ trafienie ALIASU.
                ident, alias_oid = resolve_name(lookup, r["obj"])
                # REGION = OSTATNI szczebel (#5, P3): dopiero gdy zeznanie nagłówka i alias nic nie
                # dały — 547 klatek `NGC6992` leży WEWNĄTRZ promienia Veil i chroni je kolejność.
                # …i NIE nad potwierdzeniem ze ŚCIEŻKI (`WEAK_OBJECT_SOURCES`): człowiek zatwierdził
                # nazwę z folderu, a region jest najsłabszym szczeblem automatu - stos pod
                # `STACKS\\NGC6992` z RA/DEC w promieniu Veil zostaje `NGC6992`. Zakres = sam
                # region: nagłówek, który zeznaje rozpoznawalną nazwę, wygrywa dalej (header-primary).
                if ident is None and alias_oid is None and r["osrc"] not in WEAK_OBJECT_SOURCES:
                    ident = resolve_region(r["ra"], r["dec"])
                if alias_oid is not None:
                    # Trafienie aliasu: obiekt i alias ISTNIEJĄ z definicji — BEZ upsert_object i
                    # BEZ zapisu aliasu; `object_source='alias'` (D-P4-6: klatka z aliasu zostaje
                    # re-derywowalna, 'user' rezerwuje się dla jawnego przypisania).
                    if repo.assign_object(con, frame_id=r["fid"], object_id=alias_oid,
                                          object_source="alias", now=now):
                        s.objects_assigned += 1
                        s.objects_by_alias += 1
                elif ident is not None:
                    oid, created = repo.upsert_object(
                        con, canon=ident.canon, catalog=ident.catalog, kind=ident.kind, now=now)
                    s.objects_new += created
                    if ident.alias_norm:    # region NIE aliasuje — rozpoznanie nie pochodzi z nazwy
                        repo.add_object_alias(con, alias_norm=ident.alias_norm, object_id=oid,
                                              source=ident.source, now=now)
                    if repo.assign_object(con, frame_id=r["fid"], object_id=oid,
                                          object_source=ident.source, now=now):
                        s.objects_assigned += 1
                        s.objects_by_region += ident.source == "region"
                elif r["oid"] is None:
                    # D5: delta ze STANU (`object_id IS NULL`), nie z rederywacji — frame przypisany
                    # (ręcznie lub wcześniej), którego nagłówek dziś się nie rozwiązuje, NIE wraca
                    # do review_summary (zgodnie z delta_report/review_queue, oba ze stanu).
                    raw = _to_text(r["obj"])
                    if raw is not None:              # obecny ale nierozpoznany → delta
                        unresolved[raw] = unresolved.get(raw, 0) + 1
                        s.objects_review += 1
            # obj brak (None) na lightcie → object_id NULL bez review (brak zeznania do rozwiązania)

        # --- oś FILTR: kind-agnostyczna (flat też ma filtr); brak/pusty → NULL (W2) ---
        fc = normalize_filter(r["filt"])
        if fc is not None:
            filter_items.append((r["fid"], fc))

    s.filters_set = len(filter_items)
    s.objects_unresolved_distinct = len(unresolved)
    repo.backfill_filter_canon(con, filter_items, now=now)        # no-op gdy pusto
    repo.flag_object_review_summary(
        con, sorted(unresolved.items(), key=lambda kv: (-kv[1], kv[0])), now=now)  # no-op gdy pusto

    # SZCZEBEL ŚCIEŻKI — POLICZONY, NIE ZAPISANY (D-OW-2/B). Przebieg mówi, ile klatek CZEKA na
    # gest człowieka; sam nie pisze do osi obiektu ani jednego wiersza. Liczony PO pętli i osobnym
    # SELECT-em, bo pyta o ŚCIEŻKĘ (kopia obecna), której pętla `frame JOIN header` nie zna.
    propozycje = path_proposals(con)
    s.path_proposed_names = len(propozycje)
    s.path_proposed_frames = sum(p.n_frames for p in propozycje)

    # ZASIEW NAZW POTOCZNYCH — PO pętli, i to jest jedyna kolejność, która działa na świeżej bazie:
    # zasiew wymaga ISTNIEJĄCEGO obiektu, a `LMC` powstaje dopiero, gdy szczebel słownika przypisze
    # pierwszą klatkę. Idempotentny, więc drugi przebieg jest ciszą.
    sync_own_aliases(con, now, s)

    # oś OBSERWATORIUM foldnięta tu (SPOT — jeden wjazd; callerzy bez zmian). GPS z `cards`, nie z pętli
    # `header` powyżej (osobny SELECT — SITELAT/SITELONG nie są polami gorącymi `header`).
    s.observatories_new, s.observatories_assigned, s.gps_unparseable = resolve_observatory(con, now)
    return s


def resolve_observatory(con, now):
    """Oś OBSERWATORIUM (PLAN_os_obserwatorium §2b): dla każdej klatki z GPS w `cards` (SITELAT/SITELONG,
    `value_raw` — string dla obu formatów) wyłoń stanowisko przez `repo.propose_observatory` (kotwica
    GEOMETRYCZNA, member-id) i przypisz. Brak GPS (oba raw None) → `observatory_id` NULL cicho (świadomy
    brak — kalibracja i klatki sprzed montażu GPS; XISF-y już tu NIE należą: od P6a/P6b mają karty,
    więc 202 z nich wchodzą na oś). GPS OBECNY-ale-nieparsowalny → NULL + zliczenie do JEDNEGO `observatory.review_
    summary`. Iteracja `ORDER BY f.id` = pierwszy przebieg powtarzalny (§5 D4). Zwraca (new, assigned,
    gps_unparseable). Idempotentny: re-run zwraca te same id (anchor stabilny), zero nowych eventów."""
    rows = con.execute(
        "SELECT f.id AS fid, "
        "  (SELECT value_raw FROM cards WHERE frame_id = f.id AND keyword = 'SITELAT' "
        "   ORDER BY idx LIMIT 1) AS lat_raw, "
        "  (SELECT value_raw FROM cards WHERE frame_id = f.id AND keyword = 'SITELONG' "
        "   ORDER BY idx LIMIT 1) AS lon_raw "
        "FROM frame f ORDER BY f.id").fetchall()
    new = assigned = 0
    unparseable = {}          # (lat_raw, lon_raw) -> liczba (GPS obecny ale nieparsowalny)
    for r in rows:
        pt = site_coords(r["lat_raw"], r["lon_raw"])
        if pt is None:
            if r["lat_raw"] or r["lon_raw"]:            # raw OBECNE ale śmieciowe → delta (review)
                key = (r["lat_raw"], r["lon_raw"])
                unparseable[key] = unparseable.get(key, 0) + 1
            continue                                    # oba raw None → observatory_id NULL cicho
        obs_id, created = repo.propose_observatory(con, lat=pt[0], lon=pt[1], now=now)
        new += created
        if repo.assign_observatory(con, frame_id=r["fid"], observatory_id=obs_id, now=now):
            assigned += 1
    # klucz sortu = str(para) — pary raw mogą zawierać None (nieporównywalne z str inaczej), det.
    repo.flag_observatory_review_summary(
        con, sorted(unparseable.items(), key=lambda kv: (-kv[1], str(kv[0]))), now=now)  # no-op gdy pusto
    return new, assigned, sum(unparseable.values())


@dataclass
class ReviewState:
    """Kolejka przeglądu wyprowadzona ze STANU tabel — NIE ze zliczania eventów (#12).

    `flag_config_review` i pokrewne emitują BEZWARUNKOWO przy każdym przebiegu (grouper iteruje
    WSZYSTKIE klatki z nagłówkiem), więc `count(event)` mnożył licznik przez liczbę dostaw: 7 klatek
    czekających na decyzję pokazywało się jako 35 po pięciu przebiegach. Stan jest idempotentny —
    ta sama derywacja, co kolejka osi obiektu w `gui.queries.review_queue`.

    Kubełki NIE są rozłączne: klatka bez kamery nie da się złożyć w config, więc liczy się w
    `no_camera` I `no_config`. `total` to DISTINCT klatek — NIGDY suma pól.

    `unreadable` (#13) to fakt o KOPII (location.unreadable_since), zliczany PO KLATKACH (DISTINCT
    frame z ≥1 taką kopią — spójnie z resztą liczników, które są per-klatka). Kubełek zachodzi z
    innymi jak dotychczasowe (kopia nieczytelna może być frame'em-szkieletem = też `headerless`)."""
    no_config: int = 0        # config_id NULL mimo zeznania, POZA kalibracją bez osi (kind-scoping)
    headerless: int = 0       # brak wiersza `header` — plik nieczytelny przy skanie (frame-szkielet)
    no_camera: int = 0        # camera_id NULL mimo zeznania (brak INSTRUME/XPIXSZ)
    kind_unknown: int = 0     # zeznanie JEST, rodzaju nie dało się zmapować
    unreadable: int = 0       # ≥1 kopia z unreadable_since NOT NULL (kopia stała się nieczytelna; #13)
    total: int = 0            # DISTINCT klatek w KTÓRYMKOLWIEK kubełku (nie suma — kubełki zachodzą)


def review_state(con):
    """Policz kolejkę przeglądu ze STANU (read-only, zero zapisu). Po co i dlaczego DISTINCT — zob.
    `ReviewState`.

    `kind_unknown` idzie po `EXISTS(header)`, NIE po karcie IMAGETYP: kolejka przeglądu pyta o ZEZNANIE
    (jeden wiersz na klatkę), nie o jego lustro. Do P6a `cards` były w dodatku FITS-only, więc predykat
    na nich był wprost ŚLEPY na 326 XISF-ów — dziś karty ma już każdy czytelny format, ale reguła
    zostaje: lustro może być niekompletne (plik nieparsowalny, lokacja sprzed backfillu), zeznanie
    rozstrzyga. Predykat jest przy tym
    świadomie SZERSZY od dawnego eventu `kind.unmapped` (ten wymagał NIEPUSTEGO IMAGETYP): czytelne
    zeznanie z nierozpoznanym rodzajem wymaga decyzji tak samo jak zeznanie z rodzajem niezmapowanym
    — brak IMAGETYP był dotąd cichym NULL-em, którego raport nie pokazywał.

    `unreadable` (#13) idzie po `location.unreadable_since IS NOT NULL` (join po kopii, DISTINCT po
    klatce) i dokłada TRZECI dyzjunkt do `total` — kopia, która stała się nieczytelna, wchodzi do
    kolejki jak „bez nagłówka", nawet gdy frame ma poprawne zeznanie (marker gaśnie po udanym odczycie).

    `no_config` jest KIND-AWARE (`grouper.NO_TELESCOPE_KINDS`): dark/bias nie mają osi teleskopu, więc
    ich `config_id IS NULL` to stan docelowy, nie delta — tak jak `object_id IS NULL` dla kalibracji.
    Lista rodzajów idzie do SQL przez `json_each(?)` (literał stały + jeden parametr), żeby zbiór miał
    JEDNEGO właściciela w `grouper` zamiast kopii wklejonej w predykat.

    KLATKA ZASTĄPIONA (`superseded_by IS NOT NULL`) NIE JEST W KOLEJCE — warunek stoi w KAŻDYM
    członie, także w `total`, bo kolejka przeglądu jest listą ROBOTY, a robotę takiej klatki przejęła
    następczyni. Zmierzone 2026-08-09: bez tego `headerless` pokazywał 1, a była to klatka, która
    nagłówka nigdy już nie dostanie (nie ma lokacji, więc nie ma czego przeczytać) — licznik nie
    do wyzerowania żadnym gestem. Populacja jest widoczna perspektywą „Zastąpione"
    (`gui.queries.superseded_frame_ids`), więc znika z kolejki, a nie z oczu."""
    off_axis = json.dumps(sorted(NO_TELESCOPE_KINDS))
    no_config = con.execute(
        "SELECT count(*) FROM frame f WHERE f.config_id IS NULL "
        "AND f.superseded_by IS NULL "
        "AND f.retired_at IS NULL "
        "AND f.kind NOT IN (SELECT value FROM json_each(?)) "
        "AND EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)", (off_axis,)).fetchone()[0]
    headerless = con.execute(
        "SELECT count(*) FROM frame f WHERE f.superseded_by IS NULL "
        "AND f.retired_at IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)").fetchone()[0]
    no_camera = con.execute(
        "SELECT count(*) FROM frame f WHERE f.camera_id IS NULL "
        "AND f.superseded_by IS NULL "
        "AND f.retired_at IS NULL "
        "AND EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)").fetchone()[0]
    kind_unknown = con.execute(
        "SELECT count(*) FROM frame f WHERE f.kind = 'unknown' "
        "AND f.superseded_by IS NULL "
        "AND f.retired_at IS NULL "
        "AND EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)").fetchone()[0]
    # #13: DISTINCT klatek z ≥1 kopią oznaczoną nieczytelną (fakt o KOPII zliczony po klatkach —
    # spójność z resztą liczników). Join po location; DISTINCT bo frame 1:N location.
    unreadable = con.execute(
        "SELECT count(DISTINCT f.id) FROM frame f JOIN location l ON l.frame_id = f.id "
        "WHERE f.superseded_by IS NULL AND f.retired_at IS NULL "
        "AND l.unreadable_since IS NOT NULL").fetchone()[0]
    total = con.execute(
        "SELECT count(*) FROM frame f WHERE f.superseded_by IS NULL AND f.retired_at IS NULL AND ("
        "NOT EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id) "
        "OR (((f.config_id IS NULL "
        "      AND f.kind NOT IN (SELECT value FROM json_each(?))) "
        "     OR f.camera_id IS NULL OR f.kind = 'unknown') "
        "    AND EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)) "
        "OR EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id "
        "           AND l.unreadable_since IS NOT NULL))", (off_axis,)).fetchone()[0]
    return ReviewState(no_config=no_config, headerless=headerless, no_camera=no_camera,
                       kind_unknown=kind_unknown, unreadable=unreadable, total=total)


NO_OBJECT_CARD_FILETYPES = ("raw",)
"""Formaty, które NIE MAJĄ JAK zeznać o obiekcie — JEDYNY właściciel tego faktu.

EXIF nie zna pola `OBJECT` ani RA/DEC, więc RAW-owy light nie dostanie obiektu ANI z nagłówka,
ANI z regionu po współrzędnych: milczenie tego pliku jest STANEM DOCELOWYM formatu, nie luką
do naprawienia. Zmierzone na realnym archiwum 2026-08-01: **0 z 763** RAW-lightów ma `object_raw`.

To ta sama figura myślowa, co `grouper.NO_TELESCOPE_KINDS` na osi teleskopu i „kalibracja nie ma
obiektu" na osi obiektu (kind-aware) — tyle że oś podziału jest tu FORMAT, nie rodzaj klatki.
Konsumenci biorą TĘ stałą przez `json_each(?)`; kopiowanie listy do predykatu jest zakazane
(#12 „jeden właściciel").

Czego ta stała NIE mówi: że RAW nie wymaga przeglądu. Wymaga — tylko drogą RĘCZNĄ
(„Przypisz obiekt…"), nie kartą w pliku (`macro.resolve_target` odmawia RAW: read-only).
Dlatego populacja idzie do WŁASNEGO kubełka (`nameless_raw_lights`), a nie znika z rachunku."""


def name_resolves(con, text):
    """Czy przebieg resolvera rozpozna TĘ NAZWĘ po wpisaniu jej do nagłówka — pytanie bramki dialogu
    „Napraw nagłówek…" (P-D), zadane TĄ SAMĄ drabiną, którą pójdzie `run_resolver`. Read-only.

    Szczeble zależne od NAZWY, w kolejności przebiegu: `resolve_solar` → `resolve_object` → **ALIAS**
    (`object_alias` — jawna wiedza usera z „Przypisz obiekt…"). Region świadomie POZA drabiną: on
    rozpoznaje ze WSPÓŁRZĘDNYCH, więc od wpisanego tekstu nie zależy, a dla każdej klatki wchodzącej
    do dialogu (`object_id IS NULL`) już się nie odezwał.

    Dlaczego nie sam `resolve_object` (adjudykacja bramki, 2026-08-01): pytanie „czy po zapisie oś
    się wypełni" ma w przebiegu TRZY odpowiedzi twierdzące, a bramka znała jedną. Zmierzone odmowy
    fałszywe: `Moon`/`Jupiter`/`C/2023 A3` (solar — archiwum ma `_COMETS` i `_SOLAR` jako realne
    lighty) oraz nazwa świeżo nauczona aliasem (od S1 `WR134` zna już SŁOWNIK, więc przykładem
    jest dowolna nazwa nauczona ręką — bez numeru
    katalogowego). Obie populacje resolver rozwiązuje, więc odmowa zapisu była nieprawdą o własnym
    zachowaniu.

    Od S2 to jedno zdanie nad `resolve_name`: „pierwszy człon drabiny nie jest None". Własna kopia
    kolejności szczebli zniknęła — była trzecim miejscem, w którym repo odpowiadało na to samo
    pytanie, i to ona miałaby prawo rozjechać się z przebiegiem po cichu."""
    return resolve_name(alias_lookup(con), text)[0] is not None


def nameless_lights(con):
    """Lighty, których nagłówek MILCZY o obiekcie, a format POZWALAŁBY mu mówić: `object_id IS NULL`,
    wiersz `header` JEST, `object_raw IS NULL`, `filetype` spoza `NO_OBJECT_CARD_FILETYPES` (P-D).
    Rdzeniowy właściciel predykatu — read-only, zero zapisu.

    Po co osobno od `object_unresolved`: mianownik delty WYMAGA `object_raw NOT NULL`
    (`delta_report` niżej), więc raport dostawy był na tę populację ŚLEPY — bramka akceptacji
    świeciła zielono o klatkach, których nie widzi, a pierwsza nowa dostawa bez `OBJECT`
    przeszłaby bez śladu. To jest KOTWICA NAWROTU: P-D naprawiła 25 plików na `R:` (pilot
    2026-08-01), a ta liczba pilnuje, żeby populacja nie odrosła po cichu.

    ŚWIADOMA FORMATU od 2026-08-01: bez tego warunku kotwica mieszała 25 klatek FITS (naprawialnych
    kartą) z 763 RAW-ami, których naprawić się NIE DA — jedna liczba na dwie populacje nie pilnuje
    żadnej z nich, bo ruch jednej maskuje ruch drugiej. RAW liczy `nameless_raw_lights`.
    Format NIEZNANY (`filetype IS NULL`) liczy się TUTAJ, stąd `COALESCE` (R-S4-10; uzasadnienie
    w `gui.queries.nameless_frames`): goły `NOT IN` wyrzucał NULL z obu kubełków naraz.

    Drążenie do klatek (grupy, cel writebacku) daje `gui.queries.nameless_frames` — TEN SAM
    predykat, znak w znak. Dwa literały, bo warstwy są dwie i zależność idzie w jedną stronę
    (`gui.queries` importuje ten moduł, nie odwrotnie); równość obu pinuje test.

    ZAWĘŻONY DO `kind='light'` od 2026-08-01 (I-2b/D-P-I-5): gotowe stacki wciągnięte drogą
    „Stosy" są `master_light` i mają WŁASNY kubełek (`nameless_stacks`) — ta sama zasada, co przy
    RAW-ach, tylko oś inna. Bez zawężenia 22 stacki bez `OBJECT` dopisałyby się do 25 klatek
    archiwum i kotwica nawrotu przestałaby pilnować tej, dla której powstała.

    Literał PEŁNY, mimo że bliźniaki niżej różnią się jednym słowem: wspólny prefiks + sklejenie
    czyni SQL nie-literałem, a `_first_sql_verb` zwraca wtedy `None` = offender bramki AST §8.1
    (złapane przebiegiem 2026-08-01 — bramka zadziałała dokładnie tak, jak miała)."""
    return con.execute(
        "SELECT count(*) FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind = 'light' AND f.object_id IS NULL "
        "AND f.superseded_by IS NULL "
        "AND f.retired_at IS NULL "
        "AND h.object_raw IS NULL "
        "AND COALESCE(f.filetype, '') NOT IN (SELECT value FROM json_each(?))",
        (json.dumps(list(NO_OBJECT_CARD_FILETYPES)),)).fetchone()[0]


def nameless_raw_lights(con):
    """Lighty bez obiektu w formacie, który NIE MA JAK go podać (`NO_OBJECT_CARD_FILETYPES`).

    Osobny kubełek, nie odjęcie: te klatki zostają w perspektywie „Do przeglądu" (`object_id IS
    NULL`), więc partycja kolejki musi je gdzieś policzyć — inaczej `review_queue` przestałaby
    domykać się do `review_frame_ids` dokładnie o tę populację. Droga naprawy jest inna niż dla
    `nameless_lights`: ręczne „Przypisz obiekt…", nigdy karta w pliku.

    Drążenie do klatek (grupa celu ręcznego przypisania) daje `gui.queries.nameless_raw_frames` —
    TEN SAM predykat, znak w znak, i to ONO jest od S4 licznikiem kubełka. Dwa literały, bo warstwy
    są dwie i zależność idzie w jedną stronę; równość obu pinuje test (bramka 13).

    `kind='light'` jest tu STRUKTURALNIE równoważne dawnemu `IN ('light','master_light')`, nie
    zawężeniem: `filetype='raw'` bierze rodzaj z FOLDERU (`kind_from_path`), a ta mapa zna
    wyłącznie light/dark/flat/bias — RAW-owy `master_light` nie ma jak powstać. Napisane wprost,
    żeby trzy kubełki były rozłączne z WIDOKU, nie z rozumowania."""
    return con.execute(
        "SELECT count(*) FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind = 'light' AND f.object_id IS NULL "
        "AND f.superseded_by IS NULL "
        "AND f.retired_at IS NULL "
        "AND h.object_raw IS NULL "
        "AND f.filetype IN (SELECT value FROM json_each(?))",
        (json.dumps(list(NO_OBJECT_CARD_FILETYPES)),)).fetchone()[0]


def nameless_stacks(con):
    """GOTOWE STACKI, których nagłówek milczy o obiekcie (I-2b/D-P-I-5): `kind='master_light'`,
    `object_id IS NULL`, wiersz `header` JEST, `object_raw IS NULL`.

    TRZECI kubełek tej samej partycji, z tego samego powodu co RAW-owy: `review_frame_ids` pyta
    o sam brak obiektu, więc stacki w nim SĄ — wycięcie ich z `nameless_lights` bez policzenia
    tutaj rozspójniłoby kolejkę dokładnie o tę populację.

    DROGA NAPRAWY JEST TA SAMA CO U LIGHTÓW od D-0802-1 (2026-08-02): karta `OBJECT` wraca do
    PLIKU, oknem „Napraw nagłówek…". Do tego dnia kubełek był INFORMACYJNY z powodu, który
    przestał obowiązywać — pisarz XISF nie umiał dopisać karty (D-X-12), więc akcja kończyłaby się
    'blocked' na każdej pozycji; P6d go tego nauczyła (`scan.build_fits_keyword_element`).

    OSOBNY kubełek zostaje, bo to osobna POPULACJA: gotowy obraz po integracji nie jest klatką
    z teleskopu, a partycja kolejki musi liczyć oba zbiory rozłącznie (`review_frame_ids` pyta
    o sam brak obiektu, więc stacki w nim SĄ). Drążenie do klatek =
    `gui.queries.nameless_stack_frames` — ten sam predykat, znak w znak; równość pinuje test."""
    return con.execute(
        "SELECT count(*) FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind = 'master_light' AND f.object_id IS NULL "
        "AND f.superseded_by IS NULL "
        "AND f.retired_at IS NULL "
        "AND h.object_raw IS NULL").fetchone()[0]


@dataclass
class DeltaReport:
    """Read-only delta do review (§Etap 6/§4.7) — wejście do przyszłego import-legacy. Liczy obiekt
    na light/master_light (kalibracja świadomie poza — nie ma obiektu)."""
    object_resolved: int = 0
    object_unresolved: int = 0
    object_pct: float = 0.0
    object_delta: list = field(default_factory=list)   # [(object_raw, count)] nierozpoznane light'y
    review: ReviewState = field(default_factory=ReviewState)   # kolejka ze STANU (#12), nie z eventów
    filters_canon: int = 0
    object_nameless: int = 0   # lighty BEZ `object_raw` — poza mianownikiem delty (P-D/D-PD-10)
    # …a te BEZ `object_raw` i bez SZANSY na niego (format nie zna karty; `NO_OBJECT_CARD_FILETYPES`).
    # Osobne pole, bo osobna droga naprawy: ręczne przypisanie, nigdy zapis karty do pliku.
    object_nameless_raw: int = 0
    # …a te są GOTOWYMI OBRAZAMI po integracji (I-2b/D-P-I-5). Osobne pole, bo osobna POPULACJA —
    # droga naprawy jest od D-0802-1 TA SAMA co u lightów (karta `OBJECT` do pliku, P6d).
    object_nameless_stacks: int = 0
    # Klatki, które obiekt MAJĄ, choć nazwy w nagłówku nie było — rozwiązane innym świadkiem niż
    # nazwa (dziś: region). Do `object_pct` NIE wchodzą, bo procent mierzy rozpoznanie NAZWY, a te
    # klatki nazwy nie mają. Stoją obok, żeby zawężenie licznika niczego nie schowało.
    # ŚWIADOMIE `LEFT JOIN`, wbrew symetrii z bliźniakami (one mają INNER): pole ma pokazać CAŁĄ
    # populację wypchniętą z procentu, a wypada z niego również klatka bez wiersza `header` w ogóle.
    # Dwie klasy pod jedną liczbą — dziś druga jest pusta (szkielety mają `kind='unknown'`, więc nie
    # są lightem), ale gdyby przestała być, to TU się pokaże, zamiast zniknąć między predykatami.
    object_resolved_no_raw: int = 0
    # NAGROBEK MA WŁASNĄ LICZBĘ, a nie własne wykluczenie (S3/R-S2b-2, rozstrzygnięcie briefu §5).
    # Klatka, której człowiek ZDJĄŁ nazwę, zostaje w `object_unresolved` i w `object_delta` — bo
    # wykluczenie jej z delty PODNOSIŁOBY `object_pct`, czyli metryka nagradzałaby odrzucenie
    # zeznania, a ma mierzyć ROZPOZNANIE. Bez osobnej liczby raport nie umiał jednak powiedzieć,
    # ile z „nierozpoznanych" to WERDYKT, a nie brak wiedzy: przebieg meldował `objects_review = 0`
    # (drabina pomija nagrobek poprawnie), a delta pokazywała tę samą populację jako nierozpoznaną.
    # Dwa ekrany, dwie prawdy o jednym zbiorze. Predykat stoi na SAMYM `object_source`, NIEZALEŻNIE
    # od `object_raw` — inaczej cofnięty RAW nazwany ze ścieżki wypadałby z liczby, a bramka 14b
    # żąda wyniku na OBU populacjach.
    #
    # DWIE LICZBY, NIE JEDNA (recenzja + wizytacja S3, oba silniki niezależnie). Nagrobki NIE SĄ
    # podzbiorem żadnego pojedynczego zdania raportu, bo `object_source` nic nie mówi o `object_raw`:
    # klatka z nazwą w nagłówku ląduje w `object_unresolved`, a bezimienna w `object_nameless*`.
    # Jedna liczba doklejona do któregokolwiek z tych zdań jest ARYTMETYCZNIE FAŁSZYWA — zmierzone
    # na kopii żywej `pf4`: 16 nagrobków (9 bezimiennych + 7 z nazwą) renderowało się jako
    # „bez nazwy w nagłówku: 0 · z tego cofnięte ręką: 16". Granica biegnie tam, gdzie raport już
    # ją trzyma, więc rozbicie nie wprowadza nowej osi — czyta istniejącą.
    object_cleared_named: int = 0      # …z `object_raw` — PODZBIÓR `object_unresolved`
    object_cleared_nameless: int = 0   # …bez `object_raw` — PODZBIÓR `object_nameless*` (FITS/RAW/stos)

    @property
    def object_cleared(self):
        """Wszystkie nagrobki — kotwica bramki 14b i CLI. Suma, nie trzeci literał (SPOT)."""
        return self.object_cleared_named + self.object_cleared_nameless


def delta_report(con, top=30):
    """Zbierz deltę nierozstrzygniętych (read-only, zero zapisu). % obiektu liczone NA light'ach
    (mianownik = light/master_light z obecnym object_raw); kalibracja nie zaniża wyniku.

    LICZNIK STOI NA TEJ SAMEJ POPULACJI CO MIANOWNIK — `object_raw NOT NULL` po obu stronach.
    Wcześniej licznik brał każdą klatkę z obiektem, także rozwiązaną REGIONEM bez nazwy w nagłówku,
    więc procent rósł o klatki, których mianownik nie widział, i **maskował spadek rozpoznania**:
    napływ klatek nierozpoznanych rozcieńczał się o stałą premię. Wypchnięta populacja nie znika
    z raportu — ma własne pole `object_resolved_no_raw`.

    `object_nameless` stoi OBOK procentu, nie w nim: klatka bez `object_raw` nie ma jak być
    „nierozpoznana pod nazwą" (nie ma nazwy), więc do mianownika nie wchodzi — ale musi być
    WIDOCZNA, inaczej raport milczy o całej klasie (P-D/D-PD-10).

    `object_nameless_raw` i `object_nameless_stacks` idą OSOBNO od `object_nameless`, bo to trzy
    różne POPULACJE pod jednym objawem: light archiwum i gotowy stos naprawia karta w pliku
    (stos od D-0802-1/P6d — wcześniej nie naprawiało go nic), RAW-a wyłącznie ręka. Zlanie ich
    w jedną liczbę sprawia, że kotwica nawrotu nie pilnuje żadnej — 763 RAW-y przykryłyby każdy
    ruch w populacji FITS, a 22 stacki przykryłyby ruch w niej po raz drugi."""
    resolved = con.execute(
        "SELECT count(*) FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind IN ('light','master_light') AND f.object_id IS NOT NULL "
        "AND f.retired_at IS NULL AND f.superseded_by IS NULL "
        "AND h.object_raw IS NOT NULL").fetchone()[0]
    resolved_no_raw = con.execute(
        "SELECT count(*) FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind IN ('light','master_light') AND f.object_id IS NOT NULL "
        "AND f.retired_at IS NULL AND f.superseded_by IS NULL "
        "AND h.object_raw IS NULL").fetchone()[0]
    unresolved = con.execute(
        "SELECT count(*) FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind IN ('light','master_light') AND f.object_id IS NULL "
        "AND f.retired_at IS NULL AND f.superseded_by IS NULL "
        "AND h.object_raw IS NOT NULL").fetchone()[0]
    total = resolved + unresolved
    pct = round(100.0 * resolved / total, 1) if total else 0.0
    delta = con.execute(
        "SELECT h.object_raw AS raw, count(*) AS n FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind IN ('light','master_light') AND f.object_id IS NULL "
        "AND f.retired_at IS NULL AND f.superseded_by IS NULL "
        "AND h.object_raw IS NOT NULL GROUP BY h.object_raw ORDER BY n DESC, raw LIMIT ?",
        (top,)).fetchall()
    # Nagrobki rozbite po TEJ SAMEJ granicy, którą raport trzyma wyżej (`object_raw` obecny czy nie),
    # bo tylko wtedy każda z dwóch liczb jest PODZBIOREM zdania, do którego się dokleja. `LEFT JOIN`,
    # nie `INNER`: klatka bez wiersza `header` też może mieć nagrobek i musi wpaść do „bezimiennych",
    # a nie wyparować między predykatami.
    cleared_named, cleared_nameless = con.execute(
        "SELECT count(*) FILTER (WHERE h.object_raw IS NOT NULL), "
        "       count(*) FILTER (WHERE h.object_raw IS NULL) "
        "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind IN ('light','master_light') AND f.retired_at IS NULL AND f.superseded_by IS NULL "
        "AND f.object_source = 'user_cleared'"
    ).fetchone()
    filters_canon = con.execute(
        "SELECT count(*) FROM frame WHERE filter_canon IS NOT NULL").fetchone()[0]
    return DeltaReport(
        object_resolved=resolved, object_unresolved=unresolved, object_pct=pct,
        object_resolved_no_raw=resolved_no_raw,
        object_cleared_named=cleared_named, object_cleared_nameless=cleared_nameless,
        object_delta=[(r["raw"], r["n"]) for r in delta], review=review_state(con),
        filters_canon=filters_canon, object_nameless=nameless_lights(con),
        object_nameless_raw=nameless_raw_lights(con),
        object_nameless_stacks=nameless_stacks(con))
