"""ODNIESIENIE CZASU I TOLERANCJA EKSPOZYCJI (#DR2, GO-2: segmenty R2 + R3).

Bramki odbiorcze G2-7, G2-8, G2-10, G2-11, G2-12 briefu `PLAN_dslr_rodowod.md §5` plus dwa
świadki, których brief nie żądał, a które pilnują granic wprowadzonych tą zmianą: komplet recept
per powód (lekcja R-S3-7 — drabina dwa razy zapomniała o kolejnym kubełku) oraz nieprzechodniość
progu w półce nierozłączności.

Przypadek wzorcowy jest ZMIERZONY, nie wymyślony: master IC443 zeznaje `EXPTIME 90,0` i okno
w UTC, a jego trzy suby to DNG-i `90,0 / 91,0 / 91,0` z czasem LOKALNYM przesuniętym o `+1 h`.
Przed R2+R3 okno wpuszczało z nich ZERO — najpierw przez zegar, potem przez równość ekspozycji.
"""
import json

import pytest

from horreum import db, repo
from horreum.stacks import (EXP_TOL_CEILING_S, REASON_NO_CANDIDATES, REASON_OFFSET_UNKNOWN,
                            exposure_matches, inputs_of,
                            propose_offset_minutes as stacks_propose, run_stack_lineage)

NOW = "2026-08-08T12:00:00+00:00"
LATER = "2026-08-08T13:00:00+00:00"
STOS = r"R:\ARCHIWUM\RC8R\IC443\WBPP\master\masterLight_IC443.xisf"


@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "h.db"))
    c.execute("INSERT INTO camera(model_canon, created_at) VALUES ('SONYA7S', ?)", (NOW,))
    c.execute("INSERT INTO telescope(telescop_canon, status, created_at) VALUES ('RC8R', "
              "'proposed', ?)", (NOW,))
    c.execute("INSERT INTO config(telescope_id, camera_id, status, created_at) "
              "VALUES (1, 1, 'proposed', ?)", (NOW,))
    c.execute("INSERT INTO object(canon, catalog, kind) VALUES ('IC443', 'catalog', 'deep_sky')")
    c.commit()
    yield c
    c.close()


def _light(con, sha1, *, date_obs, exptime=90.0, filetype="raw", filter_canon=None,
           config_id=1, object_id=1):
    """Sub — DOMYŚLNIE `raw`, bo to populacja, dla której ta faza powstała."""
    cur = con.execute(
        "INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, "
        "filter_canon, first_seen_at) VALUES (?, 'light', ?, 1, ?, ?, ?, ?)",
        (sha1, filetype, config_id, object_id, filter_canon, NOW))
    fid = cur.lastrowid
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, exptime, ccd_temp) "
                "VALUES (?, '{}', ?, ?, NULL)", (fid, date_obs, exptime))
    con.commit()
    return fid


def _master(con, sha1="m1", *, start="2019-01-10T20:40:38", end="2019-01-10T21:45:00",
            exptime=90.0, object_id=1, path=STOS):
    raw = {"IMAGETYP": "Master Light", "OBJECT": "IC443", "EXPTIME": exptime,
           "TELESCOP": "RC8R", "DATE-OBS": start, "DATE-END": end}
    cur = con.execute(
        "INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, "
        "filter_canon, first_seen_at) VALUES (?, 'master_light', 'xisf', 1, 1, ?, NULL, ?)",
        (sha1, object_id, NOW))
    fid = cur.lastrowid
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, exptime) VALUES (?, ?, ?, ?)",
                (fid, json.dumps(raw), start, exptime))
    if path:
        con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (fid, path))
    con.commit()
    return fid


def _integracja(con, master_frame_id):
    return con.execute("SELECT * FROM integration WHERE master_frame_id = ?",
                       (master_frame_id,)).fetchone()


def _brak_xml(_path):
    return None


# ============================================================ G2-7 · próg jest progiem (D-DR-2)

@pytest.mark.parametrize("a,b,zgodne", [
    (90.0, 91.0, True),        # IC443 — para, dla której cała reguła powstała
    (91.0, 92.0, True),
    (90.0, 92.0, False),       # NIEPRZECHODNIOŚĆ — właściwość, nie usterka
    (90.0, 120.0, False),
    (600.0, 610.0, False),     # SUFIT — bez niego 2% z 600 dawało 12 s i sklejało dwie nastawy
    (600.0, 602.0, True),      # …ale w granicach sufitu ta sama nastawa dalej się skleja
    (10.0, 10.4, True),        # PODŁOGA — 2% z 10 s to 0,2 s, czyli mniej niż rozdzielczość
    (10.0, 10.6, False),
])
def test_prog_ekspozycji_ma_podloge_sufit_i_nie_jest_przechodni(a, b, zgodne):
    assert exposure_matches(a, b) is zgodne
    assert exposure_matches(b, a) is zgodne, "próg MUSI być symetryczny (min(a,b) w formule)"


def test_prog_nie_zamienia_braku_zeznania_w_dopasowanie():
    """`None` po którejkolwiek stronie → brak zgodności. Master bez `EXPTIME` ma dostać ZERO
    kandydatów, nie wszystkich — próg poszerza jednostkę porównania, nie uprawnienia."""
    assert exposure_matches(None, 90.0) is False
    assert exposure_matches(90.0, None) is False
    assert exposure_matches(None, None) is False


def test_master_bez_ekspozycji_konczy_na_oknie_zdegenerowanym(con):
    """Kryterium G2-7 („`exptime` mastera NULL ⇒ zero kandydatów") jest SPEŁNIONE, ale nie przez
    kod R3 — łapie to strażnik STARSZY: `testimony.degenerate` jest z definicji `True`, gdy nie ma
    czym ograniczyć doboru. Test pinuje ten podział, żeby nikt nie dorobił drugiego guardu na
    stan, do którego plan nie dochodzi (własny guard w `_plan` powstał i został zdjęty jako martwy).

    Powód `degenerate_window` jest przy tym UCZCIWSZY niż `no_candidates`: mówi, że nie wiadomo,
    czym wybierać, a nie że nie było z czego."""
    m = _master(con, exptime=None)
    _light(con, "s1", date_obs="2019-01-10T20:41:00", filetype="fits")
    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert s.inputs == 0
    assert _integracja(con, m)["unresolved_reason"] == "degenerate_window"


def test_prog_wpuszcza_wszystkie_trzy_suby_a_rownosc_wpuszczala_jeden(con):
    """Rachunek R3 co do sztuki na wzorcowym przypadku: `90,0` mastera wobec `90,0 / 91,0 / 91,0`.
    Falsyfikator jest w tym samym teście — klatka `94,0 s` (poza pasem) NIE wchodzi, więc zieleń
    nie może pochodzić z „próg wpuszcza wszystko"."""
    m = _master(con)
    subs = [_light(con, "s1", date_obs="2019-01-10T20:41:00", exptime=90.0, filetype="fits"),
            _light(con, "s2", date_obs="2019-01-10T20:43:00", exptime=91.0, filetype="fits"),
            _light(con, "s3", date_obs="2019-01-10T20:45:00", exptime=91.0, filetype="fits")]
    _light(con, "obce", date_obs="2019-01-10T20:47:00", exptime=94.0, filetype="fits")
    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert s.inputs == 3
    assert [r["input_frame_id"] for r in inputs_of(con, m)] == subs


# ============================================================ G2-8 · offset melduje się PRAWDĄ

def test_raw_bez_odniesienia_melduje_offset_unknown_a_nie_no_candidates(con):
    """Cała treść R2: kandydaci SĄ, tylko liczą w innym zegarze. `no_candidates` byłby nieprawdą
    i wysyłał człowieka szukać klatek, które leżą obok."""
    m = _master(con)
    _light(con, "s1", date_obs="2019-01-10T21:41:00")     # czas LOKALNY, +1 h wobec okna
    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert s.inputs == 0
    assert _integracja(con, m)["unresolved_reason"] == REASON_OFFSET_UNKNOWN
    assert s.reasons == {REASON_OFFSET_UNKNOWN: 1}


def test_brak_kandydatow_zostaje_brakiem_kandydatow(con):
    """Falsyfikator poprzedniego: bez materiału RAW powód się NIE zmienia. Bez tego testu
    `offset_unknown` mógłby zjeść cały kubełek `no_candidates` i nikt by nie zauważył."""
    m = _master(con)
    _light(con, "s1", date_obs="2019-02-20T21:41:00", filetype="fits")   # inna noc
    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert _integracja(con, m)["unresolved_reason"] == REASON_NO_CANDIDATES


def test_token_offset_unknown_jest_w_CHECK_bazy(con):
    """Baza jest OSTATNIĄ bramką słownika (kanon 0012/0014/0015): wstrzyknięcie z pominięciem
    klingi ma się odbić o CHECK. Test pilnuje obu stron — token legalny przechodzi, literówka nie."""
    m = _master(con)
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    iid = _integracja(con, m)["id"]

    con.execute("UPDATE integration SET unresolved_reason = 'offset_unknown' WHERE id = ?", (iid,))
    with pytest.raises(Exception):
        con.execute("UPDATE integration SET unresolved_reason = 'offset_unknow' WHERE id = ?",
                    (iid,))
    con.rollback()


def test_kazdy_powod_ma_recepte_w_OBU_powierzchniach():
    """ŚWIADEK KOMPLETU, nie kopia mapy (R-S3-7: drabina dwa razy z rzędu zapomniała o kolejnym
    kubełku). Źródłem prawdy jest CHECK migracji — bo to on rozstrzyga, jakie powody baza w ogóle
    dopuszcza — a nie lista wypisana w teście, którą trzeba pamiętać, żeby zaktualizować."""
    from horreum.cli import _STACK_REASON_PROZA
    from horreum.gui.i18n_catalog import CATALOG

    ddl = db._migration_sql("0016_integration_offset.sql")
    fragment = ddl.split("unresolved_reason IN (")[1].split("))")[0]
    powody = {s.strip().strip("',") for s in fragment.replace("\n", " ").split()}
    powody = {p for p in powody if p and not p.startswith("-")}

    assert len(powody) == 7, f"CHECK dopuszcza {sorted(powody)}"
    for powod in sorted(powody):
        assert powod in _STACK_REASON_PROZA, f"CLI milczy o powodzie {powod}"
        assert f"grid.lin.reason.{powod}" in CATALOG, f"GUI milczy o powodzie {powod}"


# ============================================================ G2-10 · ZNAK offsetu

@pytest.mark.parametrize("offset,czas_suba,wchodzi", [
    (60, "2019-01-10T21:41:00", True),      # IC443: lokalny = UTC + 60 min
    (120, "2019-01-10T22:41:00", True),     # LMC: +2 h
    (60, "2019-01-10T20:41:00", False),     # sub JUŻ w UTC → po odjęciu wypada przed okno
    (-60, "2019-01-10T19:41:00", True),     # offset UJEMNY też ma test (półkula zachodnia)
    (0, "2019-01-10T20:41:00", True),       # 0 to FAKT („to jest UTC"), nie brak
])
def test_znak_offsetu_liczony_w_obie_strony(con, offset, czas_suba, wchodzi):
    """Umowa `lokalny = UTC + offset`, więc kandydat wraca do zegara mastera przez ODJĘCIE.
    Test jedzie w obie strony, bo pomylony znak daje wynik POPRAWNY dla połowy przypadków."""
    m = _master(con)
    _light(con, "s1", date_obs=czas_suba)
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    repo.set_integration_offset(con, master_frame_id=m, utc_offset_min=offset, now=LATER)
    s = run_stack_lineage(con, now=LATER, xml_reader=_brak_xml)

    assert s.inputs == (1 if wchodzi else 0)


def test_zero_to_werdykt_a_nie_brak(con):
    """`0` i `NULL` to DWA RÓŻNE stany („to jest UTC" vs „nie wiem") — w Pythonie `0 == False`,
    więc pomyłka tu jest o jeden znak i cicha. Świadkiem jest POWÓD, nie sama kolumna."""
    m = _master(con)
    _light(con, "s1", date_obs="2019-01-10T21:41:00")           # lokalny, +1 h
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    assert _integracja(con, m)["unresolved_reason"] == REASON_OFFSET_UNKNOWN

    assert repo.set_integration_offset(con, master_frame_id=m, utc_offset_min=0, now=LATER) is True
    s = run_stack_lineage(con, now=LATER, xml_reader=_brak_xml)
    row = _integracja(con, m)
    assert row["utc_offset_min"] == 0
    # Odniesienie ZNANE, więc kandydat jest OSĄDZALNY — i tu akurat wchodzi, bo `21:41` leży
    # w oknie `20:40:38–21:45`. Świadkiem `0 ≠ NULL` jest samo przejście z „nie wiem" do werdyktu:
    # gdyby `0` czytało się jak brak, powód dalej brzmiałby `offset_unknown`.
    assert s.inputs == 1 and row["unresolved_reason"] is None


def test_klinga_odmawia_boola_i_wartosci_spoza_zegarow_swiata(con):
    """BRAMKA PAKIETU, zarzuty 4 i 5 — dwie drogi do zapisu nieodróżnialnego od poprawnego.

    `isinstance(True, int)` jest PRAWDĄ, więc `False` przechodziło walidację i lądowało w bazie
    jako `0`, czyli jako werdykt „to jest UTC" — dokładnie ta kolizja, którą klinga deklaruje
    rozróżniać.

    ZAKRES JEST BRAMKĄ NA NONSENS, NIE NA POMYŁKĘ — i test pinuje właśnie tę granicę, żeby nikt
    nie wziął jej za większą, niż jest: `6000` odpada, ale `600` (przykład z recenzji, „zamiast
    60") PRZECHODZI, bo dziesięć godzin to legalna strefa. Ostatnia asercja stoi tu po to, by
    ta prawda była w bateri, a nie tylko w komentarzu."""
    m = _master(con)
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    for zly in (True, False):
        with pytest.raises(ValueError):
            repo.set_integration_offset(con, master_frame_id=m, utc_offset_min=zly, now=NOW)
    for zly in (841, -841, 6000):
        with pytest.raises(ValueError):
            repo.set_integration_offset(con, master_frame_id=m, utc_offset_min=zly, now=NOW)

    # Granice zegarów świata PRZECHODZĄ — bramka odsiewa nonsens, nie realne strefy.
    assert repo.set_integration_offset(con, master_frame_id=m, utc_offset_min=840, now=NOW) is True
    assert repo.set_integration_offset(con, master_frame_id=m, utc_offset_min=-720, now=NOW) is True
    assert repo.set_integration_offset(con, master_frame_id=m, utc_offset_min=345, now=NOW) is True
    assert repo.set_integration_offset(con, master_frame_id=m, utc_offset_min=600, now=NOW) is True, \
        "literówka dająca wartość fizycznie możliwą PRZECHODZI — zakres jej nie łapie i nie udaje"


def test_gest_offsetu_podbija_znacznik_modyfikacji(con):
    """BRAMKA PAKIETU, zarzut 8: głowa integracji drga gestem człowieka, więc `updated_at` musi
    iść razem z wartością. Wcześniej kolumna zostawała z czasem ostatniego PRZEBIEGU — ślad
    niósł tylko dziennik, a kolumna pokazywała nieprawdę."""
    m = _master(con)
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    repo.set_integration_offset(con, master_frame_id=m, utc_offset_min=60, now=LATER)

    assert _integracja(con, m)["updated_at"] == LATER


def test_raw_z_innej_nocy_NIE_daje_recepty_o_odniesieniu(con):
    """BRAMKA PAKIETU, zarzut 3 — fałszywa recepta jest gorsza niż `no_candidates`.

    RAW o zgodnej ekspozycji, ale z INNEJ NOCY, nabijał licznik świadków bez odniesienia, więc
    stos dostawał `offset_unknown` i zdanie „wskaż odniesienie" — gest, który nie miał prawa nic
    zmienić, bo fizyczny sufit zegarów (±14 h) wykluczał tego kandydata z góry."""
    m = _master(con)
    _light(con, "daleki", date_obs="2019-03-20T21:40:38")     # dwa miesiące później
    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert _integracja(con, m)["unresolved_reason"] == REASON_NO_CANDIDATES
    assert s.reasons == {REASON_NO_CANDIDATES: 1}


def test_propozycja_odrzuca_swiadka_z_innej_doby(con):
    """BRAMKA PAKIETU, zarzut 7: sama podzielność przez 60 przepuszczała 1500 minut, czyli klatkę
    z następnej doby o trafionym `mm:ss` — jeden zbieg dawał propozycję fałszywą o całą dobę."""
    m = _master(con)
    _light(con, "doba", date_obs="2019-01-11T21:40:38")       # +25 h, mm:ss trafione
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert stacks_propose(con, m) is None


def test_klinga_offsetu_jest_idempotentna_i_odmawia_nie_stosowi(con):
    m = _master(con)
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert repo.set_integration_offset(con, master_frame_id=m, utc_offset_min=60, now=NOW) is True
    assert repo.set_integration_offset(con, master_frame_id=m, utc_offset_min=60, now=LATER) is False
    zdarzenia = con.execute(
        "SELECT count(*) FROM event WHERE verb = 'integration.offset_set'").fetchone()[0]
    assert zdarzenia == 1, "powtórzony gest nie ma prawa zaśmiecać dziennika"

    with pytest.raises(ValueError):
        repo.set_integration_offset(con, master_frame_id=999, utc_offset_min=60, now=NOW)
    with pytest.raises(ValueError):
        repo.set_integration_offset(con, master_frame_id=m, utc_offset_min="60", now=NOW)


# ================================================== PROPOZYCJA odniesienia (świadek = okno mastera)

def test_propozycja_czyta_podpis_dwoch_zegarow(con):
    """Podpis to zgodność `mm:ss` przy różnicy PEŁNYCH godzin. Na kopii żywego archiwum trafia
    7 z 7 stosów DSLR i ZERO ze 121 pozostałych — drugi człon jest tu falsyfikatorem, bo
    propozycja, która trafia wszędzie, nie jest świadkiem."""
    m = _master(con)                                     # okno startuje 20:40:38
    _light(con, "s1", date_obs="2019-01-10T21:40:38")    # ten sam mm:ss, +1 h
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert stacks_propose(con, m) == 60


def test_propozycja_milczy_gdy_podpisu_nie_ma(con):
    """Trzy sposoby, na które świadek może nie zeznać — i we wszystkich milczenie jest uczciwsze
    niż środek: brak podpisu (`mm:ss` się różnią), materiał NIE-RAW (inny zegar nie wchodzi w grę)
    oraz świadkowie NIEZGODNI (dwie różne różnice godzin — propozycja z nich byłaby zgadywaniem
    podanym jako pomiar)."""
    m = _master(con)
    _light(con, "a", date_obs="2019-01-10T21:41:07")     # mm:ss inne niż okno
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    assert stacks_propose(con, m) is None

    _light(con, "b", date_obs="2019-01-10T22:40:38", filetype="fits")   # podpis, ale nie RAW
    assert stacks_propose(con, m) is None

    _light(con, "c", date_obs="2019-01-10T21:40:38")     # +1 h
    _light(con, "d", date_obs="2019-01-10T22:40:38")     # +2 h — świadkowie się kłócą
    assert stacks_propose(con, m) is None


# ============================================================ G2-11 · okno mastera NIETKNIĘTE

def test_przesuwa_sie_kandydat_nigdy_okno_mastera(con):
    """Okno idzie do bazy jako zapis tego, co zeznał PLIK. Gdyby offset przesuwał okno, każdy
    kolejny przebieg przesuwałby je ponownie — fakt o pliku zamieniłby się w dryf."""
    m = _master(con)
    _light(con, "s1", date_obs="2019-01-10T21:41:00")
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    okno_przed = (_integracja(con, m)["window_start"], _integracja(con, m)["window_end"])

    repo.set_integration_offset(con, master_frame_id=m, utc_offset_min=60, now=LATER)
    s = run_stack_lineage(con, now=LATER, xml_reader=_brak_xml)

    assert s.inputs == 1, "kandydat MA wejść — inaczej test niczego nie dowodzi"
    assert (_integracja(con, m)["window_start"], _integracja(con, m)["window_end"]) == okno_przed


# ============================================================ G2-12 · offset PRZEŻYWA przebieg

def test_offset_przezywa_dwa_przebiegi_rodowodu(con):
    """Pole jest POZA literalną listą `upsert_integration` — świadomie (0016). Bez tego pierwszy
    „Przetwórz wszystko" po geście zdejmowałby werdykt człowieka do NULL, dokładnie jak automat
    zamalowywał ręczny config przed R1b."""
    m = _master(con)
    _light(con, "s1", date_obs="2019-01-10T21:41:00")
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    repo.set_integration_offset(con, master_frame_id=m, utc_offset_min=60, now=LATER)

    for _ in range(2):
        run_stack_lineage(con, now=LATER, xml_reader=_brak_xml)
    assert _integracja(con, m)["utc_offset_min"] == 60


# ================================================== półka nierozłączności · nieprzechodniość progu

def test_polka_porownuje_ekspozycje_parami_nie_kluczem(con):
    """`exptime` wypadło z klucza półki (R3), więc nierozłączność musi je sprawdzać PARAMI.
    Dwa mastery o zachodzących oknach: `90,0` i `91,0` są jedną nastawą (flaga), `90,0` i `120,0`
    nie są (brak flagi) — a oba przypadki lądują dziś w TYM SAMYM wiadrze klucza."""
    bliski = _master(con, "mA", exptime=90.0, path=STOS + "A")
    daleki = _master(con, "mB", exptime=91.0, path=STOS + "B")
    obcy = _master(con, "mC", exptime=120.0, path=STOS + "C")
    _light(con, "s1", date_obs="2019-01-10T20:41:00", exptime=90.0, filetype="fits")
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert _integracja(con, bliski)["ambiguous"] == 1
    assert _integracja(con, daleki)["ambiguous"] == 1
    assert _integracja(con, obcy)["ambiguous"] == 0


# ============================================================ nadzbiór SQL ⊇ werdykt Pythona

def test_pas_sql_jest_nadzbiorem_progu():
    """Kontrakt, na którym stoi rozdział „SQL zawęża, Python rozstrzyga": żadna para zgodna progiem
    nie może wypaść z pasa `± sufit`. Gdyby sufit kiedyś urósł ponad pas, dobór milczkiem
    chudnie — a to jedyne miejsce, gdzie oba fakty stoją obok siebie."""
    for a in (0.5, 10.0, 90.0, 600.0, 3600.0):
        for delta in (0.0, 0.4, 0.6, 1.0, 2.9, 3.0, 3.1, 12.0):
            if exposure_matches(a, a + delta):
                assert delta <= EXP_TOL_CEILING_S


# ============================================ G2-1d · pula MIESZANA nie ucisza RAW-ów

def _zdarzenia_zapisu(con):
    return con.execute("SELECT count(*) FROM event WHERE verb IN ('integration.recorded', "
                       "'integration.updated', 'integration.linked', "
                       "'integration.unlinked')").fetchone()[0]


def test_pula_mieszana_daje_rodowod_Z_UWAGA_o_RAW_ach_bez_zegara(con):
    """Okno domyka się z FITS-ów, a obok stoją RAW-y tej samej serii w zegarze aparatu. Do G2-1d
    trzecia wartość `_in_window` nie miała wtedy czytelnika i RAW-y milkły; teraz stos dostaje
    rodowód ORAZ uwagę „a tych dwóch nie umiem umieścić w czasie". Werdykt zostaje pusty -
    uwaga niczego w nim nie zmienia, więc perspektywy i liczniki czytające `unresolved_reason`
    widzą ten sam stan co przed zmianą.

    Druga połowa: powtórka na niezmienionych danych = zero wierszy i zero zdarzeń zapisu (uwaga
    stoi w porównaniu kompletu faktów klingi). Trzecia: po wskazaniu zegara RAW-y wchodzą do
    rodowodu, a uwaga GAŚNIE (NULL, nie zero - brak uwagi ma jedną postać, CHECK 0020).

    Falsyfikator: usuń `raw_unreferenced=` z wołania `upsert_integration` w `run_stack_lineage`
    → pierwsza asercja uwagi czerwienieje."""
    m = _master(con)
    fits = [_light(con, "f1", date_obs="2019-01-10T20:41:00", filetype="fits"),
            _light(con, "f2", date_obs="2019-01-10T20:43:00", filetype="fits")]
    raw = [_light(con, "r1", date_obs="2019-01-10T21:45:00"),       # lokalny, +1 h wobec okna
           _light(con, "r2", date_obs="2019-01-10T21:47:00")]
    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    row = _integracja(con, m)
    assert row["unresolved_reason"] is None and s.reasons == {}
    assert [r["input_frame_id"] for r in inputs_of(con, m)] == fits
    assert row["raw_unreferenced"] == 2, "RAW-y bez zegara mają przemówić obok rodowodu"

    wiersze = con.execute("SELECT count(*) FROM integration_input").fetchone()[0]
    przed = _zdarzenia_zapisu(con)
    run_stack_lineage(con, now=LATER, xml_reader=_brak_xml)
    assert (con.execute("SELECT count(*) FROM integration_input").fetchone()[0],
            _zdarzenia_zapisu(con)) == (wiersze, przed)

    repo.set_integration_offset(con, master_frame_id=m, utc_offset_min=60, now=LATER)
    run_stack_lineage(con, now=LATER, xml_reader=_brak_xml)
    assert _integracja(con, m)["raw_unreferenced"] is None
    assert [r["input_frame_id"] for r in inputs_of(con, m)] == sorted(fits + raw)


def test_werdykt_offset_unknown_NIE_dostaje_uwagi_obok(con):
    """Gdy RAW-y bez zegara SĄ werdyktem (`offset_unknown`), uwaga byłaby dublem tego samego
    zdania - panel powiedziałby je dwa razy. Kod zostawia ją pustą, a CHECK 0020 odbija wstrzyk
    z pominięciem klingi (test schematu)."""
    m = _master(con)
    _light(con, "r1", date_obs="2019-01-10T21:41:00")
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    row = _integracja(con, m)
    assert row["unresolved_reason"] == REASON_OFFSET_UNKNOWN
    assert row["raw_unreferenced"] is None
