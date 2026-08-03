r"""SZCZEBEL ŚCIEŻKI — propozycje, potwierdzanie, odwracalność (S2, brief obiektów własnych).

Bramki §4, których właścicielem jest ten plik:
  * **1b** — PRZEBIEG NIE PISZE DO OSI. Rdzeń wariantu B: implementacja zapisująca „przy okazji"
    przeszłaby wszystkie bramki liczbowe wariantu A, więc ta jest jedyną, która ją zaczerwieni.
  * **4** — kształt sprzętowy odrzucony, rozszczepienie kanonu widoczne, ZERO aliasów ze ścieżki
    (człon RÓŻNICOWY + przypadek DODATNI + pin kontraktu).
  * **11 (człon szósty, R-S1-4)** — klatka nazwana ŚCIEŻKĄ wraca do NULL-a przy edycji słownika.
    Bez tego członu usunięcie `LMC` zostawiłoby 36 klatek przypiętych do obiektu, którego słownik
    już nie zna, przy `§5.9` ZIELONEJ.
  * **16** — parytet DRABINY: te same MIEJSCA WOŁANIA, z JAWNĄ listą oczekiwanych różnic.
    „Ta sama funkcja daje ten sam wynik" byłoby tautologią, która nie może się zaczerwienić.

Populacja fikstury naśladuje archiwum: RAW-owy light bez karty `OBJECT` (EXIF jej nie zna), jedna
obecna kopia, nazwa obiektu WYŁĄCZNIE w folderze."""
import json

import pytest

from horreum import audit, db, repo, resolver
from horreum.gui import queries
from horreum.resolve import objects as ro
from test_gui_queries_object import _partycja       # równanie partycji ma JEDEN dom

NOW = "2026-08-03T12:00:00Z"
R = "R:\\ASTRO_"


def _baza(items):
    """`items` = [(ścieżka, object_raw|None, filetype)] → baza z klatkami-lightami i jedną obecną
    kopią każda. Surowy SQL (fikstura, nie ingest) — tak jak w `test_objects_own`."""
    con = db.connect(":memory:")
    db.migrate(con)
    for i, (path, raw, filetype) in enumerate(items, start=1):
        con.execute(
            "INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
            "VALUES (?, 'light', ?, ?, ?)", (i, filetype, f"sha{i}", NOW))
        con.execute("INSERT INTO header(frame_id, object_raw, raw_json) VALUES (?,?,'{}')",
                    (i, raw))
        con.execute(
            "INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'VOL', ?, 1)",
            (i, path))
    con.commit()
    return con


def _lmc(n=2):
    return [(rf"{R}\LIGHTS\LMC\A7R3_105\OSC\_7R3880{i}.ARW", None, "raw") for i in range(n)]


def _ev(con, verb):
    return con.execute("SELECT count(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


# ═══════════════════════════════════════════════════ §4/1b — PRZEBIEG NIE PISZE DO OSI OBIEKTU


def test_przebieg_liczy_propozycje_i_NIE_pisze():
    """Rdzeń wariantu B. Pełny `run_resolver` na bazie z RAW-ami: zero klatek z obiektem, zero
    eventów przypisania, ZERO obiektów — a licznik propozycji > 0."""
    con = _baza(_lmc(3))
    s = resolver.run_resolver(con, NOW)
    assert s.path_proposed_frames == 3 and s.path_proposed_names == 1
    assert con.execute("SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0] == 0
    assert _ev(con, "object.assigned") == 0
    assert con.execute("SELECT count(*) FROM object").fetchone()[0] == 0


def test_drugi_przebieg_to_cisza_takze_ze_szczeblem_sciezki():
    """Szczebel liczy przy każdym przebiegu — i ma to być CISZA w dzienniku, nie tylko w bazie."""
    con = _baza(_lmc(2))
    resolver.run_resolver(con, NOW)
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    resolver.run_resolver(con, NOW)
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed


def test_propozycja_jest_STICKY_wobec_klatki_z_obiektem():
    """Klatka, która obiekt JUŻ ma, nie jest kandydatem — inaczej pierwszy przebieg po przenosinach
    plików przemalowałby kanon z nowej ścieżki, cicho."""
    con = _baza(_lmc(2))
    con.execute("INSERT INTO object(id, canon, kind) VALUES (7, 'CUDZY', 'own')")
    con.execute("UPDATE frame SET object_id = 7, object_source = 'user' WHERE id = 1")
    con.commit()
    prop = resolver.path_proposals(con)
    assert [p.frame_ids for p in prop] == [(2,)]


def test_klatka_bez_obecnej_kopii_MILCZY():
    """Brak obecnej kopii ⇒ nie ma ścieżki ⇒ szczebel milczy (D-OW-2 pkt 8) — zamiast zgadywać
    z kopii, która zniknęła."""
    con = _baza(_lmc(1))
    con.execute("UPDATE location SET present = 0")
    con.commit()
    assert resolver.path_proposals(con) == ()


def test_zeznanie_naglowka_wyklucza_szczebel():
    """Ścieżka jest świadkiem SŁABSZYM od nagłówka (320 rozjazdów na 13,5 tys. klatek): klatka,
    która ma `object_raw`, nie należy do tej populacji — nawet gdy nagłówka nie da się rozwiązać."""
    con = _baza([(rf"{R}\LIGHTS\LMC\A7R3\OSC\x.ARW", "cos-nieznanego", "raw")])
    assert resolver.path_proposals(con) == ()


def test_format_z_karta_OBJECT_jest_poza_szczeblem():
    """Zakres po FORMACIE, nie po objawie: FITS bez karty ma własną drogę naprawy (karta w PLIKU)
    i własną kotwicę nawrotu, której szczebel nie ma prawa opróżniać naprawą NAZWY."""
    con = _baza([(rf"{R}\LIGHTS\LMC\RC8\L\x.fit", None, "fits")])
    assert resolver.path_proposals(con) == ()


# ═══════════════════════════════════════════════════ §4/3 i §4/4 — kształt kanonu i aliasy


def test_ksztalt_sprzetowy_odrzucony_gole_oznaczenie_przyjete():
    """`C8_2600MC`/`RC8_2600MC`/`A7R3_105`/`OSC`/`L-Pro` na pozycji obiektu to SPRZĘT — odrzucone.
    Gołe `C8` na tej samej pozycji naprawdę oznacza Caldwella — przyjęte (gwarancję daje POZYCJA)."""
    con = _baza([(rf"{R}\LIGHTS\C8_2600MC\OSC\x.ARW", None, "raw"),
                 (rf"{R}\LIGHTS\A7R3_105\OSC\x.ARW", None, "raw"),
                 (rf"{R}\LIGHTS\C8\OSC\x.ARW", None, "raw")])
    assert {p.canon for p in resolver.path_proposals(con)} == {"C8"}


def test_normalizacja_ta_sama_co_dla_naglowka():
    """`Sh2-229`/`IC 405` przechodzą TĘ SAMĄ normalizację co zeznanie nagłówka — szczebel nie ma
    własnej gramatyki (`IC 405` ze spacją daje `IC405`).

    ROZJAZD `Sh2-229` vs `IC405` ZOSTAJE — i to jest pin na DŁUG NAZWANY, nie na poprawność:
    `xref` tych dwóch oznaczeń nie skleja, więc ten sam obiekt nieba ma w bazie dwa kanony i dwie
    pozycje w facecie. Brief mówi wprost, że tego NIE naprawia (to pytanie o `xref`, 308 klatek
    FITS), a bramka rozszczepienia (§4/3) ma go POKAZAĆ, nie ukryć. Zzielenienie tego pinu na
    jeden kanon znaczy, że ktoś ruszył `catalog_xref.json` — wtedy trzeba policzyć skutek na
    tamtych 308 klatkach, a nie tylko tutaj."""
    con = _baza([(rf"{R}\LIGHTS\Sh2-229\RC8\Ha\x.ARW", None, "raw"),
                 (rf"{R}\LIGHTS\IC 405\RC8\Ha\y.ARW", None, "raw")])
    assert {p.canon for p in resolver.path_proposals(con)} == {"IC405", "Sh2-229"}


def test_kanon_NOWY_jest_oznaczony():
    """232 klatki trafiają w 21 kanonów, których w bazie NIE MA — i to te pozycje mają przejść
    przez oko. Falsyfikator: `NGC6960` przy ISTNIEJĄCYCH `NGC6992`/`Veil` jest NOWY, mimo że to
    ten sam obiekt nieba."""
    con = _baza([(rf"{R}\LIGHTS\NGC6960\A7R3\OSC\x.ARW", None, "raw"),
                 (rf"{R}\LIGHTS\NGC7000\A7R3\OSC\y.ARW", None, "raw")])
    con.execute("INSERT INTO object(canon, catalog, kind) VALUES ('NGC6992','NGC','deep_sky')")
    con.execute("INSERT INTO object(canon, catalog, kind) VALUES ('Veil',NULL,'region')")
    con.execute("INSERT INTO object(canon, catalog, kind) VALUES ('NGC7000','NGC','deep_sky')")
    con.commit()
    stan = {p.canon: p.is_new for p in resolver.path_proposals(con)}
    assert stan == {"NGC6960": True, "NGC7000": False}


def test_szczebel_sciezki_NIE_zasiewa_aliasow():
    """§4/4(c) — człon RÓŻNICOWY, nie literałowy: implementacja nadająca `source='path'` tylko
    KLATCE wsypałaby aliasy z `source='header'`, a predykat na `'path'` byłby zielony.

    Przypadek DODATNI w tym samym teście: kanon `LMC` pochodzi z WPISU SŁOWNIKA, więc po
    zatwierdzeniu propozycji zasiew nazw potocznych MUSI zadziałać — i wszystkie te aliasy są
    `curated`, ani jednego innego."""
    con = _baza(_lmc(2))
    przed = con.execute(
        "SELECT count(*) FROM object_alias WHERE source <> 'curated'").fetchone()[0]
    resolver.run_resolver(con, NOW)
    assert con.execute(
        "SELECT count(*) FROM object_alias WHERE source <> 'curated'").fetchone()[0] == przed

    p = resolver.path_proposals(con)[0]
    repo.user_assign_object(con, alias_norm=None, canon=p.canon, catalog=p.catalog, kind=p.kind,
                            frame_ids=list(p.frame_ids), now=NOW, object_source="path")
    resolver.run_resolver(con, NOW)                       # zasiew biegnie dopiero, gdy obiekt JEST
    zrodla = {r[0] for r in con.execute("SELECT DISTINCT source FROM object_alias").fetchall()}
    assert zrodla == {"curated"}
    aliasy = {r[0] for r in con.execute("SELECT alias_norm FROM object_alias").fetchall()}
    assert {"LMC", "LARGEMAGELLANICCLOUD"} <= aliasy


def test_pin_kontraktu_drabiny_ze_sciezki():
    """Wołanie ze ŚCIEŻKI zwraca tożsamość z PUSTYM kluczem aliasu — na PIERWSZYM elemencie pary
    (drugi to `object_id` trafienia aliasu, nie tożsamość).

    OBIE gałęzie, nie jedna: lookup, który NIE trafia (szczebel słownika), i lookup, który TRAFIA
    (szczebel aliasu). Pin na samym `lambda _k: None` przechodziłby przy kontrakcie połowicznym —
    a właśnie tak kontrakt był napisany, dopóki recenzja diffu tego nie pokazała."""
    ident, oid = resolver.resolve_name(lambda _k: None, "LMC", from_path=True)
    assert ident.alias_norm is None and oid is None
    wiersz = {"object_id": 42, "canon": "NGC7000", "catalog": "NGC", "kind": "deep_sky"}
    trafia = lambda _k: wiersz                                                     # noqa: E731
    ident_a, oid_a = resolver.resolve_name(trafia, "cos wlasnego", from_path=True)
    assert (ident_a.canon, ident_a.source, ident_a.alias_norm, oid_a) \
        == ("NGC7000", "alias", None, 42)
    ident2, _ = resolver.resolve_name(lambda _k: None, "LMC")
    assert ident2.alias_norm == "LMC"                     # tryb nagłówka NIETKNIĘTY
    assert resolver.resolve_name(trafia, "cos wlasnego")[0].alias_norm == "COSWLASNEGO"


def test_drabina_oddaje_object_id_tylko_przy_trafieniu_aliasu():
    """Drugi człon krotki mówi „ten obiekt JUŻ ISTNIEJE" — przy każdym innym szczeblu wołający
    sam zakłada obiekt, więc musi tam być None."""
    wiersz = {"object_id": 42, "canon": "NGC7000", "catalog": "NGC", "kind": "deep_sky"}
    ident, oid = resolver.resolve_name(lambda k: wiersz if k == "MOJANAZWA" else None, "moja nazwa")
    assert (ident.canon, ident.source, oid) == ("NGC7000", "alias", 42)
    ident2, oid2 = resolver.resolve_name(lambda _k: None, "NGC 7000")
    assert (ident2.canon, ident2.source, oid2) == ("NGC7000", "header", None)


# ═══════════════════════════════════════════════════ §4/16 — PARYTET DRABINY (jawne różnice)

#: Trójki `(ścieżka, propozycja DIALOGU, kanon SZCZEBLA)` — obie strony pinowane WPROST. Kolumna
#: szczebla nie jest ozdobą: bez niej implementacja, w której szczebel TEŻ żąda dwóch świadków
#: (czyli kasująca różnicę, którą ta tabela opisuje), przechodziła wszystkie wiersze na zielono.
_PARYTET = [
    # zgodni świadkowie — obie powierzchnie mówią TO SAMO
    (rf"{R}\LIGHTS\NGC7635\RC8\Ha\NGC7635_0001.fit", "NGC7635", "NGC7635"),
    (rf"{R}\LIGHTS\LMC\A7R3_105\OSC\LMC_20230323.ARW", "LMC", "LMC"),
    # RÓŻNICA 1 (ŚWIADEK): dialog żąda DRUGIEGO świadka, szczebel nie — nazwy plików z lustrzanki
    # milczą strukturalnie, więc to jest różnica na 707 klatkach minus 31.
    (rf"{R}\LIGHTS\LMC\A7R3_105\OSC\_7R38821.ARW", None, "LMC"),
    (rf"{R}\LIGHTS\NGC1976\RC8\L\x.fit", None, "NGC1976"),
    # zakaz cięcia i marker rodzaju obowiązują OBIE powierzchnie — tu milczą OBIE
    (rf"{R}\LIGHTS\C8_2600MC\OSC\C8_0001.fit", None, None),
    (rf"{R}\CALIBRATION\dark\dark_0001.fit", None, None),
]


@pytest.mark.parametrize("path, dialog_kanon, szczebel_kanon", _PARYTET)
def test_parytet_drabiny_miejsca_wolania(path, dialog_kanon, szczebel_kanon):
    """Porównuje MIEJSCA WOŁANIA (propozycja dialogu vs szczebel przebiegu) przy tym samym trybie.
    Różnice są DWIE i obie są zamierzone — tabela wypisuje je JAWNIE, kolumna po kolumnie:

      1. **ŚWIADEK** — dialog wymaga dwóch zgodnych (pisze do PLIKU), szczebel jednego (proponuje
         do BAZY, odwracalnie).
      2. **`xref`** — dialog oddaje formę SPRZED równoważności (konwencja usera w JEGO pliku,
         D-PD-9), szczebel kanon bazy. Widać ją w wierszu `M42` (osobny test niżej, bo dotyczy
         WARTOŚCI, nie milczenia).

    Reguła czytania: gdzie obie kolumny są niepuste, wartości MUSZĄ się zgadzać — inaczej to nie
    jedna drabina, tylko dwie, które udają jedną."""
    con = _baza([(path, None, "raw")])
    dialog = resolver.path_proposal(con, path)
    szczebel = [p.canon for p in resolver.path_proposals(con)]
    assert dialog == dialog_kanon
    assert szczebel == ([szczebel_kanon] if szczebel_kanon else [])
    if dialog is not None:                       # dialog nie ma prawa mówić tam, gdzie szczebel milczy
        assert szczebel, "dwaj świadkowie bez jednego świadka = dwie różne drabiny"


def test_parytet_roznica_xref_wypisana_jawnie():
    """RÓŻNICA 2: te same dwaj świadkowie, dwie różne WARTOŚCI — i tak ma być."""
    path = rf"{R}\LIGHTS\M42\RC8\Ha\M42_0001.fit"
    con = _baza([(path, None, "raw")])
    assert resolver.path_proposal(con, path) == "M42"                 # do PLIKU: konwencja usera
    assert [p.canon for p in resolver.path_proposals(con)] == ["NGC1976"]   # do BAZY: kanon


# ═══════════════════════════════════════════════════ §4/19 — POWIERZCHNIA POTWIERDZANIA (read-model)


def test_kolejka_pokazuje_propozycje_POZA_partycja():
    """Kubełek propozycji jest PODZBIOREM RAW-owego, więc partycja kolejki NIE MOŻE go dodać —
    inaczej rozspójniłaby się dokładnie o jego liczbę.

    Równanie partycji ma JEDEN dom (`test_gui_queries_object._partycja`) i to stamtąd je bierzemy:
    druga kopia, dopisana w segmencie, który dokłada kubełek, byłaby już o człon uboższa."""
    con = _baza(_lmc(3) + [(rf"{R}\LIGHTS\Orion\A7S1_070\OSC\x.ARW", None, "raw")])
    q = queries.review_queue(con)
    assert q["nameless_raw_count"] == 4                    # cała populacja RAW bez obiektu
    assert (q["path_proposed_names"], q["path_proposed_frames"]) == (1, 3)   # Orion bez propozycji
    assert _partycja(con) == len(queries.review_frame_ids(con))


def test_bledny_slownik_NIE_wywala_kolejki(monkeypatch):
    """Słownik jest plikiem CZŁOWIEKA, a jego edycja operacją WSPIERANĄ — literówka ma zostać
    ZGŁOSZONA, nie wywalić widok tracebackiem przy otwarciu. `None` ≠ `0`: „nie policzono" i „nie
    ma czego liczyć" to dwie różne prawdy, a kubełek udający zero ukryłby błąd assetu na zawsze."""
    con = _baza(_lmc(2))
    assert queries.review_queue(con)["path_proposed_frames"] == 2

    def _wybuch():
        raise ValueError("objects_own.json: rekord bez kanonu `c`")
    monkeypatch.setattr(ro, "load_own_objects", _wybuch)
    ro._own_index_stamped.cache_clear()
    q = queries.review_queue(con)
    assert q["path_proposed_frames"] is None and q["path_proposed_names"] is None
    assert q["nameless_raw_count"] == 2            # reszta kolejki liczy się dalej
    ro._own_index_stamped.cache_clear()


def test_pozycje_grupowane_PO_NAZWIE_z_folderem():
    """707 klatek ⇒ ≈35 pozycji, nie 707. Każda niesie liczbę klatek i FOLDER ŹRÓDŁOWY."""
    con = _baza(_lmc(36))
    prop = resolver.path_proposals(con)
    assert len(prop) == 1
    assert (prop[0].canon, prop[0].n_frames, prop[0].folder) == ("LMC", 36, rf"{R}\LIGHTS\LMC")


def test_zatwierdzenie_pisze_TA_SAMA_klinga_ze_zrodlem_path():
    """Falsyfikator §4/19: klatka zatwierdzona z propozycji ma dawać się cofnąć akcją z S2b —
    a to działa wtedy i tylko wtedy, gdy zapis poszedł tą samą klingą i nadał źródło `path`."""
    con = _baza(_lmc(2))
    p = resolver.path_proposals(con)[0]
    assigned, skipped = repo.user_assign_object(
        con, alias_norm=None, canon=p.canon, catalog=p.catalog, kind=p.kind,
        frame_ids=list(p.frame_ids), now=NOW, object_source="path")
    assert (assigned, skipped) == (2, 0)
    zrodla = {r[0] for r in con.execute(
        "SELECT DISTINCT object_source FROM frame WHERE object_id IS NOT NULL").fetchall()}
    assert zrodla == {"path"}
    assert _ev(con, "object.assigned") == 2 and _ev(con, "object.upserted") == 1
    assert con.execute("SELECT count(*) FROM object_alias").fetchone()[0] == 0
    # po zatwierdzeniu propozycji znikają — kolejka mówi świeżą prawdę
    assert resolver.path_proposals(con) == ()
    assert audit.object_source_audit(con).ok


def test_klinga_odmawia_zrodla_spoza_stalej():
    """EXPECT: literówka w źródle jest po zapisie niewykrywalna, a audyt 5b zaczerwieniłby się
    dopiero na całej bazie."""
    con = _baza(_lmc(1))
    with pytest.raises(ValueError):
        repo.user_assign_object(con, alias_norm=None, canon="LMC", catalog=None, kind="own",
                                frame_ids=[1], now=NOW, object_source="sciezka")
    with pytest.raises(ValueError):                  # pusty klucz to NIE „brak klucza"
        repo.user_assign_object(con, alias_norm="", canon="LMC", catalog=None, kind="own",
                                frame_ids=[1], now=NOW)
    assert con.execute("SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0] == 0


def test_drazenie_dekoruje_id_od_jednego_wlasciciela():
    """Panel drążenia nie ma własnego predykatu populacji — dostaje id-y od `path_proposals`."""
    con = _baza(_lmc(2) + [(rf"{R}\LIGHTS\Orion\A7S1\OSC\x.ARW", None, "raw")])
    ids = [fid for p in resolver.path_proposals(con) for fid in p.frame_ids]
    rows = queries.path_proposal_frames(con, ids)
    assert [r["frame_id"] for r in rows] == ids
    assert rows[0]["n_present"] == 1 and rows[0]["path"].endswith(".ARW")


# ═══════════════════════════════ §4/11 człon szósty — R-S1-4: odwracalność klatki nazwanej ŚCIEŻKĄ


def test_edycja_slownika_odpina_takze_klatki_ze_SCIEZKI(monkeypatch):
    """R-S1-4 (odroczone z recenzji diffu S1 — źródła `path` wtedy nie było).

    Klatka RAW nazwana ścieżką ma `object_source='path'` **i `object_raw IS NULL`**, więc dawny
    predykat odpinania (`source IN ('alias','curated')` ∧ świadek z nagłówka) NIE ZAFISZKOWAŁBY
    ŻADNEJ z nich. Usunięcie `LMC` ze słownika zostawiłoby 36 klatek przypiętych do obiektu,
    którego słownik już nie zna — przy `§5.9` ZIELONEJ, bo encje i eventy zgadzają się co do sztuki.

    Fikstura MUSI mieć klatkę BEZ ZEZNANIA, inaczej człon nie ma jak się zaczerwienić."""
    con = _baza(_lmc(2) + [(rf"{R}\LIGHTS\LMC\RC8\L\x.fit", "Large Magellanic Cloud", "fits")])
    resolver.run_resolver(con, NOW)                        # klatka 3 dostaje obiekt z nagłówka
    p = resolver.path_proposals(con)[0]
    repo.user_assign_object(con, alias_norm=None, canon=p.canon, catalog=p.catalog, kind=p.kind,
                            frame_ids=list(p.frame_ids), now=NOW, object_source="path")
    resolver.run_resolver(con, NOW)                        # zasiew nazw potocznych
    assert con.execute(
        "SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0] == 3

    okrojony = tuple(r for r in ro.load_own_objects() if r["c"] != "LMC")
    monkeypatch.setattr(resolver, "load_own_objects", lambda: okrojony)
    s = resolver.sync_own_aliases(con, NOW)
    assert s.own_frames_unassigned == 3, "klatki ze ŚCIEŻKI muszą wypaść razem z tymi z nagłówka"
    assert con.execute(
        "SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0] == 0
    # …do NULL-a, nie do nagrobka: migracja nie kasuje klatce przyszłości
    assert {r[0] for r in con.execute("SELECT DISTINCT object_source FROM frame").fetchall()} \
        == {None}
    parity = {p.name: p for p in audit.entity_event_parity(con)}
    assert parity["frame.object_id"].ok and parity["object_alias"].ok


def test_odpinanie_nie_rusza_klatek_nazwanych_INNA_droga():
    """Zakres pozostaje WĄSKI: klatka tego samego obiektu nazwana z nagłówka nazwą, której wpis
    nie zna, zostaje nietknięta — odpinamy to, czego bez wpisu NIE DA SIĘ odtworzyć."""
    con = _baza([(rf"{R}\LIGHTS\NGC7000\RC8\L\x.fit", "NGC7000", "fits"),
                 (rf"{R}\LIGHTS\NGC7000\A7R3\OSC\y.ARW", None, "raw")])
    resolver.run_resolver(con, NOW)
    p = resolver.path_proposals(con)[0]
    repo.user_assign_object(con, alias_norm=None, canon=p.canon, catalog=p.catalog, kind=p.kind,
                            frame_ids=list(p.frame_ids), now=NOW, object_source="path")
    oid = con.execute("SELECT id FROM object WHERE canon = 'NGC7000'").fetchone()[0]
    wycofane, odpiete = repo.retire_alias_and_unassign(
        con, object_id=oid, alias_norms=["JAKASNAZWA"], now=NOW)
    assert (wycofane, odpiete) == (0, 0)                   # diff-first: zero różnicy ⇒ zero DML
    assert con.execute(
        "SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0] == 2


def test_zdjecie_samej_NAZWY_POTOCZNEJ_nie_odpina_klatek_ze_sciezki(monkeypatch):
    """DRUGI warunek członu — bez niego był ZA SZEROKI (złapane pierwszym przebiegiem tego pliku).

    Wpis `LMC` ZOSTAJE, znika tylko jego nazwa potoczna: klatka nazwana ścieżką dalej odtwarza swój
    kanon z tego samego wpisu, więc odpięcie byłoby stratą bez zysku. Odpinamy klatkę bez zeznania
    wyłącznie wtedy, gdy zniknął KANON — czyli sam rekord."""
    con = _baza(_lmc(2) + [(rf"{R}\LIGHTS\LMC\RC8\L\x.fit", "Large Magellanic Cloud", "fits")])
    resolver.run_resolver(con, NOW)
    p = resolver.path_proposals(con)[0]
    repo.user_assign_object(con, alias_norm=None, canon=p.canon, catalog=p.catalog, kind=p.kind,
                            frame_ids=list(p.frame_ids), now=NOW, object_source="path")
    resolver.run_resolver(con, NOW)

    okrojony = tuple({**r, "n": []} if r["c"] == "LMC" else r for r in ro.load_own_objects())
    monkeypatch.setattr(resolver, "load_own_objects", lambda: okrojony)
    s = resolver.sync_own_aliases(con, NOW)
    assert s.own_frames_unassigned == 1, "wypada TYLKO klatka nazwana wycofaną nazwą (świadek)"
    assert {r[0] for r in con.execute(
        "SELECT DISTINCT object_source FROM frame WHERE object_id IS NOT NULL").fetchall()} \
        == {"path"}


def test_kontrakt_klingi_odpinania_ma_TRZY_czlony():
    """Publiczna klinga odpowiada za SWÓJ kontrakt, nie za dobre maniery wołającego. Trzy człony
    strażnika kanonu, każdy z osobnym falsyfikatorem:

      (a) klucz, którego ten obiekt NIE MA jako równoważności `curated` — nie odpina niczego
          (inaczej: klatki na NULL bez wycofania czegokolwiek, a następny przebieg przypina je
          z powrotem — czysty churn w dzienniku);
      (b) kanon ODTWARZALNY z gramatyki katalogowej — nie odpina (klatka zachowa nazwę bez wpisu);
      (c) kanon spoza gramatyki, klucz realnie wycofany — ODPINA (to jest przypadek LMC)."""
    con = _baza(_lmc(2) + [(rf"{R}\LIGHTS\NGC7000\A7R3\OSC\y.ARW", None, "raw")])
    prop = {p.canon: p for p in resolver.path_proposals(con)}
    for p in prop.values():
        repo.user_assign_object(con, alias_norm=None, canon=p.canon, catalog=p.catalog,
                                kind=p.kind, frame_ids=list(p.frame_ids), now=NOW,
                                object_source="path")
    lmc = con.execute("SELECT id FROM object WHERE canon = 'LMC'").fetchone()[0]
    ngc = con.execute("SELECT id FROM object WHERE canon = 'NGC7000'").fetchone()[0]

    # (a) klucz spoza równoważności `curated` tego obiektu
    assert repo.retire_alias_and_unassign(
        con, object_id=lmc, alias_norms=["LMC"], now=NOW) == (0, 0)
    # (b) kanon gramatyczny — nawet gdyby jego klucz był wycofywany, klatki zostają
    assert repo.retire_alias_and_unassign(
        con, object_id=ngc, alias_norms=["NGC7000"], now=NOW) == (0, 0)
    assert con.execute(
        "SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0] == 3
    # (c) po zasianiu równoważności ze słownika ten sam gest ODPINA klatki LMC
    resolver.run_resolver(con, NOW)
    wycofane, odpiete = repo.retire_alias_and_unassign(
        con, object_id=lmc, alias_norms=[r[0] for r in con.execute(
            "SELECT alias_norm FROM object_alias WHERE object_id = ?", (lmc,)).fetchall()],
        now=NOW)
    assert wycofane > 0 and odpiete == 2


def test_slownikowe_zrodla_maja_jednego_wlasciciela():
    """Zbiór jest DOPEŁNIENIEM pytania „co da się odtworzyć bez wpisu", nie wyliczanką — nowe
    źródło produkowane ze słownika ma tu dojść, inaczej klatki wypadną z odwracalności po cichu."""
    assert repo._SLOWNIKOWE <= ro.OBJECT_SOURCES
    assert {"alias", "curated", "path"} == repo._SLOWNIKOWE


def test_zrodlo_path_jest_zadeklarowane():
    """Audyt 5b chodzi po `OBJECT_SOURCES`; wartość, którą paczka wnosi, musi tam być — inaczej
    bramka czerwieni się na własnym kodzie."""
    assert "path" in ro.OBJECT_SOURCES
    assert "path" not in ro.ALIAS_SOURCES, "ze ścieżki NIE robimy równoważności (D-OW-2 pkt 4)"
    assert json.loads(json.dumps(sorted(ro.OBJECT_SOURCES)))     # serializowalne do `json_each`
