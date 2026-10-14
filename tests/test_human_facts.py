"""BRAMKA „RĘKA NIETYKALNA" — spis faktów człowieka i jego zachowanie przy nowym materiale.

Warunek Zdzinia z 2026-08-09, dosłownie: *„Wprowadzanie nowych subów albo masterów nie może wpłynąć
na wycofanie czegokolwiek już ustawionego ręcznie w istniejących w bazie klatkach."*

Trzy guardy, które go trzymają, stoją w klingach i mają własne testy tam, gdzie mieszkają:
oś obiektu (`STICKY_OBJECT_SOURCES` — `test_object_gesture.py`), oś sprzętu
(`STICKY_CONFIG_SOURCES` — `test_config_hand.py`), rodowód stosu (`RANGA_ASSERT` —
`test_stacks.py`), rodowód kalibracji (`test_lineage.py`). Ten plik NIE powtarza tamtych bramek;
pilnuje rzeczy, której żadna z nich nie widzi w pojedynkę — **że po przebiegu faktów ręki jest
tyle samo albo więcej**. Do 0809 zdanie „ręka przeżyła" było wnioskiem z lektury kodu; regresja
w którymkolwiek guardzie byłaby cicha, bo nic jej nie liczyło.
"""
import json

from horreum import audit, db, repo, writeback
from horreum import object_change as oc
from horreum.stacks import run_stack_lineage

NOW = "2026-08-09T12:00:00+00:00"
LATER = "2026-08-09T13:00:00+00:00"


def _baza():
    return db.open_db(":memory:")


def _spis(**nadpisz):
    """`HumanFacts` z zerami poza tym, co test nazywa — porównanie ma być czytelne w asercji."""
    pola = {"object_hand": 0, "object_cleared": 0, "config_hand": 0, "lineage_inputs": 0,
            "lineage_excluded": 0, "calibration_facts": 0, "calibration_links": 0,
            "offset_hand": 0}
    return audit.HumanFacts(**{**pola, **nadpisz})


def test_spis_zna_KAZDA_os_gestu_ktora_repo_ma():
    """Bramka pakietu 3a, zarzut 4: spis z dziurą jest gorszy niż brak spisu, bo melduje
    „ubytków BRAK" o osi, której nie liczy. Ten test jest ROLL-CALLEM osi — dokładając nowy gest
    człowieka dopisz go tu i w `human_facts_census`, inaczej regresja na nim będzie cicha."""
    assert set(_spis().counts) == {
        "object_hand", "object_cleared", "config_hand", "lineage_inputs", "lineage_excluded",
        "calibration_facts", "calibration_links", "offset_hand", "retired_hand",
        "observatory_hand", "testimony_hand", "notes_hand"}
    # E5-1: odniesienie niesie też migawkę TOŻSAMOŚCI osi obiektu i znak wodny dziennika - to nie
    # są osie (nie ma ich w `counts`), tylko materiał rozstrzygnięcia po klatkach.
    # AR-128: oś teleskopu jest MIGAWKĄ REKORDÓW (`telescope_hand`), nie liczbą - liczność tej osi
    # nie widzi nadpisania pola, więc nie ma jej w `counts`.
    # AR-145: oś aliasów ręki - też migawka rekordów (przepięcie aliasu nie zmienia liczności).
    assert set(_spis().snapshot) == set(_spis().counts) | {"object_hand_frames",
                                                           "event_watermark", "telescope_hand",
                                                           "alias_hand"}


def test_odniesienie_bez_nowej_osi_wczytuje_sie_jako_zero():
    """Spis zapisany PRZED dołożeniem ósmej osi nie ma jej klucza. Kierunek błędu jest jeden
    i świadomy: zero po stronie „przed" może ukryć WZROST, nigdy ubytek."""
    stare = audit.HumanFacts(object_hand=1, object_cleared=0, config_hand=0, lineage_inputs=0,
                             lineage_excluded=0, calibration_facts=0, calibration_links=0)
    assert stare.offset_hand == 0
    assert _spis(object_hand=1, offset_hand=7).spadki(stare) == {}      # wzrost to nie ubytek
    assert _spis(offset_hand=0).spadki(_spis(offset_hand=3)) == {"offset_hand": (3, 0)}
    # Dwunasta oś (uwagi, 0032) - ta sama figura: odniesienie bez klucza wczytuje się zerem.
    assert stare.notes_hand == 0 and "notes_hand" in stare.counts
    assert _spis(object_hand=1, notes_hand=4).spadki(stare) == {}
    assert _spis(notes_hand=1).spadki(_spis(notes_hand=2)) == {"notes_hand": (2, 1)}


# ---------------------------------------------------------------- sam spis

def test_spis_liczy_kazda_os_osobno():
    con = _baza()
    oid = repo.upsert_object(con, canon="IC443", catalog="IC", kind=None, now=NOW)[0]
    a, _ = repo.upsert_frame(con, sha1_data="aaa", kind="light", filetype="raw",
                             camera_id=None, now=NOW)
    b, _ = repo.upsert_frame(con, sha1_data="bbb", kind="light", filetype="raw",
                             camera_id=None, now=NOW)
    repo.assign_object(con, frame_id=a, object_id=oid, object_source="user", now=NOW)
    repo.assign_object(con, frame_id=b, object_id=oid, object_source="header", now=NOW)

    spis = audit.human_facts_census(con)
    assert spis.object_hand == 1              # `header` to nie ręka
    assert spis.counts["lineage_inputs"] == 0


def test_nagrobek_ma_wlasna_liczbe_obok_sumy():
    """„Ta klatka obiektu NIE ma" jest werdyktem tak samo jak wskazanie nazwy — ale jego zniknięcie
    to inna szkoda i inna droga naprawy, więc w sumie osi nie ma prawa się rozpłynąć."""
    con = _baza()
    oid = repo.upsert_object(con, canon="IC443", catalog="IC", kind=None, now=NOW)[0]
    a, _ = repo.upsert_frame(con, sha1_data="aaa", kind="light", filetype="raw",
                             camera_id=None, now=NOW)
    repo.assign_object(con, frame_id=a, object_id=oid, object_source="path", now=NOW)
    repo.clear_object_assignment(con, frame_ids=[a], now=NOW)

    spis = audit.human_facts_census(con)
    assert (spis.object_hand, spis.object_cleared) == (1, 1)


def test_spadki_lapia_ubytek_i_MILCZA_o_wzroscie():
    """Wzrost nie jest naruszeniem: nowy materiał wolno opatrzyć ręką, a przeniesienie faktu na
    następczynię też podnosi licznik. Pytamy WYŁĄCZNIE o ubytek, bo tylko on jest wycofaniem."""
    przed = _spis(object_hand=703, config_hand=3, lineage_inputs=1876)
    po_wzroscie = _spis(object_hand=768, config_hand=3, lineage_inputs=1876)
    po_ubytku = _spis(object_hand=703, config_hand=3, lineage_inputs=1875)

    assert po_wzroscie.spadki(przed) == {}
    assert po_ubytku.spadki(przed) == {"lineage_inputs": (1876, 1875)}
    # Falsyfikator: gdyby `spadki` porównywało sumy, ubytek na jednej osi zniknąłby pod wzrostem
    # na drugiej — więc sprawdzamy właśnie taki przypadek.
    mieszany = _spis(object_hand=800, config_hand=3, lineage_inputs=1875)
    assert mieszany.spadki(przed) == {"lineage_inputs": (1876, 1875)}


# ---------------------------------------------------------------- przebieg na żywym materiale

def _stos_z_werdyktem(con):
    """Gotowy obraz, dwa suby w oknie i JEDEN werdykt ręki — najmniejszy układ, w którym da się
    zapytać, czy nowy materiał uszczupla spis."""
    con.execute("INSERT INTO camera(model_canon, created_at) VALUES ('ASI2600MM', ?)", (NOW,))
    con.execute("INSERT INTO telescope(telescop_canon, status, created_at) "
                "VALUES ('A140R', 'proposed', ?)", (NOW,))
    con.execute("INSERT INTO config(telescope_id, camera_id, status, created_at) "
                "VALUES (1, 1, 'proposed', ?)", (NOW,))
    con.execute("INSERT INTO object(canon, catalog, kind) VALUES ('CTB1', 'catalog', 'deep_sky')")
    raw = ('{"IMAGETYP": "Master Light", "OBJECT": "CTB 1", "FILTER": "H", "EXPTIME": 600.0, '
           '"TELESCOP": "A140R", "DATE-OBS": "2025-08-30T20:00:00", '
           '"DATE-END": "2025-08-30T23:00:00"}')
    cur = con.execute(
        "INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, "
        "filter_canon, first_seen_at) VALUES ('m1', 'master_light', 'xisf', 1, 1, 1, 'Ha', ?)",
        (NOW,))
    m = cur.lastrowid
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, exptime) VALUES (?, ?, ?, 600.0)",
                (m, raw, "2025-08-30T20:00:00"))
    con.execute("INSERT INTO location(frame_id, volume, path, present) "
                "VALUES (?, 'V', 'R:\\stos.xisf', 1)", (m,))
    subs = []
    for sha, kiedy in (("l1", "2025-08-30T20:30:00"), ("l2", "2025-08-30T21:30:00")):
        c = con.execute(
            "INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, "
            "filter_canon, first_seen_at) VALUES (?, 'light', 'fits', 1, 1, 1, 'Ha', ?)",
            (sha, NOW))
        con.execute("INSERT INTO header(frame_id, raw_json, date_obs, exptime, ccd_temp) "
                    "VALUES (?, '{}', ?, 600.0, -10.0)", (c.lastrowid, kiedy))
        subs.append(c.lastrowid)
    con.commit()
    return m, subs


def test_nowy_sub_nie_uszczupla_spisu_faktow_reki():
    """BRAMKA WŁAŚCIWA: wjazd nowego materiału i pełny przebieg rodowodu — spis PO nie może być
    mniejszy niż PRZED. To jest ta asercja, której do 0809 nie było nigdzie."""
    con = _baza()
    m, subs = _stos_z_werdyktem(con)
    run_stack_lineage(con, now=NOW, xml_reader=lambda _p: None)
    iid = con.execute("SELECT id FROM integration WHERE master_frame_id = ?", (m,)).fetchone()[0]
    repo.judge_integration_input(con, integration_id=iid, input_frame_id=subs[0],
                                 excluded=False, now=NOW)
    przed = audit.human_facts_census(con)
    assert przed.lineage_inputs == 1

    con.execute("INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, "
                "filter_canon, first_seen_at) VALUES ('l3', 'light', 'fits', 1, 1, 1, 'Ha', ?)",
                (NOW,))
    nowy = con.execute("SELECT id FROM frame WHERE sha1_data = 'l3'").fetchone()[0]
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, exptime, ccd_temp) "
                "VALUES (?, '{}', '2025-08-30T22:00:00', 600.0, -10.0)", (nowy,))
    con.commit()
    run_stack_lineage(con, now=LATER, xml_reader=lambda _p: None)

    po = audit.human_facts_census(con)
    assert po.spadki(przed) == {}
    assert po.lineage_inputs == przed.lineage_inputs


# ---------------------------------------------------------------- oś uwag klatki (0032)

def test_spis_liczy_uwagi_klatek():
    con = _baza()
    a, _ = repo.upsert_frame(con, sha1_data="aaa", kind="light", filetype="raw",
                             camera_id=None, now=NOW)
    b, _ = repo.upsert_frame(con, sha1_data="bbb", kind="flat", filetype="fits",
                             camera_id=None, now=NOW)
    assert audit.human_facts_census(con).notes_hand == 0
    repo.set_frame_note(con, frame_ids=[a, b], body="zmieniony flat", now=NOW)
    przed = audit.human_facts_census(con)
    assert przed.notes_hand == 2
    repo.clear_frame_note(con, frame_ids=[b], now=LATER)
    assert audit.human_facts_census(con).spadki(przed) == {"notes_hand": (2, 1)}


def test_spis_na_bazie_sprzed_0032(tmp_path):
    """Spis nie migruje mierzonej bazy - na bazie v31 (bez tabeli uwag) oś liczy się jako 0,
    zamiast wywracać `human-facts`."""
    path = str(tmp_path / "v31.db")
    con = db.connect(path)
    for version, filename in db.MIGRATIONS:
        if version <= 31:
            db._apply_migration(con, version, db._migration_sql(filename))
    assert not con.execute(
        "SELECT count(*) FROM sqlite_master WHERE name = 'frame_note'").fetchone()[0]
    assert audit.human_facts_census(con).notes_hand == 0
    con.close()


def test_cli_ubytek_uwagi_to_kod_1(tmp_path, capsys):
    """Bramka etapu: odniesienie z `--json`, uwaga zdjęta poza odniesieniem - `--baseline` drukuje
    oś i ubytek, kod wyjścia 1. Uwag nie pisze żaden automat, więc każdy ubytek jest wycofaniem."""
    from horreum import cli
    path = str(tmp_path / "h.db")
    con = db.open_db(path)
    a, _ = repo.upsert_frame(con, sha1_data="aaa", kind="light", filetype="raw",
                             camera_id=None, now=NOW)
    repo.set_frame_note(con, frame_ids=[a], body="chmury po 2:00", now=NOW)
    con.close()
    assert cli.main(["human-facts", path]) == 0
    assert "  notes_hand         1" in capsys.readouterr().out.splitlines()
    assert cli.main(["human-facts", path, "--json"]) == 0
    odniesienie = tmp_path / "przed.json"
    odniesienie.write_text(capsys.readouterr().out, encoding="utf-8")
    assert cli.main(["human-facts", path, "--baseline", str(odniesienie)]) == 0
    capsys.readouterr()

    con = db.open_db(path)
    repo.clear_frame_note(con, frame_ids=[a], now=LATER)
    con.close()
    assert cli.main(["human-facts", path, "--baseline", str(odniesienie)]) == 1
    assert "  UBYTEK notes_hand: 1 -> 0" in capsys.readouterr().out.splitlines()


# ---------------------------------------------------------------- oś aliasów ręki (AR-145)

def _alias_reki(con, nazwa, canon):
    """Alias ręki drogą gestu „Przypisz obiekt…” (`source='user'`) - klatka i nazwa w jednym."""
    fid, _ = repo.upsert_frame(con, sha1_data=f"al-{nazwa}", kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    repo.user_assign_object(con, alias_norm=nazwa, canon=canon, catalog=None, kind="deep_sky",
                            frame_ids=[fid], now=NOW)
    return con.execute("SELECT id, object_id FROM object_alias WHERE alias_norm = ?",
                       (nazwa,)).fetchone()


def _z_json(spis):
    """Spis przepuszczony przez `--json` - odniesienie wraca z pliku, nie z pamięci."""
    return audit.HumanFacts(**json.loads(json.dumps(spis.snapshot)))


def test_os_aliasow_reki_to_migawka_aliasow_user():
    """Migawka niesie wyłącznie aliasy ręki (`source='user'`) jako `(id, alias_norm, object_id)`;
    równoważność ze słownika ręką nie jest. JSON odtwarza spis w całości.
    Mutant: spis bez osi (`alias_hand=None`) - migawka pusta, test czerwony."""
    con = _baza()
    a = _alias_reki(con, "plomien", "NGC2024")
    repo.add_object_alias(con, alias_norm="ngc2024", object_id=a["object_id"], source="curated",
                          now=NOW)
    spis = audit.human_facts_census(con)
    assert spis.alias_hand == ((a["id"], "plomien", a["object_id"]),)
    assert _z_json(spis) == spis


def test_przepiecie_aliasu_reki_jest_ubytkiem_choc_liczba_stoi():
    """Przepięcie aliasu ręki na inny obiekt nie zmienia liczności osi - ubytek widać wyłącznie po
    rekordzie. Skasowanie wiersza i zmiana źródła z `user` (np. klinga przepięcia bez guardu ręki)
    to ten sam ubytek: ręka pod tym kluczem już nie mówi.
    Mutant: porównanie liczności (`len`) zamiast rekordów - przepięcie przechodzi jako „BRAK”."""
    con = _baza()
    a = _alias_reki(con, "plomien", "NGC2024")
    b = _alias_reki(con, "konik", "B33")
    przed = _z_json(audit.human_facts_census(con))
    con.execute("UPDATE object_alias SET object_id = ? WHERE id = ?", (b["object_id"], a["id"]))
    con.commit()
    po = audit.human_facts_census(con)
    assert len(po.alias_hand) == len(przed.alias_hand)
    assert po.reka_aliasow(przed) == (("plomien", a["object_id"], b["object_id"]),)
    assert po.spadki(przed) == {"alias_hand": (2, 1)}

    con.execute("DELETE FROM object_alias WHERE id = ?", (b["id"],))
    con.execute("UPDATE object_alias SET object_id = ?, source = 'catalog_xref' WHERE id = ?",
                (a["object_id"], a["id"]))
    con.commit()
    po = audit.human_facts_census(con)
    assert po.reka_aliasow(przed) == (("konik", b["object_id"], None),
                                      ("plomien", a["object_id"], None))
    assert po.spadki(przed) == {"alias_hand": (2, 0)}


def test_nowy_alias_i_ten_sam_klucz_pod_nowym_id_to_nie_ubytek():
    """Wzrost nie jest naruszeniem; ta sama nazwa przy tym samym obiekcie pod nowym `id` to ten sam
    fakt ręki (tożsamość po kluczu - cofnięcie i ponowienie gestu zakłada wiersz na nowo)."""
    con = _baza()
    a = _alias_reki(con, "plomien", "NGC2024")
    przed = _z_json(audit.human_facts_census(con))
    _alias_reki(con, "konik", "B33")
    con.execute("DELETE FROM object_alias WHERE id = ?", (a["id"],))
    con.execute("INSERT INTO object_alias(id, alias_norm, object_id, source) "
                "VALUES (999, 'plomien', ?, 'user')", (a["object_id"],))
    con.commit()
    po = audit.human_facts_census(con)
    assert po.reka_aliasow(przed) == () and po.spadki(przed) == {}


def test_odniesienie_bez_osi_aliasow_to_brak_porownania_nie_wynik():
    """Spis sprzed AR-145 nie ma klucza `alias_hand` - oś poza porównaniem (`None`): ani fałszywy
    ubytek, ani porównanie zrobione na pustej migawce udające pomiar.
    Mutant: domyślna `()` zamiast `None` - `reka_aliasow` zwraca `()` jak po zmierzeniu."""
    stare = _spis()
    assert stare.alias_hand is None and "alias_hand" not in stare.counts
    teraz = _spis(alias_hand=())
    assert teraz.reka_aliasow(stare) is None and teraz.spadki(stare) == {}
    assert stare.reka_aliasow(_spis(alias_hand=((1, "plomien", 1),))) is None


def test_wyjasnienie_po_rekordzie_nie_po_id():
    """SQLite używa ponownie id skasowanego najwyższego wiersza (0040): zdjęcie gestem INNEGO aliasu
    pod tym samym id nie wyjaśnia ubytku tego.
    Mutant: wyjaśnienie po samym `id` - ubytek `plomien` znika."""
    przed = _spis(alias_hand=((5, "plomien", 1),))
    po = _spis(alias_hand=())
    assert po.spadki(przed, zdjete_aliasy=frozenset({(5, "inny", 1)})) == {"alias_hand": (1, 0)}
    assert po.spadki(przed, zdjete_aliasy=frozenset({(5, "plomien", 1)})) == {}


def test_nagrobek_obiektu_wyjasnia_zdjecie_aliasu_wlasnego_gestu(tmp_path):
    """„Zmień obiekt…” zakłada IC405 i alias ręki wpisanej nazwy; spis PO geście, potem „Cofnij” -
    nagrobek zdejmuje alias gestu (`object.alias_retired` z `run_id` przebiegu, który go założył):
    wyjaśnione, nie ubytek. Alias ręki SPRZED gestu skasowany obok - ubytek zostaje, także gdy
    dziennik niesie podrobione `object.alias_retired` bez śladu przebiegu.
    Mutanty: `alias_hand_retired_since` zwraca pusty zbiór - `plomien` zostaje ubytkiem; zapytanie
    bez złączenia ze śladem przebiegu - podróbka wyjaśnia `konik`."""
    from test_object_change_write import _Scena
    s = _Scena(tmp_path)
    con = s.con
    target = oc.ObjectTarget(canon="IC405", catalog="IC", kind="deep_sky", alias_norm="plomien",
                             card_form="IC 405")
    plan = oc.ObjectChangePlan(run_id="R1", target=target,
                               items=tuple(s.pozycja(i) for i in range(3)), skipped=())
    writeback.commit_object_change(con, s.stage(plan), now=NOW)
    konik = _alias_reki(con, "konik", "B33")
    przed = _z_json(audit.human_facts_census(con))
    ic = con.execute("SELECT object_id FROM object_alias WHERE alias_norm = 'plomien'").fetchone()[0]
    assert {r[1] for r in przed.alias_hand} == {"plomien", "konik"}

    writeback.undo_object_change(con, "R1", now=LATER)
    po = audit.human_facts_census(con)
    zdjete = audit.alias_hand_retired_since(con, przed.event_watermark)
    assert {(r[1], r[2]) for r in zdjete} == {("plomien", ic)}
    assert po.reka_aliasow(przed) == (("plomien", ic, None),)          # bez dowodu - ubytek
    assert po.reka_aliasow(przed, zdjete) == ()
    assert "alias_hand" not in po.spadki(przed, zdjete_aliasy=zdjete)

    con.execute("DELETE FROM object_alias WHERE id = ?", (konik["id"],))
    con.execute("INSERT INTO event(ts, actor, verb, target, payload) VALUES (?, 'user:local', "
                "'object.alias_retired', ?, ?)",
                (LATER, f"object:{konik['object_id']}",
                 json.dumps({"alias_norm": "konik", "source": "user", "run_id": "R1"})))
    con.commit()
    zdjete = audit.alias_hand_retired_since(con, przed.event_watermark)
    po = audit.human_facts_census(con)
    assert po.reka_aliasow(przed, zdjete) == (("konik", konik["object_id"], None),)
    assert po.spadki(przed, zdjete_aliasy=zdjete)["alias_hand"] == (2, 1)
    assert audit.alias_hand_retired_since(con, None) == frozenset()
    # Baza sprzed 0040 nie ma `made_alias_id`, więc zbioru wyjaśnień nie ma z czego liczyć - straż
    # wersji, nie błąd zapytania (mutant bez straży oddaje tu `plomien` z dziennika tej bazy).
    con.execute("PRAGMA user_version = 39")
    assert audit.alias_hand_retired_since(con, przed.event_watermark) == frozenset()
    con.close()


def test_cli_przepiecie_aliasu_reki_to_kod_1_a_stare_odniesienie_mowi_wprost(tmp_path, capsys):
    """Bramka etapu na osi aliasów: odniesienie z `--json`, alias ręki przepięty poza gestem -
    `--baseline` drukuje alias i ubytek, kod 1. Odniesienie bez klucza osi (spis sprzed AR-145) -
    kod 0 i zdanie, że oś poza porównaniem, zamiast milczenia pod „ubytków: BRAK”."""
    from horreum import cli
    path = str(tmp_path / "h.db")
    con = db.open_db(path)
    a = _alias_reki(con, "plomien", "NGC2024")
    b = _alias_reki(con, "konik", "B33")
    con.close()
    assert cli.main(["human-facts", path, "--json"]) == 0
    snapshot = json.loads(capsys.readouterr().out)
    assert snapshot["alias_hand"] == [[a["id"], "plomien", a["object_id"]],
                                      [b["id"], "konik", b["object_id"]]]
    odniesienie = tmp_path / "przed.json"
    odniesienie.write_text(json.dumps(snapshot), encoding="utf-8")
    stare = tmp_path / "stare.json"
    stare.write_text(json.dumps({k: v for k, v in snapshot.items() if k != "alias_hand"}),
                     encoding="utf-8")
    assert cli.main(["human-facts", path, "--baseline", str(odniesienie)]) == 0
    assert "  alias_hand         2 (aliasy nazw z reki)" in capsys.readouterr().out.splitlines()

    con = db.open_db(path)
    con.execute("UPDATE object_alias SET object_id = ? WHERE id = ?", (b["object_id"], a["id"]))
    con.commit()
    con.close()
    assert cli.main(["human-facts", path, "--baseline", str(odniesienie)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert (f"  alias plomien: object:{a['object_id']} -> object:{b['object_id']} bez gestu reki"
            in out)
    assert "  UBYTEK alias_hand: 2 -> 1" in out
    assert cli.main(["human-facts", path, "--baseline", str(stare)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "  odniesienie bez migawki aliasow reki - os alias_hand poza porownaniem" in out


def test_cli_odniesienie_bez_osi_teleskopu_mowi_wprost(tmp_path, capsys):
    """Odniesienie bez klucza `telescope_hand` (spis sprzed 0039) - oś poza porównaniem, kod 0
    i zdanie o tym w wyjściu, zamiast milczenia pod „ubytków: BRAK”. Odniesienie z migawką - bez
    tego zdania.
    Mutant: gałąź `rozbior_tel is None` zdjęta - wiersza nie ma."""
    from horreum import cli
    path = str(tmp_path / "h.db")
    db.open_db(path).close()
    assert cli.main(["human-facts", path, "--json"]) == 0
    snapshot = json.loads(capsys.readouterr().out)
    assert snapshot["telescope_hand"] == []
    pelne = tmp_path / "pelne.json"
    pelne.write_text(json.dumps(snapshot), encoding="utf-8")
    stare = tmp_path / "stare.json"
    stare.write_text(json.dumps({k: v for k, v in snapshot.items() if k != "telescope_hand"}),
                     encoding="utf-8")
    wiersz = "  os telescope_hand poza porownaniem (spis bez migawki rekordow teleskopu)"
    assert cli.main(["human-facts", path, "--baseline", str(stare)]) == 0
    assert wiersz in capsys.readouterr().out.splitlines()
    assert cli.main(["human-facts", path, "--baseline", str(pelne)]) == 0
    assert wiersz not in capsys.readouterr().out.splitlines()
