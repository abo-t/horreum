"""SŁOWNIK OBIEKTÓW WŁASNYCH (S1, brief obiektów własnych / D-OW-1 wariant E′).
Klasa „obiekt bez numeru katalogowego" — `LMC`, `WR134`. Trzy warstwy, bo trzy rzeczy mogą się
rozjechać osobno: szczebel drabiny (kanon z nazwy), kontrakt assetu (dwie klasy rekordów, jeden
plik dla resolvera i planera) oraz cykl zasiewu aliasów (zasiej → cisza → migracja assetu odpina).
"""
import pytest
from horreum import db, resolver, targets
from horreum.audit import entity_event_parity, light_population_closure, object_source_audit
from horreum.resolve import objects as ro
from horreum.resolve.objects import ALIAS_SOURCES, OBJECT_SOURCES, resolve_object
NOW = "2026-08-03T12:00:00Z"


# ─────────────────────────────────────────────────────────── szczebel drabiny


@pytest.mark.parametrize("raw, canon", [
    ("LMC", "LMC"),                          # kanon SAMO-KANONICZNY — to on łamał `_COMMON`
    ("lmc", "LMC"),                          # normalizacja jak na każdym szczeblu
    ("Large Magellanic Cloud", "LMC"),       # nazwa potoczna ze spacjami
    ("Wielki Oblok Magellana", "LMC"),
    ("WR134", "WR134"),
    ("WR 134", "WR134"),
    ("HD 191765", "WR134"),                  # nazwa potoczna wskazuje kanon INNY niż ona sama
])
def test_slownik_rozwiazuje_nazwy_wlasne(raw, canon):
    o = resolve_object(raw)
    assert (o.canon, o.source, o.kind) == (canon, "curated", "own")


def test_slownik_nie_rusza_gramatyki_katalogowej():
    """Szczebel jest OSTATNI w `resolve_object`: oznaczenie katalogowe i nazwa potoczna wygrywają.
    Falsyfikator regresji „słownik wpuszczony za wysoko"."""
    assert resolve_object("M106").source == "catalog_xref"
    assert resolve_object("NGC 4258").source == "header"
    assert resolve_object("Rosette Nebula").source == "common_name"


def test_nazwa_spoza_slownika_dalej_none():
    assert resolve_object("Snapshot") is None


def test_kanon_wlasny_nie_dostaje_katalogu():
    """`catalog=None` niesie fakt: ten obiekt nie należy do żadnej gramatyki katalogowej. Gdyby
    szczebel zgadywał katalog, `catalog_label` zaczęłoby kłamać w facecie i w nazwach plików."""
    assert resolve_object("LMC").catalog is None


# ────────────────────────────────────── kontrakt assetu (jeden plik, dwaj czytelnicy)


def test_asset_ma_dwie_klasy_rekordow():
    """Rekord-CEL ma komplet pól celu, rekord-NAZWA nie ma ŻADNEGO. Trzeciej klasy nie ma —
    rekord częściowy jest błędem pliku, nie wariantem."""
    for rec in ro.load_own_objects():
        n = targets.target_fields_present(rec)
        assert n in (0, len(targets.TARGET_FIELDS)), f"{rec['c']}: {n} pól celu"


def test_planer_dostaje_wylacznie_rekordy_cele():
    """E′ z MECHANIZMU, nie z ostrożności wołającego: rekord-nazwa nie dociera do puli planera.
    Falsyfikator trzech awarii zmierzonych w kodzie (`--find` bez `feasible`, przejęcie kanonu
    w `coverage_index` bez wiersza, koercja `_target`)."""
    pula = {t.canon for t in targets.load_targets()}
    assert "WR134" in pula                       # rekord-cel — planer go zna
    assert "LMC" not in pula                     # rekord-nazwa — zna go WYŁĄCZNIE resolver
    assert resolve_object("LMC") is not None     # …i naprawdę zna


def test_koercja_targetu_nietknieta():
    """Filtr E′ stoi PRZED `_target`, więc rekord NIEPEŁNY nadal wybucha przy kanonie (EXPECT),
    a nie pół planera dalej. Pin przeciw „rozluźnijmy koercję, to przejdzie"."""
    with pytest.raises(ValueError, match="major_arcmin"):
        targets._target({"c": "X", "t": "EmN", "r": 1.0, "d": 2.0}, "curated")


def test_asset_planera_i_resolvera_to_JEDEN_plik():
    """SPOT: gdyby warstwa `curated` czytała inny plik niż słownik, kanon mógłby istnieć w jednym
    świecie i nie istnieć w drugim — dokładnie stan sprzed E′."""
    assert targets._ASSET["curated"] == ("horreum.resolve.data", "objects_own.json")


def test_kolizja_nazw_w_slowniku_wybucha(monkeypatch):
    """Dwa rekordy pod jedną nazwą = człowiek wpisał ją dwa razy. Ciche „wygrywa ostatni" ukryłoby
    to na zawsze; unikalność KANONÓW pilnuje producent, ale nazwy `n` widzi dopiero indeks."""
    monkeypatch.setattr(ro, "load_own_objects", lambda: (
        {"c": "AAA", "n": ["Wspolna"]}, {"c": "BBB", "n": ["Wspolna"]}))
    ro._own_index.cache_clear()
    with pytest.raises(ValueError, match="dwa rekordy"):
        ro._own_index()
    ro._own_index.cache_clear()


# ─────────────────────────────────────────────────────────── enum źródeł (jeden właściciel)


def test_enum_zrodel_pokrywa_szczeble_drabiny():
    """Każde źródło, które drabina POTRAFI wyprodukować, musi być w stałej — inaczej audyt 5b
    czerwieni się na własnym kodzie. Rozjazd trzech siedzib tego enumu powstał dokładnie tak."""
    assert {"header", "catalog_xref", "common_name", "curated"} <= ALIAS_SOURCES
    assert ALIAS_SOURCES < OBJECT_SOURCES            # klatka ma nadto `alias` i `region`
    assert {"alias", "region"} <= OBJECT_SOURCES
    assert "region" not in ALIAS_SOURCES             # region rozpoznaje ze WSPÓŁRZĘDNYCH


# ─────────────────────────────────────────────────────────── cykl zasiewu (fikstura bazy)


def _baza(raws):
    con = db.connect(":memory:")
    db.migrate(con)
    for i, raw in enumerate(raws, start=1):
        con.execute("INSERT INTO frame(id, kind, sha1_data, first_seen_at) VALUES (?,'light',?,?)",
                    (i, f"sha{i}", NOW))
        con.execute("INSERT INTO header(frame_id, object_raw, raw_json) VALUES (?,?,'{}')",
                    (i, raw))
    con.commit()
    return con


def _ev(con, verb):
    return con.execute("SELECT count(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


def test_zasiew_nazw_potocznych_po_przebiegu():
    """Klatka zeznaje samym kanonem `LMC`, a mimo to szukajka ma znaleźć „Large Magellanic Cloud":
    zasiew jest przywiązany do TOŻSAMOŚCI, nie do tego, którą nazwą przyszła klatka."""
    con = _baza(["LMC"])
    resolver.run_resolver(con, NOW)
    aliasy = {r[0] for r in con.execute(
        "SELECT alias_norm FROM object_alias WHERE source = 'curated'").fetchall()}
    assert {"LMC", "LARGEMAGELLANICCLOUD", "WIELKIOBLOKMAGELLANA"} <= aliasy


def test_zasiew_tylko_dla_obiektow_ISTNIEJACYCH():
    """`object_alias.object_id` to NOT NULL REFERENCES object(id): dopóki żadna klatka nie ma
    `WR134`, nie ma czego aliasować. Asset opisuje KLASĘ, baza opisuje ARCHIWUM."""
    con = _baza(["LMC"])
    resolver.run_resolver(con, NOW)
    kanony = {r[0] for r in con.execute("SELECT canon FROM object").fetchall()}
    assert kanony == {"LMC"}
    assert con.execute("SELECT count(*) FROM object_alias WHERE alias_norm = 'WR134'"
                       ).fetchone()[0] == 0


def test_drugi_przebieg_to_cisza():
    """DIFF-FIRST: zero różnicy ⇒ zero DML i zero eventów. Naiwne DELETE+INSERT emitowałoby przy
    każdym przebiegu i churnowało `id`."""
    con = _baza(["LMC", "NGC7000"])
    resolver.run_resolver(con, NOW)
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    s = resolver.run_resolver(con, NOW)
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed
    assert (s.own_aliases_seeded, s.own_aliases_retired, s.own_frames_unassigned) == (0, 0, 0)


def test_migracja_assetu_wycofuje_alias_I_odpina_klatki(monkeypatch):
    """DWA CZŁONY re-derywacji. Samo skasowanie aliasu zostawiłoby klatkom `object_id` NA ZAWSZE
    (żaden szczebel resolvera nie odpina), więc „operacja migracyjna" byłaby tylko nazwą."""
    con = _baza(["LMC", "Large Magellanic Cloud", "NGC7000"])
    resolver.run_resolver(con, NOW)
    assert con.execute("SELECT count(*) FROM frame WHERE object_id IS NOT NULL"
                       ).fetchone()[0] == 3
    okrojony = tuple({**r, "n": [n for n in (r.get("n") or []) if n != "Large Magellanic Cloud"]}
                     if r["c"] == "LMC" else r for r in ro.load_own_objects())
    monkeypatch.setattr(resolver, "load_own_objects", lambda: okrojony)
    s = resolver.sync_own_aliases(con, NOW)
    assert (s.own_aliases_retired, s.own_frames_unassigned) == (1, 1)
    assert _ev(con, "object.alias_retired") == 1 and _ev(con, "object.unassigned") == 1
    # klatka 2 (przyszła wycofaną nazwą) odpięta DO NULL — nie do nagrobka: nagrobek jest STICKY
    # i wypadałaby z drabiny na zawsze, czyli migracja kasowałaby jej przyszłość.
    assert con.execute("SELECT object_id, object_source FROM frame WHERE id = 2"
                       ).fetchone()[:2] == (None, None)
    # klatka 1 (kanon) i 3 (nagłówek) NIETKNIĘTE — odpinanie idzie po ŚWIADKU, nie po źródle
    assert con.execute("SELECT object_id FROM frame WHERE id = 1").fetchone()[0] is not None
    assert con.execute("SELECT object_id FROM frame WHERE id = 3").fetchone()[0] is not None


def test_kolizja_nazwy_z_innym_obiektem_to_raport_nie_wyjatek(monkeypatch):
    """Zasiew biegnie w passie masowym Dostawy — wyjątek urwałby `calibrate`/`lineage`/`delta`
    z powodu danych, które user miał prawo stworzyć. Alias zostaje przy dotychczasowym obiekcie."""
    con = _baza(["NGC7000"])
    resolver.run_resolver(con, NOW)
    oid = con.execute("SELECT id FROM object WHERE canon = 'NGC7000'").fetchone()[0]
    con.execute("INSERT INTO object(canon, kind) VALUES ('ZZZ', 'own')")
    con.commit()
    monkeypatch.setattr(resolver, "load_own_objects",
                        lambda: ({"c": "ZZZ", "n": ["NGC7000"]},))   # nazwa już zajęta
    s = resolver.sync_own_aliases(con, NOW)
    assert s.own_alias_conflicts == 1
    assert _ev(con, "object.alias_conflict") == 1        # JEDEN zbiorczy, nie per kolizja
    assert con.execute("SELECT object_id FROM object_alias WHERE alias_norm = 'NGC7000'"
                       ).fetchone()[0] == oid                          # przegrany NIE nadpisał


# ─────────────────────────────────────────────────────────── audyt (§5.9 / §5.9b / §5.7a)


#: Wiersze parytetu, które ta fikstura może rozstrzygnąć. `frame`/`header` wstawiamy surowym SQL
#: (fikstura, nie ingest), więc ich eventów nie ma i ich równość należy do bramki akceptacji na
#: realnym przebiegu — nie do testu osi obiektu.


_OS_OBIEKTU = ("object", "object_alias", "frame.object_id")


def test_parytet_odejmuje_wycofania_i_odpiecia(monkeypatch):
    """§5.9 z członem odejmowanym. Falsyfikator jest w GEŚCIE, nie w liczbie: bez edycji assetu
    człon byłby zielony niezależnie od implementacji, bo nie ma czego odejmować."""
    con = _baza(["LMC", "Large Magellanic Cloud"])
    resolver.run_resolver(con, NOW)
    rows = {p.name: p for p in entity_event_parity(con)}
    assert all(rows[n].ok for n in _OS_OBIEKTU)
    assert all(rows[n].retracted == 0 for n in _OS_OBIEKTU)     # nie ma jeszcze czego odejmować
    okrojony = tuple({**r, "n": []} if r["c"] == "LMC" else r for r in ro.load_own_objects())
    monkeypatch.setattr(resolver, "load_own_objects", lambda: okrojony)
    resolver.sync_own_aliases(con, NOW)
    rows = {p.name: p for p in entity_event_parity(con)}
    assert rows["object_alias"].retracted > 0 and rows["frame.object_id"].retracted > 0
    assert all(rows[n].ok for n in _OS_OBIEKTU), \
        "równość bez odejmowania rozjeżdża się dokładnie o wycofania"
    # …a gdyby formuła NIE odejmowała, te dwa wiersze byłyby czerwone — pin na samej różnicy:
    assert rows["object_alias"].entities != rows["object_alias"].events
    assert rows["frame.object_id"].entities != rows["frame.object_id"].events


def test_parytet_lapie_brak_eventu():
    """Pozytywna asercja zakresu: bramka ma się CZERWIENIĆ, gdy encja powstaje bez emisji.
    Fikstura wstawia klatki surowym SQL (z pominięciem klingi), więc `frame` i `header` są tu
    dowodem, że parytet naprawdę mierzy, a nie zawsze zwraca zielone."""
    con = _baza(["LMC"])
    rows = {p.name: p for p in entity_event_parity(con)}
    assert not rows["frame"].ok and rows["frame"].entities == 1 and rows["frame"].events == 0


def test_audyt_zrodel_lapie_wartosc_spoza_stalej():
    """Falsyfikatorem 5b jest WSTRZYKNIĘCIE wartości nikomu nieznanej — samo dopisanie `curated`
    byłoby zielone, bo to wartość, którą paczka świadomie wnosi."""
    con = _baza(["LMC"])
    resolver.run_resolver(con, NOW)
    assert object_source_audit(con).ok
    con.execute("UPDATE frame SET object_source = 'wymyslone' WHERE id = 1")
    con.commit()
    a = object_source_audit(con)
    assert not a.ok and a.frame_unknown == ("wymyslone",)


def test_rozklad_lightow_domyka_sie():
    """R-S0-6: sześć predykatów raportu ma pokrywać CAŁĄ populację. Rozkład, który się nie domyka,
    jest fałszywie zieloną bramą."""
    con = _baza(["LMC", "NGC7000", "Snapshot"])
    resolver.run_resolver(con, NOW)
    c = light_population_closure(con, resolver.delta_report(con))
    assert c.ok, f"{c.buckets} + bez nagłówka {c.headerless} != {c.total}"


def test_rozklad_lapie_klatke_bez_naglowka():
    """Klasa, którą kryterium ujawnia: predykaty `nameless_*` mają INNER JOIN na `header`,
    a `resolved_no_raw` wymaga obiektu — light bez zeznania i bez obiektu nie wpada do żadnego
    z sześciu. Dziś populacja pusta, więc bez tego testu kryterium byłoby zielone w milczeniu."""
    con = _baza(["LMC"])
    con.execute("INSERT INTO frame(id, kind, sha1_data, first_seen_at) VALUES (99,'light','x',?)",
                (NOW,))
    con.commit()
    resolver.run_resolver(con, NOW)
    c = light_population_closure(con, resolver.delta_report(con))
    assert c.headerless == 1 and c.ok
    assert sum(c.buckets.values()) == c.total - 1     # sześć kubełków SAMO by się nie domknęło
