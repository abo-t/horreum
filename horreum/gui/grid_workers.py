"""Robotnicy tła widoku „Klatki" - pokrycie panelu „Pola" i skład zbioru poza wątkiem GUI.

`PolaWorker` i `ZbiorWorker` liczą na WŁASNYM połączeniu (migawka WAL), wynik oddają sygnałem
z numerem generacji. `_sklad_zbioru` to jeden kod składu zbioru dla wątku GUI i robotnika (AR-27),
z licznikami listwy facetów (`_liczniki_listwy`) liczonymi jedną derywacją trimów.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Slot

from horreum import db, filter_engine, pivot as pivot_mod, repo
from horreum.gui import facet_model, i18n, portfolio, queries
from horreum.gui import pola as pola_mod
from horreum.gui import assign_dialog
from horreum.gui.grid_model import (_adnotuj_rodowod, _adnotuj_wersje, _derive, _dolacz_kopie,
                                    _STANY_RODOWODU)
from horreum.gui.wb_worker import tekst_powodu       # zdanie błędu w języku UI (AR-198)
from horreum.item_reasons import blad_systemu


class PolaWorker(QObject):
    """Pokrycie panelu „Pola" liczone POZA wątkiem GUI (rdzeń: Qt-wolny `pola`, koszty tam).

    Bliźniak `PlanWorker`: `db_path` → WŁASNE połączenie otwarte w SWOIM wątku (sqlite
    `check_same_thread`), odcisk i pokrycie w jednej transakcji czytającej; `con` (tryb inline,
    testy i `:memory:`) → ten sam rdzeń na połączeniu wołającego, bez transakcji, bo bez wątku.
    `poprzedni_odcisk` równy bieżącemu = karty bez zmian: `keyword_facets` NIE jest wołane,
    a `done` niesie `None` zamiast pól (listwa zostaje, jaka była).

    ANULOWANIE MUSI UMIEĆ PRZERWAĆ SAMO ZAPYTANIE: pokrycie to jedno zapytanie trwające sekundy,
    więc flaga sprawdzana „przed następnym krokiem" kazałaby zamknięciu okna czekać do jego końca.
    `Connection.interrupt` jest w sqlite3 wprost przeznaczone do wołania z INNEGO wątku; zamek
    pilnuje, żeby nie trafiło w połączenie właśnie zamykane."""

    done = Signal(int, object, object)   # generacja, odcisk, pola (lista słowników) albo None
    failed = Signal(int, str)            # generacja, komunikat
    finished = Signal()                  # run() wrócił KAŻDĄ drogą → quit wątku

    def __init__(self, gen, poprzedni_odcisk, *, db_path=None, con=None):
        super().__init__()
        self._gen = gen
        self._poprzedni = poprzedni_odcisk
        self._db_path = db_path
        self._con_zewn = con
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
        odcisk = pola = error = None
        try:
            if self._con_zewn is not None:
                odcisk, pola = self._policz(self._con_zewn)
            else:
                with self._zamek:
                    self._con = db.connect(self._db_path)
                try:
                    # Migawka WAL na oba zapytania: odcisk opisuje dokładnie dane pokrycia.
                    self._con.execute("BEGIN")
                    odcisk, pola = self._policz(self._con)
                finally:
                    with self._zamek:
                        self._con.close()          # PRZED emisją - główny wątek czyta przez swoje
                        self._con = None
        except Exception as exc:                   # błąd (także przerwanie) → sygnał, NIE crash
            # Zdanie w języku UI składane TU (wzorzec `WritebackWorker.run`): odbiorca w `grid.py`
            # bierze tekst. Pokrycie czyta wyłącznie bazę, więc realna awaria to błąd SQLite -
            # klasą bazy (AR-198); przerwanie zapytania (stara generacja) zostaje tekstem SQLite.
            error = tekst_powodu(blad_systemu(exc))
        if error is not None:
            self.failed.emit(self._gen, error)
        else:
            self.done.emit(self._gen, odcisk, pola)
        self.finished.emit()

    def _policz(self, con):
        odcisk = pola_mod.odcisk_kart(con)
        if odcisk == self._poprzedni:
            return odcisk, None                    # karty bez zmian - liczyć nie ma czego
        if self._cancel.is_set():
            raise RuntimeError("przerwano")
        return odcisk, pola_mod.pokrycie(con)


# ---- skład danych gridu (AR-27): czysty odczyt, bez widżetów - wątek GUI albo `ZbiorWorker` ----

def _memo_leaf_fns(con, stany=None):
    """Memoizowane akcesory silnika na czas JEDNEGO składu (F4R2#4): sibling-sety facetów
    re-używają tych samych liści, więc cache `(kind,kw,p1,p2)→set` zwija 5N wywołań liści do N.
    Jedna migawka DB per skład - cache umiera razem z nim (źródło prawdy = baza).

    `stany` = stan rodowodu gotowych obrazów policzony RAZ na skład (`queries.stack_lineage_states`):
    liść facetu „Rodowód" filtruje ten słownik zamiast liczyć read-model od nowa per wartość."""
    leaf_cache = {}
    universe_cache = []

    def leaf_fn(k, kw, p1, p2):
        key = (k, kw, p1, p2)
        if key not in leaf_cache:
            leaf_cache[key] = (queries.lineage_state_frame_ids(stany, p1)
                               if k == "rel_lineage" and stany is not None
                               else queries.leaf_frame_ids(con, k, kw, p1, p2))
        return leaf_cache[key]

    def universe_fn():
        if not universe_cache:
            universe_cache.append(queries.all_frame_ids(con))
        return universe_cache[0]

    return leaf_fn, universe_fn


def _sklad_zbioru(con, stan, przerwij=lambda: None):
    """Migawka stanu widoku (`FramesView._migawka_zbioru`) → dane gridu i listwy. ZERO widżetów, więc
    ten sam kod liczy na wątku GUI (tryb inline, gesty) i w `ZbiorWorker` na jego własnym połączeniu.
    `przerwij` rzuca, gdy zlecenie straciło sens (nowsze w kolejce, widok znika) - wołane między
    krokami; zapytanie w locie przerywa `Connection.interrupt` u wołającego.

    Zwraca słownik dla `FramesView._zastosuj_zbior`: wiersze `base`, `pivot`, `keywords`, `base_ids`,
    liczniki listwy `listwa` i `baza_ma_klatki` (rozróżnienie pustego stanu, wiz F5 #8)."""
    # Stan rodowodu gotowych obrazów RAZ na skład: kolumna, liść facetu, widoczność grupy i liczniki
    # listwy czytają ten sam słownik (jedna migawka, zero powtórzeń read-modelu).
    # ZBIÓR KUBEŁKA RODOWODU TEŻ RAZ (AR-154): liczy propozycję dla ~33 stosów (36 ms na kopii pf4),
    # a perspektywa „Rodowód do potwierdzenia" bierze go dodatkowo jako trim - ten sam wynik idzie
    # do stanów i do trimu, zamiast drugiego liczenia.
    # Ten sam przebieg daje też stosy z samymi klatkami nowszymi niż obraz (stan `only_newer`, AR-171).
    zbiory = queries.lineage_hand_sets(con)
    stany = queries.stack_lineage_states(con, zbiory=zbiory)
    gotowe_trimy = {"lineage_pending_frame_ids": zbiory.pending}
    # Obrazy z wejściem ręki nowszym niż obraz (AR-153) - trim perspektywy wiersza Porządków i wariant
    # podpowiedzi „dokładny" w kolumnie. Liczone RAZ na skład: tu, gdy perspektywa je przycina, niżej
    # (po wierszach) - tylko gdy w zbiorze stoi obraz „dokładny" i podpowiedź ma kogo dotyczyć.
    if "lineage_newer_frame_ids" in stan["trimy"]:
        gotowe_trimy["lineage_newer_frame_ids"] = queries.lineage_newer_frame_ids(con)
    leaf_fn, universe_fn = _memo_leaf_fns(con, stany)
    frame_ids = filter_engine.run(stan["drzewo"], leaf_fn=leaf_fn, universe_fn=universe_fn)
    # JEDNA derywacja trimu dla zbioru głównego I dla sibling-setów listwy (SPOT, F4R2#2) -
    # lista powstaje RAZ i idzie w obie strony. Dwie kopie tej enumeracji rozjechały się
    # dokładnie tak, jak zapowiada historia rodziny `only_*`: listwa dostawała `dup_ids`
    # i `review_ids`, a pięciu młodszych braci nie widziała w ogóle, więc w perspektywie
    # z trimem liczniki facetów i godziny portfela liczyły się na zbiorze BEZ przycięcia.
    # Skład rodziny czyta migawka z `_TRIMY` (BP-4), więc dołożenie ósmej flagi jest wpisem
    # w tabelę, a nie ósmym miejscem do zapamiętania.
    trims = [gotowe_trimy[nazwa] if nazwa in gotowe_trimy else getattr(queries, nazwa)(con)
             for nazwa in stan["trimy"]]
    # TEKST UWAG TNIE JAK TRIM - w tę samą listę, więc ten sam zbiór dostają i grid, i sibling-sety
    # listwy (liczniki facetów przy `uwagi:chmury` liczą klatki z tą uwagą, nie całe archiwum).
    # `.get`: migawka sprzed tego składnika (test, który ją składa ręcznie) znaczy „bez uwag".
    if stan.get("uwagi") is not None:
        trims.append(set(queries.note_hits(con, stan["uwagi"])))
    # KLATKI WSKAZANE WPROST (dwuklik w panelu rodowodu, `FramesView.show_frames`) - ta sama lista,
    # więc i listwa liczy na nich, a nie na całym archiwum.
    if stan.get("wskazane") is not None:
        trims.append(set(stan["wskazane"]))
    # NOWY set, NIGDY `&=`: przy pustym filtrze `filter_engine.run` zwraca uniwersum WPROST
    # (`filter_engine.py:171`), a to jest ZAPAMIĘTANY obiekt memoizacji (`_memo_leaf_fns`).
    # `&=` przycinało go W MIEJSCU, więc kolejne `universe_fn()` widziało już przycięty zbiór -
    # perspektywa z trimem potrafiła pokazać „Baza pusta" na pełnej bazie (wizytator P5 #2).
    for trim in trims:
        frame_ids = frame_ids & trim
    przerwij()
    base = [_derive(r) for r in queries.base_rows(con, list(frame_ids))]
    nowsze = gotowe_trimy.get("lineage_newer_frame_ids")
    if nowsze is None and any(stany.get(b["frame_id"]) == "exact" for b in base):
        nowsze = queries.lineage_newer_frame_ids(con)
    _adnotuj_rodowod(base, stany, nowsze or ())   # kolumna „Rodowód" - ten sam słownik co facet
    if stan["wersje"]:
        _adnotuj_wersje(base, queries.stack_version_groups(con))
    # Fakty KOPII (0021) - pytamy wyłącznie o klatki z kilkoma obecnymi kopiami: kolumna
    # „Obrazy" i podpowiedź „×N" potrzebują wtedy każdej kopii, a reszta archiwum ma jedną
    # i jej liczbę niesie już `base_rows`. Wąskie zapytanie zamiast podzapytania na 16 tys. wierszy.
    # Kotwice ręki tych samych klatek - jednym zapytaniem, nie per klatka (znacznik „wskazana ręką").
    wielokopiowe = [b["frame_id"] for b in base if (b.get("n_present") or 0) > 1]
    _dolacz_kopie(base, queries.present_copy_facts(con, wielokopiowe),
                  repo.hand_lead_locations(con, wielokopiowe))
    base_ids = [b["frame_id"] for b in base]
    keywords = list(stan["kolumny"])
    przerwij()
    karty = queries.cards_pivot(con, base_ids, keywords) if (base_ids and keywords) else []
    pv = pivot_mod.build_pivot(base_ids, keywords, karty)
    przerwij()
    listwa = _liczniki_listwy(con, stan["facety"], stan["filtr"], leaf_fn, universe_fn,
                              trims, base_ids, stany)
    # Uniwersum bierzemy z memoizowanego `universe_fn` TEGO składu - na niepustym gridzie
    # zapytania nie ma w ogóle, a gdy filtr już go dotknął, jest z cache'u.
    # Migawka wraca razem z wynikiem: przyłożenie mówi o składnikach TEGO zbioru (chipy Znajdź),
    # a nie o stanie widoku z chwili, w której wynik dojechał.
    return {"base": base, "pivot": pv, "keywords": keywords, "base_ids": base_ids,
            "listwa": listwa, "baza_ma_klatki": bool(base) or bool(universe_fn()),
            "migawka": stan}


def _liczniki_listwy(con, facet_state, filter_tree, leaf_fn, universe_fn, trims, current_ids,
                     stany=None):
    """Liczniki listwy facetów per SIBLING-SET (F4R#1): zbiór facetu F = compose bez CAŁEJ własnej
    grupy F (in+ex) - liczniki na pełnym zbiorze samo-zawężałyby facet i OR-wewnątrz byłby
    nieosiągalny. Facet BEZ aktywnego wyboru → sibling == zbiór bieżący (już policzony;
    D-UX-3(a)). Trim perspektywy = przecięcie z gotowymi setami (F4R2#2, bez base_rows).

    `trims` przychodzi ze składu GOTOWĄ LISTĄ, a nie jako dwa nazwane sety: enumeracja
    rodziny `only_*` ma tu jednego właściciela, więc dołożenie siódmej perspektywy nie może
    po cichu ominąć liczników listwy (to jest ta sama klasa rozjazdu, którą rodzina
    przechodziła już dwa razy).

    `stany` = stan rodowodu z tego samego składu (`_sklad_zbioru`); `None` = policz tu, raz.

    Zwraca `(counts, extras, aliases, alias_forms)` - komplet argumentów `FacetRail.set_data`
    poza stanem i odsłonięciem, które należą do widoku (`FramesView._zastosuj_listwe`)."""
    if stany is None:
        stany = queries.stack_lineage_states(con)
    counts, extras = {}, {}
    for facet in facet_model.FACETS:
        if facet == "lineage" and facet not in facet_state and not _same_gotowe_obrazy(
                stany, current_ids):
            # RODOWÓD WCHODZI DO LISTWY, GDY ZBIÓR TO GOTOWE OBRAZY (preset „Gotowe obrazy",
            # Rodzaj = master_light, perspektywa rodowodu) albo gdy facet ma już wybór. Nad
            # zbiorem mieszanym grupa stałaby zawsze (stosy są w każdym archiwum) i podnosiła
            # podłogę okna o 74 px (zmierzone na kopii `pf4`: 825 → 899) dla pytania, które
            # dotyczy jednego rodzaju. Pusta lista = grupa gaśnie (`FacetRail`, `_ZNIKAJACE`).
            counts[facet] = []
            continue
        if facet not in facet_state:
            ids = current_ids
        else:
            tree = facet_model.compose(facet_model.sibling_state(facet_state, facet), filter_tree)
            sib = filter_engine.run(tree, leaf_fn=leaf_fn, universe_fn=universe_fn)
            # NOWY set, NIGDY `&=` - z tego samego powodu, co w składzie zbioru: sibling-set powstaje
            # z drzewa BEZ własnej grupy facetu, więc przy jednym aktywnym facecie i pustym
            # filtrze `compose` daje `None`, a `run` oddaje MEMOIZOWANE uniwersum. `&=` przycinało
            # je w miejscu, czyli kolejny facet tej samej pętli liczył licznik na zbiorze
            # przyciętym przez poprzednika.
            for trim in trims:
                sib = sib & trim
            ids = list(sib)
        counts[facet] = _liczniki_facetu(con, facet, ids, stany)
        if facet == "object":
            # Portfel (F7 §8): godziny lightów per obiekt na TYM SAMYM `ids` co `facet_objects`
            # (parytet n↔godziny; inne aktywne facety zawężają godziny). Formatowanie = `portfolio`.
            summ = portfolio.summarize(queries.object_exposure(con, ids))
            extras["object"] = {oid: (portfolio.object_suffix(e), portfolio.object_tooltip(e))
                                for oid, e in summ.items()}
    # DRUGIE NAZWY do szukajki (S3): mapa `canon → {alias_norm}` z CAŁEJ biblioteki, nie ze
    # zbioru - szukajka chowa wiersze listy, więc filtrowanie mapy po `ids` nic by nie
    # oszczędziło, a rozjechałoby dwa wejścia tego samego pytania. Bez niej „Large Magellanic
    # Cloud" nie znajduje niczego: kanon `LMC` nie ma z tą frazą wspólnej litery.
    # Brzmienie aliasu w podpowiedzi trafienia (AR-45) - ta sama mapa co okno „Przypisz obiekt”.
    return (counts, extras, queries.object_alias_index(con), assign_dialog.formy_aliasow(con))


def _same_gotowe_obrazy(stany, ids):
    """Czy niepusty zbiór `ids` składa się WYŁĄCZNIE z gotowych obrazów (klucze stanu rodowodu)."""
    return bool(ids) and all(fid in stany for fid in ids)


def _liczniki_facetu(con, facet, ids, stany=None):
    """Kubełki jednego facetu → list[(value, label, n)] (kontrakt `FacetRail.set_data`).
    Etykieta teleskopu = label→canon fallback z JEDNEGO właściciela (`queries.telescope_label`);
    filtr/rodzaj/noc są swoją własną etykietą."""
    if facet == "object":
        return [(r["id"], r["canon"], r["n"]) for r in queries.facet_objects(con, ids)]
    if facet == "filter":
        return [(r["filter_canon"], r["filter_canon"], r["n"])
                for r in queries.facet_filters(con, ids)]
    if facet == "channel":
        return [(r["channel"], r["channel"], r["n"])
                for r in queries.facet_channels(con, ids)]
    if facet == "kind":
        return [(r["kind"], r["kind"], r["n"]) for r in queries.facet_kinds(con, ids)]
    if facet == "lineage":
        # Etykieta z katalogu, nie token: wartość (token) niesie tożsamość, etykieta tylko mówi.
        return [(stan, i18n.t(_STANY_RODOWODU[stan]), n)
                for stan, n in queries.facet_lineage(con, ids, stany)]
    if facet == "telescope":
        return [(r["id"], queries.telescope_label(r), r["n"])
                for r in queries.facet_telescopes(con, ids)]
    return [(r["night"], r["night"], r["n"]) for r in queries.facet_nights(con, ids)]


class ZbiorWorker(QObject):
    """Skład danych gridu POZA wątkiem GUI (AR-27) - bliźniak `PolaWorker`, ten sam cykl wątku.

    Zmierzone na kopii żywej bazy (16 901 klatek, perspektywa „Przegląd"): okno stało 1,4-1,5 s po
    każdym przebiegu Dostawy i 1,2-1,5 s po każdym kliku facetu, perspektywy i kolumn, bo cały
    skład (`base_rows` + `_derive` ×16 901, `cards_pivot`, liczniki listwy) szedł w slocie. Tu
    liczy go `_sklad_zbioru` na WŁASNYM połączeniu w jednej transakcji czytającej (migawka WAL: zbiór
    i liczniki listwy opisują ten sam stan bazy); w slocie zostaje samo przyłożenie do widżetów.

    Anulowanie jak w `PolaWorker`: flaga sprawdzana między krokami składu + `Connection.interrupt`
    z wątku GUI na zapytanie w locie, pod zamkiem, żeby nie trafić w połączenie właśnie zamykane."""

    done = Signal(int, object)     # generacja, wynik `_sklad_zbioru`
    failed = Signal(int, str)      # generacja, komunikat
    finished = Signal()            # run() wrócił KAŻDĄ drogą → quit wątku

    def __init__(self, gen, stan, db_path):
        super().__init__()
        self._gen = gen
        self._stan = stan
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

    def _przerwij(self):
        if self._cancel.is_set():
            raise RuntimeError("przerwano")

    @Slot()
    def run(self):
        wynik = error = None
        try:
            with self._zamek:
                self._con = db.connect(self._db_path)
            try:
                self._con.execute("BEGIN")
                wynik = _sklad_zbioru(self._con, self._stan, self._przerwij)
            finally:
                with self._zamek:
                    self._con.close()          # PRZED emisją - główny wątek czyta przez swoje
                    self._con = None
        except Exception as exc:                   # błąd (także przerwanie) → sygnał, NIE crash
            error = tekst_powodu(blad_systemu(exc))    # jak `PolaWorker.run` (AR-198)
        if error is not None:
            self.failed.emit(self._gen, error)
        else:
            self.done.emit(self._gen, wynik)
        self.finished.emit()
