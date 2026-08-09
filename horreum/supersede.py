"""Pass ZASTĄPIENIA tożsamości (#DR2 segment R4) — kto po kim niesie plik pod tą samą ścieżką.

Skan rozstrzyga podmianę treści po `sha1_data` i przepina lokację na nową tożsamość
(`scan.py:1248` → `repo.rebind_location`). Stara klatka zostaje wtedy **sierotą**: ma nagłówek,
karty i historię, nie ma lokacji. Do 0014 ten stan nie miał w bazie nazwy — czytało się go
wyłącznie z dziennika, więc każdy konsument (dobór rodowodu, lista masterów, rachunek godzin)
widział dwie klatki tam, gdzie na dysku jest jeden plik, i liczył tę samą ekspozycję dwa razy.

Ten pass nadaje stanowi nazwę WSTECZ: replayuje `event(location.rebound)` i wypełnia
`frame.superseded_by`. Nowe podmiany oznacza już sam skan, na bieżąco — pass jest jednorazowym
domknięciem historii i siatką bezpieczeństwa, nie stałym krokiem potoku.

APPEND-ONLY (ŚWIĘTE): niczego nie kasuje — ani plików, ani wierszy. Zmienia się jedno twierdzenie:
„ta tożsamość jest bieżąca" → „niesie ją dziś klatka N". Zapis idzie WYŁĄCZNIE przez klingę
`repo.mark_superseded` (ten moduł nie wykonuje DML — meta-tripwir AST to potwierdza).

CZTERY STRAŻNIKI (W8 z recenzji — naiwny backfill „przepisz payloady" łamie się na każdym z nich):

  1. **REPLAY CHRONOLOGICZNY** (`ORDER BY ts, id`) — kolejność zapisu do dziennika jest jedyną
     prawdą o kolejności podmian; `id` rozstrzyga remis w obrębie jednego przebiegu skanu.
  2. **OSTATNI EVENT PER KLATKA** — ta sama tożsamość bywa `frame_before` więcej niż raz (kopia
     pod dwiema ścieżkami, kolejne edycje). Liczy się ostatnia obserwacja; wcześniejsze opisują
     stan, który już minął.
  3. **ŻYWOTNOŚĆ** — klatka z obecną lokacją NIE jest zastąpiona, choćby dziennik mówił inaczej:
     `frame` ma 1:N `location`, więc podmiana jednej kopii nie czyni drugiej duchem. Predykat
     liczymy tu DLA RAPORTU, a rozstrzyga go ponownie klinga pod lockiem (TOCTOU) — ten sam
     podział, co `presence.check` ↔ `mark_location_vanished`.
  4. **ODMOWA CYKLU** — `A → B → A` (edycja i cofnięcie edycji) jest zwykłym gestem człowieka.
     Wtedy ŻADNA ze stron nie jest zastąpiona i pass odmawia OBU, zamiast wybierać arbitralnie.
     Bieżącej treści dowodzi odczyt z dysku, nie dziennik — dlatego cykl gasi się skanem
     (`repo.clear_superseded`), a nie tutaj.

ŁAŃCUCH ZOSTAJE ŁAŃCUCHEM (D-DR-4): `A→B` i `B→C` zapisujemy jako dwa ogniwa, nigdy jako skrót
`A→C`. Skrót zgubiłby wersję środkową — a to ona bywa tą, do której człowiek chce wrócić.

HAMULCA MASOWEGO NIE MA — świadomie, w odróżnieniu od `presence` (D-V-4). Tamten broni przed
awarią ŚWIATA ZEWNĘTRZNEGO (share zamontowany pusty ⇒ „wszystko zniknęło"); tu wejściem jest
własny dziennik bazy, którego żadna awaria dysku nie napompuje. Granica nazwana, nie obłożona
kodem na populację, która nie ma jak powstać.
"""
from dataclasses import dataclass, field

from . import repo
from .resolve.objects import TRANSFERABLE_OBJECT_SOURCES   # jeden właściciel zbioru (SPOT)


@dataclass
class SupersedeSummary:
    """Wynik jednego przebiegu. Liczby są ROZŁĄCZNE i domykają się:
    `proposed == marked + already + alive + cycles + conflicts + missing`.
    Domknięcie jest ASERCJĄ raportu, nie ozdobą — kubełek, który wypadnie z sumy, znaczy, że
    pass odrzucił klatkę bez podania powodu (ta sama lekcja, co partycja 128 stosów w rodowodzie)."""
    events: int = 0                  # wierszy `location.rebound` przeczytanych
    proposed: int = 0                # klatek z kandydatem na następczynię (po strażniku 2)
    marked: int = 0                  # oznaczonych w tym przebiegu
    already: int = 0                 # oznaczonych wcześniej tą samą tożsamością (idempotencja)
    alive: int = 0                   # odrzuconych strażnikiem żywotności
    cycles: int = 0                  # odrzuconych odmową cyklu
    conflicts: int = 0               # ogniwo już zajęte przez INNĄ następczynię
    missing: int = 0                 # następczyni albo poprzedniczka nie istnieje w `frame`
    pairs: list = field(default_factory=list)        # [(frame_before, frame_after)] — po strażnikach
    refused: list = field(default_factory=list)      # [(frame_before, frame_after, powód)]
    superseded_by_later: list = field(default_factory=list)
    """[(klatka, następczyni_porzucona, następczyni_bieżąca)] — obserwacje przykryte późniejszym
    zdarzeniem o tej samej klatce (strażnik 2). NIE są odmową ani błędem: opisują stan, który już
    minął. Raportujemy je, bo partycja liczy klatki, nie zdarzenia — bez tej listy jedna z dwóch
    obserwacji znikałaby z rachunku i nikt by się nie dowiedział, że w ogóle była."""


def _rebound_pairs(con):
    """Pary `(frame_before, frame_after)` z dziennika, chronologicznie (strażnik 1).

    `json_extract` zamiast parsowania w Pythonie: payload jest tekstem JSON zapisanym przez
    `repo.emit_event`, a odczyt w SQL-u trzyma zapytanie literałem (bramka AST) i nie kusi
    do wciągania tu logiki, która należy do `repo`."""
    return con.execute(
        "SELECT id, "
        "       json_extract(payload, '$.frame_before') AS frame_before, "
        "       json_extract(payload, '$.frame_after')  AS frame_after "
        "FROM event WHERE verb = 'location.rebound' "
        "ORDER BY ts, id").fetchall()


def _alive(con, frame_id):
    """Czy klatka ma jeszcze OBECNĄ kopię (strażnik 3, wersja raportowa — patrz docstring modułu)."""
    return con.execute(
        "SELECT 1 FROM location WHERE frame_id = ? AND present = 1",
        (frame_id,)).fetchone() is not None


def _existing_links(con):
    """Ogniwa JUŻ zapisane w bazie — cykl trzeba wykrywać na pełnej mapie, nie na samej propozycji.
    Bez tego drugi przebieg passu po powrocie treści zobaczyłby tylko połowę pętli."""
    return {r["id"]: r["superseded_by"] for r in con.execute(
        "SELECT id, superseded_by FROM frame WHERE superseded_by IS NOT NULL")}


def _in_cycle(succ, start):
    """Czy podążanie za mapą następczyń od `start` wraca do klatki już odwiedzonej (strażnik 4)."""
    widziane = {start}
    cur = succ.get(start)
    while cur is not None:
        if cur in widziane:
            return True
        widziane.add(cur)
        cur = succ.get(cur)
    return False


def backfill(con, *, now, apply=False, actor="supersede"):
    """Jeden przebieg passu. DRY DOMYŚLNIE (`apply=False`): raportuje i NIE dotyka bazy.

    DRY jest domyślne z tego samego powodu, co w `presence`: `event` jest APPEND-ONLY, więc
    fałszywy przebieg zostawia w dzienniku tyle wierszy, ile klatek. Stan cofnie `clear_superseded`,
    dziennika nie cofnie nic.

    Zwraca `SupersedeSummary`. W DRY `marked` liczy klatki, które BY oznaczono — a nie zero, bo
    zero znaczyłoby „nie ma czego robić" i raport kłamałby o zakresie."""
    s = SupersedeSummary()
    zdarzenia = _rebound_pairs(con)
    s.events = len(zdarzenia)

    ostatnie = {}                    # strażnik 2: późniejszy event nadpisuje wcześniejszy
    for r in zdarzenia:
        before, after = r["frame_before"], r["frame_after"]
        if before is None or after is None or before == after:
            continue
        poprzednie = ostatnie.get(before)
        if poprzednie is not None and poprzednie != after:
            # NADPISANIE MELDOWANE, NIE CICHE: partycja domykałaby się mimo porzuconej pary, więc
            # raport twierdziłby „policzyłem wszystko", gdy jedna obserwacja wypadła bez powodu.
            # To ta sama klasa milczenia, co licznik bez listy — liczba się zgadza, treść ginie.
            s.superseded_by_later.append((before, poprzednie, after))
        ostatnie[before] = after

    istnieje = {r["id"] for r in con.execute("SELECT id FROM frame")}
    istniejace = _existing_links(con)

    # ŻYWOTNOŚĆ ODSIEWA PRZY BUDOWIE MAPY, NIE DOPIERO PRZY ZAPISIE — i to jest warunek
    # poprawności, nie optymalizacja. Klatka z obecną kopią NIE MOŻE być ogniwem: skoro plik pod
    # nią leży, to ona niesie treść, a nie ktoś po niej. Zostawiona w mapie tworzy POZORNE cykle
    # z dziennika, bo dziennik pamięta też podmiany, które człowiek już cofnął.
    # Przypadek wzorcowy (zarzut blokujący z bramki 0806): edycja `A → B`, potem cofnięcie edycji
    # `B → A`. Skan gasi ogniwo `A → B` (`repo.clear_superseded`), ale replay odtwarza je z dziennika
    # i `_in_cycle` widzi pętlę `A → B → A`, więc odmawia OBU. Skutek byłby dokładnie tą chorobą,
    # którą R4 leczy: `B` zostaje sierotą BEZ ogniwa, a jej godziny liczą się drugi raz — i żadne
    # narzędzie już tego nie naprawi, bo każdy kolejny przebieg powtórzy tę samą odmowę.
    # Po odsianiu żywej `A` mapa to `{B: A}`: cyklu nie ma, `B` dostaje ogniwo, rachunek się zgadza.
    zywe = {before for before in ostatnie if _alive(con, before)}
    succ = {b: a for b, a in istniejace.items() if b not in zywe}
    succ.update({b: a for b, a in ostatnie.items() if b not in zywe})

    for before, after in sorted(ostatnie.items()):
        s.proposed += 1
        if before not in istnieje or after not in istnieje:
            s.missing += 1
            s.refused.append((before, after, "klatka nie istnieje"))
            continue
        if before in zywe:
            s.alive += 1
            s.refused.append((before, after, "klatka ma obecną kopię"))
            continue
        if _in_cycle(succ, before):
            s.cycles += 1
            s.refused.append((before, after, "cykl — treść wróciła pod tę tożsamość"))
            continue
        zapisane = istniejace.get(before)
        if zapisane == after:
            # Ogniwo już jest — i liczy się TU, przed rozgałęzieniem na DRY/apply. Inaczej DRY
            # meldowałby „oznaczyłbym 1" na bazie, w której nie ma czego oznaczać, a raport
            # przed przebiegiem na żywej bazie zawyżałby zakres o wszystko, co już zrobiono.
            s.already += 1
            continue
        if zapisane is not None and zapisane != after:
            # DWIE ŚCIEŻKI, DWIE NASTĘPCZYNIE: ta sama treść leżała pod dwiema ścieżkami i każda
            # kopia została podmieniona na co innego. Model trzyma JEDNO ogniwo na klatkę, więc
            # drugiego nie da się zapisać bez zgubienia pierwszego — zostawiamy ogniwo starsze
            # (jest już faktem w bazie) i meldujemy. Klinga na ten stan rzuca `ValueError`
            # (EXPECT: wołający, który zna mapę, nie ma prawa tu trafić) — pass zna mapę i odsiewa.
            s.conflicts += 1
            s.refused.append((before, after, f"ogniwo zajęte przez frame:{zapisane}"))
            continue
        s.pairs.append((before, after))     # dopiero TU: para, która przeszła wszystkie strażniki
        if not apply:
            s.marked += 1
            continue
        if repo.mark_superseded(con, frame_id=before, superseded_by=after, now=now, actor=actor):
            s.marked += 1
        else:
            # Klinga odmówiła po SWOIM odczycie pod lockiem: albo oznaczono już wcześniej
            # (idempotencja), albo kopia wróciła między raportem a zapisem (TOCTOU).
            if _alive(con, before):
                s.alive += 1
                s.refused.append((before, after, "kopia wróciła w trakcie przebiegu"))
            else:
                s.already += 1
    return s


def pending_transfer(con):
    """Klatki zastąpione, których FAKT CZŁOWIEKA jeszcze nie przeszedł na następczynię (R4).

    To jest predykat KUBEŁKA PODMIANY — kolejka roboty, nie lista zdarzeń. Wchodzi do niej para,
    w której stara klatka niesie werdykt ręki, a następczyni tego faktu jeszcze nie ma. Wychodzi
    z niej dwiema drogami, obie poprawne: gestem przeniesienia albo tym, że następczyni przemówiła
    sama (kartą w pliku, xrefem, regionem, drugim gestem, własnym zeznaniem o sprzęcie).

    DWIE OSIE, JEDEN KUBEŁEK (R1) — bo jeden gest przenosi oba fakty i jedna kolejka ma je
    pokazywać. Predykaty osi są RÓŻNE i to wynika z kolumn, nie z gustu: `object_source` bywa
    niepuste od automatu, więc guard pyta o niepustość; `config_source` zapisuje wyłącznie ręka
    (0015), więc guard pyta o CAŁĄ oś (`config_id IS NULL AND config_source IS NULL`) — inaczej
    para z configiem policzonym z nagłówka wisiałaby w kubełku bez wyjścia. Lustro tych warunków
    stoi w `repo.transfer_human_facts`; rozjazd tych dwóch miejsc znaczy kubełek, którego gest nie
    umie opróżnić — pinuje to test.

    KUBEŁEK JEST DZIŚ PUSTY I TO JEST WYNIK, NIE BRAK: jedyna zastąpiona klatka archiwum (15958)
    ma `object_source NULL` i `config_source NULL`, więc nie ma czego przenosić. Kolejka mówi „zero
    roboty", a nie „nic się nie stało" — te dwie rzeczy odróżnia `orphans` obok.

    TRZECIA OŚ (0809): **werdykty rodowodu stosu**, w których zastąpiona klatka jest WEJŚCIEM.
    Wyjście z kubełka jest tu takie samo jak na dwóch pozostałych: gest przeniesienia albo własny
    werdykt ręki po stronie następczyni. Rola GŁOWY integracji do kubełka nie wchodzi — ponownie
    zapisany master jest nowym przetworzeniem, nie tą samą klatką (granica z `transfer_human_facts`).

    ODSIEW OSI ROBI SIĘ W PYTHONIE, nie w `WHERE`, i to jest zmiana wobec pierwotnego kształtu:
    trzy warunki w jednym `WHERE` musiałyby powtórzyć te same podzapytania, które pętla i tak liczy
    dla etykiety `co`, a rozjazd DWÓCH kopii tego samego kryterium jest dokładnie tym, przed czym
    ostrzega akapit wyżej. Populacja to klatki zastąpione (dziś 2 na 16 797), więc pełne przejście
    po nich nic nie kosztuje, a kryterium ma jedno miejsce.

    Zwraca `[(stara, nowa, co), …]`, gdzie `co` = osie do przeniesienia (`obiekt` / `config` /
    `rodowod` i ich sumy) — raport ma mówić, CZEGO gest dotyczy, nie tylko że coś czeka."""
    rows = con.execute(
        "SELECT f.id, f.superseded_by, f.object_source, f.config_source, f.config_id, "
        "       n.object_source AS n_obj_src, n.config_source AS n_cfg_src, "
        "       n.config_id AS n_cfg, "
        "       (SELECT count(*) FROM integration_input ii "
        "         WHERE ii.input_frame_id = f.id AND ii.asserted_by = 'user' "
        "           AND NOT EXISTS (SELECT 1 FROM integration_input jj "
        "                            WHERE jj.integration_id = ii.integration_id "
        "                              AND jj.input_frame_id = n.id "
        "                              AND jj.asserted_by = 'user')) AS rodowod_n "
        "FROM frame f JOIN frame n ON n.id = f.superseded_by "
        "WHERE f.superseded_by IS NOT NULL ORDER BY f.id").fetchall()
    transferowalne = set(TRANSFERABLE_OBJECT_SOURCES)
    lepkie = set(repo.STICKY_CONFIG_SOURCES)
    out = []
    for r in rows:
        osie = []
        if r["object_source"] in transferowalne and r["n_obj_src"] is None:
            osie.append("obiekt")
        if (r["config_source"] in lepkie and r["config_id"] is not None
                and r["n_cfg_src"] is None and r["n_cfg"] is None):
            osie.append("config")
        if r["rodowod_n"]:
            osie.append("rodowod")
        if osie:
            out.append((r["id"], r["superseded_by"], "+".join(osie)))
    return out


def orphans(con):
    """Sieroty NIEROZSTRZYGNIĘTE — klatka bez ŻADNEJ lokacji i bez `superseded_by`.

    To jest predykat bramki G1-7 i przyszłego kubełka podmiany: sierota z ogniwem jest
    WYJAŚNIONA (wiadomo, kto niesie jej plik), sierota bez ogniwa to otwarte pytanie.
    Sama sierota z bazy NIE ZNIKA (D-DR-4) — kasowanie klatki byłoby drugim wyjątkiem C3,
    a wyjątek ma pozostać wyjątkiem."""
    return [r["id"] for r in con.execute(
        "SELECT f.id FROM frame f WHERE f.superseded_by IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id) ORDER BY f.id")]
