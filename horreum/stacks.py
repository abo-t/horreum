"""RODOWÓD GOTOWYCH STOSÓW — co weszło w ten obraz (segment I-2c, paczka P-I). Siostra `lineage`.

`lineage` (C4) odpowiada „czym skalibrowano tę klatkę", ten moduł — „z czego zrobiono ten stos".
Obie osie łączy kształt (Qt-wolne, zapis wyłącznie przez `repo`, SELECT literałem, idempotencja na
UNIQUE, kubełki „czego nie wiemy"), ale różni je ŹRÓDŁO PEWNOŚCI i to jest sedno projektu:

  * kalibrator wylicza się z PRZEPISU, który obie strony niosą w nagłówku — wynik jest faktem;
  * wejścia stosu wylicza OKNO CZASU mastera, a to jest KANDYDAT, nie fakt. Dowieść go potrafi
    tylko `PixInsight:ProcessingHistory` (zeznanie pliku o samym sobie), i to na mniejszości
    plików. Stąd trójstan `asserted_by` (`history` / `window` / `user`) i strażniki niżej.

DLACZEGO NIE DOPASOWUJEMY PO NAZWACH, skoro historia niesie ścieżki wejść: zmierzone 0/36 —
historia wskazuje dysk roboczy i nazwy WBPP, archiwum trzyma nazwy z akwizycji. Historia służy
więc do WERYFIKACJI zbioru wybranego oknem (`resolve.stack.inputs_contained` porównuje wielozbiór
temperatur z nazw WBPP z temperaturami klatek okna), nie do wskazania klatek.

TRZY STRAŻNIKI — każdy gasi konkretną, ZMIERZONĄ nieprawdę (brief P-I §4.2):
  1. **okno zdegenerowane** (`DATE-END ≈ DATE-OBS + EXPTIME`) → ZERO relacji. 23 z 84 masterów
     starszego rocznika opisuje nagłówkiem JEDNĄ klatkę; bez tego strażnika stos dostałby jeden
     sub i wyglądałby wiarygodnie. Cicha nieprawda jest gorsza niż brak odpowiedzi.
  2. **rozjazd z historią** → ZERO relacji. Gdy plik zeznał, z czego powstał, a okno wybrało inny
     zbiór, to okno się MYLI — a nie historia.
  3. **okna nierozłączne** (43 pary tej samej półki, reprocessingi tej samej nocy) → `ambiguous=1`.
     Relacje zostają, ale most do planera (I-2e) MUSI liczyć taki sub raz.

Czas idzie przez `naming.header_dt` (SPOT parser ISO) — NIGDY po stringu: master zapisuje
`…02.608`, klatka `…02.6075262`, więc porządek leksykalny gubi pierwszy sub okna. Filtr i teleskop
porównujemy po OSIACH, nie po surowych napisach nagłówka: `frame.filter_canon` (resolver, oś
kind-agnostyczna — master dostaje ją tak samo jak light) i `telescope_canonical` (kanon po
scaleniach). Inaczej naprawa `ED`→`ED120R` rozspójniłaby rodowód ze wszystkim, co repo wie.

KROK ZBIORCZY PO `group` I `resolve` — tak jak `lineage` idzie po `calibrate`: dobór stoi na osi
obiektu i osi teleskopu, więc puszczony przed nimi widziałby same `no_object`.

ODCZYT PLIKU: historia mieszka w XML-u nagłówka XISF, którego baza nie lustruje (`cards` niosą
karty FITS, nie własności PixInsighta). Ten moduł czyta ją więc z dysku — READ-ONLY, sam nagłówek
(`scan.read_xisf_meta_full`), bez sekcji danych. Plik nieosiągalny nie jest błędem przebiegu:
stos schodzi wtedy na ścieżkę okna i jest to POLICZONE (`history_unread`), nie przemilczane.
"""
import json
from dataclasses import dataclass, field

from . import repo
from .hashing import sha1_of_set
from .naming import header_dt
from .resolve import stack as rstack
from .resolve._coerce import _to_float

# Powody, dla których stos NIE dostaje wejść. Wartości = tokeny CHECK-a migracji 0012 (baza jest
# ostatnią bramką słownika, jak przy `target_plan.status`), proza należy do powierzchni.
REASON_DEGENERATE = "degenerate_window"
REASON_MISMATCH = "history_mismatch"
REASON_NO_OBJECT = "no_object"
REASON_NO_WINDOW = "no_window"
REASON_NO_CANDIDATES = "no_candidates"
REASON_TELESCOPE = "telescope_mismatch"


@dataclass
class StackLineageSummary:
    """Zliczenia przebiegu (QUIET), tym samym podziałem co `LineageSummary`: `linked` = ile
    integracji MA rodowód, `linked_new` = delta zapisu (idempotentny re-run daje 0), `reasons` =
    kubełki „nie wiem".

    `linked`/`reasons` liczy PLAN, nie zapytanie o stan — i to jest różnica, którą trzeba trzymać
    w głowie przy czytaniu bramki: domykają one populację (`linked + suma(reasons) == stacks`),
    czyli mówią, co automat POTRAFIŁ ustalić w tym przebiegu. Jedyny wyjątek to stos pominięty
    strażnikiem 4 — tam plan jest niewiarygodny, więc źródło bierzemy ze STANU. `inputs` liczymy
    zapytaniem, bo werdykt ręki zmienia tabelę, nie plan."""
    stacks: int = 0
    linked: int = 0            # integracje z co najmniej jednym wejściem
    inputs: int = 0            # STAN: wierszy `integration_input`
    linked_new: int = 0        # delta: realnie zapisane relacje tego przebiegu
    unlinked: int = 0          # delta: relacje zdjęte przez reconcile
    by_assert: dict = field(default_factory=dict)   # 'history'/'window' -> ile integracji
    ambiguous: int = 0         # integracje z oknem nierozłącznym (patrz strażnik 3)
    telescope_mismatch: int = 0    # master zeznaje inny teleskop niż klatki jego okna
    history_unread: int = 0    # plik nieosiągalny/nieczytelny (błąd odczytu ALBO brak lokacji)
    kept_unread: int = 0       # gotowy rodowód ZOSTAWIONY nietknięty, bo zeznania nie dało się
                               # przeczytać — delta zapisu jest wtedy zerowa Z WYBORU, nie z braku
                               # zmian, i bez tego licznika wyglądałaby jak idempotencja
    reasons: dict = field(default_factory=dict)     # powód -> licznik (integracje bez wejść)


def _bump(d, key):
    d[key] = d.get(key, 0) + 1


def _masters(con):
    """Klatki stosów z materiałem zeznania. `telescope_id` bierzemy z KANONU osi (widok
    `telescope_canonical`), więc scalenie teleskopów przenosi rodowód razem ze sprzętem."""
    return con.execute(
        "SELECT f.id AS frame_id, f.object_id AS object_id, f.filter_canon AS filter_canon, "
        "h.raw_json AS raw_json, tc.canon_id AS telescope_id, "
        "(SELECT l.path FROM location l WHERE l.frame_id = f.id AND l.present = 1 "
        " ORDER BY l.id LIMIT 1) AS path "
        "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "WHERE f.kind = 'master_light' ORDER BY f.id").fetchall()


def _window_candidates(con, *, object_id, exptime):
    """Lighty tego obiektu o tej ekspozycji — SUROWY materiał okna (czas/filtr/teleskop przycina
    Python, bo każde z tych porównań ma własną regułę: parser ISO, normalizacja filtra, kanon osi).

    `exptime` porównywane w SQL, bo to jedyny warunek, który jest zwykłą równością liczby —
    wołający podaje je JUŻ SKOERCOWANE do float (patrz `_plan`), a nie surowe zeznanie stosu.

    TEMPERATURA IDZIE Z `ccd_temp` (POMIAR) I TAK MA BYĆ — to wynik pomiaru, nie przeoczenie.
    Nazwa wejścia WBPP niesie temperaturę ZMIERZONĄ, nie nastawę: na 6 stosach z historią test
    tożsamości (`resolve.stack.inputs_contained`) przechodzi na `ccd_temp` 6/6, a na `set_temp`
    0/6 — nastawa jest stała (−10,0), gdy deklarowane wartości rozkładają się −10,1…−9,6.
    Podmiana na `header.set_temp` zamieniłaby wszystkie dowiedzione rodowody w `history_mismatch`.
    (Standing „SET-TEMP jest osią, nie pomiar" dotyczy PRZEPISU KALIBRACJI — innej osi niż ta.)"""
    return con.execute(
        "SELECT f.id AS frame_id, f.filter_canon AS filter_canon, h.date_obs AS date_obs, "
        "h.ccd_temp AS ccd_temp, tc.canon_id AS telescope_id "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "WHERE f.kind = 'light' AND f.object_id = ? AND h.exptime = ? "
        "AND h.date_obs IS NOT NULL ORDER BY f.id",
        (object_id, exptime)).fetchall()


def _in_window(rows, *, start, end, filter_canon, telescope_id):
    """Przytnij kandydatów oknem czasu i osiami → `(wybrane, rozjazd_teleskopu)`.

    Oś, której master NIE ZNA (filtr/teleskop puste — zmierzone: `TELESCOP` w 83 z 85, `FILTER`
    w 84 z 85), NIE zawęża doboru: nieznane nie może udawać warunku.

    TELESKOP ROZSTRZYGA WARUNKOWO — i to jest wniosek z POMIARU, nie z ostrożności. Na realnym
    archiwum (81 niepustych okien) zbiór kandydatów okazał się teleskopowo JEDNORODNY w 81 na 81
    przypadków: ta oś nigdy nie wybierała MIĘDZY klatkami okna, umiała tylko odrzucić wszystkie.
    A odrzucała je w 7 przypadkach, w których master niesie kartę PRZESTARZAŁĄ albo śmieciową
    (`ED` — wartość naprawioną już w archiwum writebackiem; `EQMOD HEQ5/6` — nazwa MONTAŻU).
    Reguła jest więc taka:

      * są kandydaci z teleskopu mastera → bierzemy WYŁĄCZNIE ich (oś rozstrzyga, gdy umie);
      * okno jednorodne, ale z INNEGO teleskopu → bierzemy je i podnosimy `rozjazd`, bo to szew
        dwóch zeznań o tej samej nocy, a nie dwa różne zestawy klatek. Relacja i tak jest
        KANDYDATEM (`asserted_by='window'`), więc nic nie udaje faktu, a powierzchnia dostaje
        materiał do naprawy karty — dokładnie tej, którą archiwum już przeszło;
      * okno MIESZA teleskopy i żaden nie jest masterowy → nie ma czym rozstrzygnąć, zero relacji.

    Wariant „twardy" (odmowa zawsze) kosztowałby dziś 7 rodowodów i nazwałby je `no_candidates`,
    czyli nieprawdą: kandydaci byli, odrzuciła ich oś.

    MASTER, KTÓRY SAM NIE ZNA TELESKOPU, NIE FLAGUJE ROZJAZDU — świadoma granica, nie przeoczenie:
    nie ma czego z czym rozjechać. Okno mieszające wtedy dwa teleskopy weszłoby w całości bez
    ostrzeżenia; zmierzone na realnym archiwum 0/128, więc granica zostaje NAZWANA, a nie obłożona
    kodem na populację zerową. Wraca do rozważenia, gdy pojawi się pierwszy taki przypadek.

    Okno jest PÓŁOTWARTE `[start, end)`: `DATE-END` to koniec ostatniej ekspozycji, więc klatka
    ZACZYNAJĄCA się w tej chwili należy do następnej serii, nie do tej. Zmierzone: 0 wejść na 128
    stosach siada dokładnie na granicy, więc dziś to no-op — i o to chodzi, bo granicę domyka się,
    póki jest pusta, a nie po pierwszym cudzym subie wciągniętym do obrazu."""
    okno = []
    for r in rows:
        t = header_dt(r["date_obs"])
        if t is None or not (start <= t < end):
            continue
        if filter_canon and r["filter_canon"] != filter_canon:
            continue
        okno.append(r)
    if telescope_id is None or not okno:
        return okno, False
    zgodne = [r for r in okno if r["telescope_id"] == telescope_id]
    if zgodne:
        return zgodne, False
    return (okno, True) if len({r["telescope_id"] for r in okno}) == 1 else ([], True)


def _shelf_ambiguous(plany):
    """Zbiór klatek mastera, których okno NAKŁADA się na okno innego stosu tej samej PÓŁKI
    (obiekt+filtr+ekspozycja+teleskop). Fakt 20 briefu: 43 takie pary to reprocessingi tej samej
    nocy (`WBPP` vs `WBPP_nowy`) — ten sam sub wchodzi wtedy do dwóch integracji, więc
    `integration_input` jest POKRYCIEM, nie podziałem. Oznaczamy OBIE strony pary."""
    ambi = set()
    polki = {}
    for p in plany:
        if p["start"] is None or p["end"] is None:
            continue
        polki.setdefault(p["shelf"], []).append(p)
    for grupa in polki.values():
        for i, a in enumerate(grupa):
            for b in grupa[i + 1:]:
                if a["start"] <= b["end"] and b["start"] <= a["end"]:
                    ambi.add(a["frame_id"])
                    ambi.add(b["frame_id"])
    return ambi


def _read_history_xml(path):
    """Tekst XML nagłówka XISF spod ścieżki — READ-ONLY, sam nagłówek. Import lokalny, bo `scan`
    ciągnie astropy, a ten moduł bywa wołany tam, gdzie ładowanie astropy jest zbędne.

    Format INNY niż XISF oddaje `None`, a nie wyjątek: historia PixInsighta jest własnością XISF-a
    i jej brak w FITS-ie nie jest awarią odczytu. Bez tego rozdziału stos zapisany jako FITS
    wpadłby do licznika „historia nieodczytana" i kłamał o dostępności pliku (dziś zmierzone
    128/128 stosów to `.xisf`, ale licznik ma mierzyć to, co mierzy)."""
    from .scan import XISF_SUFFIXES, read_xisf_meta_full
    if not str(path).lower().endswith(XISF_SUFFIXES):
        return None
    return read_xisf_meta_full(path).xml_bytes.decode("utf-8", "replace")


def _plan(con, row, *, xml_reader):
    """Materiał decyzji dla JEDNEJ klatki stosu — bez zapisu (czysta faza, testowalna osobno)."""
    header = json.loads(row["raw_json"]) if row["raw_json"] else {}
    xml, unread = None, False
    if row["path"]:
        try:
            xml = xml_reader(row["path"])
        except Exception:              # plik zniknął/leży na odłączonym dysku — patrz docstring
            unread = True
    else:
        # BRAK OBECNEJ LOKACJI TO TEN SAM STAN, co błąd odczytu: pliku nie ma pod ręką, więc jego
        # zeznania NIE ZNAMY. Rozdzielanie tych dwóch przypadków dawało licznik, który milczał
        # o połowie populacji — a wołający podejmuje na nim decyzję „nie ruszaj gotowego rodowodu".
        unread = True
    t = rstack.read_testimony(header, xml)
    start, end = t.window_start, t.window_end
    # KOERCJA PRZY WEJŚCIU, nie w SQL-u: XISF oddaje KAŻDĄ kartę jako tekst (`_put(header,
    # keyword, value_raw)`), więc `EXPTIME` stosu to `'600.00'`, a `header.exptime` klatki to REAL.
    # Porównanie działałoby i tak — SQLite nakłada powinowactwo kolumny na parametr tekstowy — ale
    # stałoby na regule silnika zamiast na naszej decyzji, a półka grupująca po surowej wartości
    # rozdzieliłaby `'600.00'` od `600.0` bez śladu.
    exptime = _to_float(t.exptime)
    plan = {
        "frame_id": row["frame_id"], "testimony": t, "start": start, "end": end,
        "history_unread": unread, "inputs": [], "asserted_by": None, "reason": None,
        "telescope_mismatch": False,
        "shelf": (row["object_id"], row["filter_canon"], exptime, row["telescope_id"]),
    }
    if row["object_id"] is None:
        plan["reason"] = REASON_NO_OBJECT
        return plan
    if start is None or end is None or t.degenerate:
        # Okno bez końca i okno o długości jednej klatki to ten sam brak: nie ma czym wybierać.
        plan["reason"] = REASON_NO_WINDOW if start is None or end is None else REASON_DEGENERATE
        return plan
    kand, rozjazd = _in_window(
        _window_candidates(con, object_id=row["object_id"], exptime=exptime),
        start=start, end=end, filter_canon=row["filter_canon"], telescope_id=row["telescope_id"])
    plan["telescope_mismatch"] = rozjazd
    if not kand:
        plan["reason"] = REASON_TELESCOPE if rozjazd else REASON_NO_CANDIDATES
        return plan
    if t.rows is None:
        plan["inputs"], plan["asserted_by"] = kand, "window"
        return plan
    ok, _poza, _nadwyzka = rstack.inputs_contained(t, [r["ccd_temp"] for r in kand])
    if not ok:
        plan["reason"] = REASON_MISMATCH        # strażnik 2: myli się OKNO, nie zeznanie pliku
        return plan
    plan["inputs"], plan["asserted_by"] = kand, "history"
    return plan


def run_stack_lineage(con, *, now, actor="stacks", xml_reader=None, progress=None):
    """Przebieg rodowodu stosów — idempotentny: drugi przebieg na niezmienionych danych daje ZERO
    nowych wierszy i ZERO eventów (UNIQUE z 0012 trzyma idempotencję, nie kod).

    Kolejność faz jest istotna: NAJPIERW plan dla wszystkich stosów (bo nierozłączność okien to
    fakt o PARZE integracji, nie o pojedynczej), POTEM zapis. `xml_reader` wstrzykiwalny — testy
    podają zeznanie wprost, produkcja czyta nagłówek z dysku."""
    s = StackLineageSummary()
    reader = xml_reader if xml_reader is not None else _read_history_xml
    rows = _masters(con)
    s.stacks = len(rows)
    plany = []
    for i, row in enumerate(rows, 1):
        plany.append(_plan(con, row, xml_reader=reader))
        if progress is not None:
            progress(i, len(rows), row["frame_id"])
    ambi = _shelf_ambiguous(plany)

    for p in plany:
        t = p["testimony"]
        s.history_unread += p["history_unread"]
        # STRAŻNIK 4 — decyzja PRZED policzeniem i PRZED zapisem CZEGOKOLWIEK. Reguła brzmi „bez
        # zeznania nie dotykamy tego stosu", więc obejmuje GŁOWĘ integracji tak samo jak wiersze.
        # Guard postawiony za `upsert_integration` chronił tylko wiersze i przez to sam produkował
        # dwa defekty:
        #   * głowa dostawała `unresolved_reason` z planu, którego wiersze właśnie ODMÓWIŁ
        #     zastosować (powód wynika z BAZY — obiekt, okno, kandydaci, teleskop — więc powstaje
        #     i bez pliku), a stare wiersze zostawały → stan łamał inwariant bramki §5.14
        #     „powód wyklucza wejścia automatu";
        #   * `t.rows`/`t.tool` przy nieodczytanym pliku są `None`, więc jeden przebieg offline
        #     KASOWAŁ fakty zeznania (`declared_rows`, `tool`, drizzle) przy wierszach `history`
        #     zachowanych obok — panel mówił „plik zeznał" i nie umiał powiedzieć, ile deklaruje.
        # Liczniki idą wtedy ze STANU, nie z planu: rodowód istnieje, tylko nie myśmy go teraz
        # ustalili. `ambiguous`/`telescope_mismatch` świadomie pomijamy — to fakty TEGO przebiegu,
        # a ten przebieg o tym stosie niczego nie rozstrzygnął.
        if p["history_unread"]:
            zrodlo = _zapisane_zrodlo(con, p["frame_id"])
            if zrodlo is not None:
                s.kept_unread += 1
                s.linked += 1
                _bump(s.by_assert, zrodlo)
                continue
        if p["reason"]:
            _bump(s.reasons, p["reason"])
        else:
            s.linked += 1
            _bump(s.by_assert, p["asserted_by"])
        s.ambiguous += p["frame_id"] in ambi
        # ROZJAZD TELESKOPU LICZYMY TYLKO TAM, GDZIE RODOWÓD POWSTAŁ — bo tylko tam jest FLAGĄ
        # („relacje są, ale karta się nie zgadza"). Rozjazd, który skończył się ODMOWĄ, siedzi już
        # w `reasons['telescope_mismatch']`; wspólny licznik meldował go dwa razy i kazał raportowi
        # mówić „karta do naprawy: N" o stosach, przy których nie zapisano niczego.
        if p["telescope_mismatch"] and not p["reason"]:
            s.telescope_mismatch += 1
        wejscia = [r["frame_id"] for r in p["inputs"]]
        odcisk = _fingerprint(con, wejscia)
        iid, _ = repo.upsert_integration(
            con, master_frame_id=p["frame_id"], integ_hash=odcisk, tool=t.tool,
            window_start=p["start"].isoformat() if p["start"] else None,
            window_end=p["end"].isoformat() if p["end"] else None,
            declared_rows=t.rows,
            drizzle_inputs=sum(1 for x in t.inputs if x.has_drizzle) if t.rows is not None else None,
            disabled_inputs=sum(1 for x in t.inputs if not x.enabled) if t.rows is not None else None,
            degenerate=int(t.degenerate), ambiguous=int(p["frame_id"] in ambi),
            telescope_mismatch=int(p["telescope_mismatch"]),
            unresolved_reason=p["reason"], now=now, actor=actor)
        # Tu docierają WYŁĄCZNIE stosy, o których wolno nam pisać: albo zeznanie było czytelne,
        # albo rodowodu jeszcze nie ma (świeża integracja nie ma czego stracić, a milczenie
        # łamałoby „bez wejść ZAWSZE niesie powód"). Strażnik 4 stoi wyżej, przed `upsert`.
        s.linked_new += _zapisz_wejscia(con, iid, wejscia, p["asserted_by"], now=now, actor=actor)
        s.unlinked += _reconcile(con, iid, wejscia, now=now, actor=actor)

    # `inputs` liczymy ze STANU, nie z planu (lustro `LineageSummary.linked`): odrzucenie ręką
    # zostawia wiersz w tabeli, ale ten sub w obraz NIE wszedł — plan wciąż widzi go jako kandydata,
    # więc rachunek z planu zawyżałby o każdy werdykt „nie". `linked`/`reasons` zostają Z PLANU,
    # bo to one domykają partycję populacji (człowiek wykluczający WSZYSTKIE wejścia nie zmienia
    # tego, co automat potrafił ustalić — a bramka pyta właśnie o to).
    s.inputs = con.execute(
        "SELECT count(*) FROM integration_input WHERE excluded = 0").fetchone()[0]
    s.reasons = dict(sorted(s.reasons.items()))
    repo.flag_stack_lineage_summary(con, sorted(s.reasons.items()), now, actor=actor,
                                    kept_unread=s.kept_unread)
    return s


def _fingerprint(con, frame_ids):
    """Odcisk ZBIORU wejść — po `sha1_data`, nie po `id`: tożsamość treści przeżywa przebudowę
    bazy, a numer wiersza nie. FAKT o bieżącym dopasowaniu (§4.1), nigdy klucz rekordu."""
    if not frame_ids:
        return None
    return sha1_of_set(
        r["sha1_data"] for fid in frame_ids
        for r in con.execute("SELECT sha1_data FROM frame WHERE id = ?", (fid,)))


def _zapisane_zrodlo(con, master_frame_id):
    """Źródło pewności JUŻ ZAPISANEGO rodowodu tego stosu — albo `None`, gdy rodowodu nie ma.
    Pytanie o STAN, nie o plan: rozstrzyga, czy wolno go ruszyć przebiegowi, który nie przeczytał
    zeznania pliku, i czym go wtedy policzyć w podsumowaniu.

    Wiersze automatu są jednorodne (plan nadaje jedno źródło całej integracji), więc jedyna możliwa
    mieszanka to automat + werdykty ręki. Sortowanie stawia NIE-`user` pierwszy, bo podsumowanie
    pyta „na czym stoi ten rodowód", a nie „czy ktoś go dotknął"; sam `user` wychodzi tylko wtedy,
    gdy innych wierszy nie ma. Pytamy po KLATCE MASTERA, bo wołający nie zna jeszcze `integration.id`
    — i nie ma go poznać, skoro właśnie decyduje, czy w ogóle pisać."""
    row = con.execute(
        "SELECT ii.asserted_by AS zrodlo FROM integration_input ii "
        "JOIN integration i ON i.id = ii.integration_id "
        "WHERE i.master_frame_id = ? ORDER BY (ii.asserted_by = 'user'), ii.asserted_by LIMIT 1",
        (master_frame_id,)).fetchone()
    return None if row is None else row["zrodlo"]


def _zapisz_wejscia(con, integration_id, frame_ids, asserted_by, *, now, actor):
    if not frame_ids:
        return 0
    return sum(repo.link_integration(con, integration_id=integration_id, input_frame_id=fid,
                                     asserted_by=asserted_by, now=now, actor=actor)
               for fid in frame_ids)


def _reconcile(con, integration_id, frame_ids, *, now, actor):
    """Zdejmij wejścia, których bieżące dopasowanie już nie wskazuje (§4.2). Relacje `user`
    pomija sama klinga — automat nie cofa rozstrzygnięcia ręki."""
    stare = [r["input_frame_id"] for r in con.execute(
        "SELECT input_frame_id FROM integration_input WHERE integration_id = ?", (integration_id,))]
    zbedne = set(stare) - set(frame_ids)
    return sum(repo.unlink_integration_input(con, integration_id=integration_id, input_frame_id=fid,
                                             now=now, actor=actor)
               for fid in sorted(zbedne))


def inputs_of(con, master_frame_id):
    """READ-ONLY „co weszło w ten obraz": wiersze rodowodu stosu ze ścieżką klatki wejściowej
    i źródłem pewności. Materiał pod powierzchnię I-2d i raport CLI — bez zapisu."""
    return con.execute(
        "SELECT ii.input_frame_id AS input_frame_id, ii.asserted_by AS asserted_by, "
        "ii.excluded AS excluded, "
        "(SELECT l.path FROM location l WHERE l.frame_id = ii.input_frame_id AND l.present = 1 "
        " ORDER BY l.id LIMIT 1) AS path "
        "FROM integration_input ii JOIN integration i ON i.id = ii.integration_id "
        "WHERE i.master_frame_id = ? ORDER BY ii.input_frame_id",
        (master_frame_id,)).fetchall()
