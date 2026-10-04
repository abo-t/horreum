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
from horreum import audit, db, repo
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
        "observatory_hand"}
    # E5-1: odniesienie niesie też migawkę TOŻSAMOŚCI osi obiektu i znak wodny dziennika - to nie
    # są osie (nie ma ich w `counts`), tylko materiał rozstrzygnięcia po klatkach.
    assert set(_spis().snapshot) == set(_spis().counts) | {"object_hand_frames",
                                                           "event_watermark"}


def test_odniesienie_bez_nowej_osi_wczytuje_sie_jako_zero():
    """Spis zapisany PRZED dołożeniem ósmej osi nie ma jej klucza. Kierunek błędu jest jeden
    i świadomy: zero po stronie „przed" może ukryć WZROST, nigdy ubytek."""
    stare = audit.HumanFacts(object_hand=1, object_cleared=0, config_hand=0, lineage_inputs=0,
                             lineage_excluded=0, calibration_facts=0, calibration_links=0)
    assert stare.offset_hand == 0
    assert _spis(object_hand=1, offset_hand=7).spadki(stare) == {}      # wzrost to nie ubytek
    assert _spis(offset_hand=0).spadki(_spis(offset_hand=3)) == {"offset_hand": (3, 0)}


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
