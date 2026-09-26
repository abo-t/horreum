"""PROPOZYCJA MATERIAŁU dla stosu bez rodowodu (`stacks.propose_lineage_candidates`, 0808).

Powstała z pomiaru, nie z pomysłu: 30 stosów archiwum ma okno ZDEGENEROWANE (`DATE-END` opisuje
jedną klatkę zamiast serii), więc automat nie ma czym wybierać, a panel „Rodowód" umiał do tej
zmiany tylko wytłumaczyć, dlaczego milczy. Reguła zamienia zepsuty koniec okna na NOC
OBSERWACYJNĄ, zostawiając nietknięte wszystkie osie zgodności doboru.

Decyzja Zdzinia 0808 („noc mastera + wybór innej nocy") jest tu pinowana wprost: noc obrazu wchodzi
na listę ZAWSZE, także pusta — 5 stosów archiwum nie ma materiału w swojej nocy, choć ich obiekty
mają go setki w innych.
"""
import json

import pytest

from horreum import db, repo
from horreum.stacks import propose_lineage_candidates

NOW = "2026-08-08T12:00:00+00:00"


@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "h.db"))
    c.execute("INSERT INTO camera(model_canon, created_at) VALUES ('ASI2600', ?)", (NOW,))
    c.execute("INSERT INTO telescope(telescop_canon, status, created_at) VALUES ('RC8R', "
              "'proposed', ?)", (NOW,))
    c.execute("INSERT INTO telescope(telescop_canon, status, created_at) VALUES ('ED120R', "
              "'proposed', ?)", (NOW,))
    c.execute("INSERT INTO config(telescope_id, camera_id, status, created_at) "
              "VALUES (1, 1, 'proposed', ?)", (NOW,))
    c.execute("INSERT INTO config(telescope_id, camera_id, status, created_at) "
              "VALUES (2, 1, 'proposed', ?)", (NOW,))
    c.execute("INSERT INTO object(canon, catalog, kind) VALUES ('M82', 'catalog', 'deep_sky')")
    c.commit()
    yield c
    c.close()


def _light(con, sha1, *, date_obs, exptime=300.0, filetype="fits", filter_canon="Ha",
           config_id=1, object_id=1):
    cur = con.execute(
        "INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, "
        "filter_canon, first_seen_at) VALUES (?, 'light', ?, 1, ?, ?, ?, ?)",
        (sha1, filetype, config_id, object_id, filter_canon, NOW))
    fid = cur.lastrowid
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, exptime, ccd_temp) "
                "VALUES (?, '{}', ?, ?, NULL)", (fid, date_obs, exptime))
    con.commit()
    return fid


def _master(con, *, start="2023-04-21T20:00:00", exptime=300.0, object_id=1,
            filter_canon="Ha", config_id=1):
    """Master z oknem ZDEGENEROWANYM (koniec = początek + jedna ekspozycja) — populacja, dla której
    ta propozycja powstała."""
    koniec = "2023-04-21T20:05:00"
    raw = {"IMAGETYP": "Master Light", "OBJECT": "M82", "EXPTIME": exptime,
           "DATE-OBS": start, "DATE-END": koniec}
    cur = con.execute(
        "INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, "
        "filter_canon, first_seen_at) VALUES ('m1', 'master_light', 'xisf', 1, ?, ?, ?, ?)",
        (config_id, object_id, filter_canon, NOW))
    fid = cur.lastrowid
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, exptime) VALUES (?, ?, ?, ?)",
                (fid, json.dumps(raw), start, exptime))
    con.execute("INSERT INTO location(frame_id, volume, path, present) "
                "VALUES (?, 'V', 'R:\\m\\masterLight_M82.xisf', 1)", (fid,))
    con.commit()
    return fid


def _integracja(con, master_frame_id, *, reason="degenerate_window"):
    iid, _ = repo.upsert_integration(
        con, master_frame_id=master_frame_id, integ_hash=None, tool=None,
        window_start="2023-04-21T20:00:00", window_end="2023-04-21T20:05:00",
        declared_rows=None, drizzle_inputs=None, disabled_inputs=None, degenerate=1,
        ambiguous=0, telescope_mismatch=0, unresolved_reason=reason, now=NOW)
    return iid


def test_noc_mastera_zbiera_material_ktorego_okno_nie_umialo_wybrac(con):
    """Sedno reguły: okno zdegenerowane opisuje 5 minut, a sesja trwała całą noc. Klatki tej nocy
    (także te PO fałszywym końcu okna) wchodzą do propozycji, bo zepsuty jest KONIEC, nie początek."""
    fid = _master(con)
    _integracja(con, fid)
    for i, godz in enumerate(("20:00:00", "21:30:00", "23:59:00")):
        _light(con, f"s{i}", date_obs=f"2023-04-21T{godz}")
    noce, _ = propose_lineage_candidates(con, fid)
    assert len(noce) == 1
    assert noce[0].master_night is True and noce[0].night == "2023-04-21"
    assert len(noce[0].frames) == 3


def test_noc_przechodzi_przez_polnoc(con):
    """Doba obserwacyjna tnie się o POŁUDNIU: klatka z 01:00 należy do wieczoru poprzedniego dnia.
    Podział o północy rozbiłby jedną sesję na dwie pozycje listy i kazał człowiekowi kliknąć dwa
    razy w to, co widział jako jedną noc."""
    fid = _master(con)
    _integracja(con, fid)
    _light(con, "wieczor", date_obs="2023-04-21T22:00:00")
    _light(con, "po_polnocy", date_obs="2023-04-22T01:30:00")
    noce, _ = propose_lineage_candidates(con, fid)
    assert len(noce) == 1 and len(noce[0].frames) == 2


def test_noc_mastera_wchodzi_TAKZE_pusta_a_reszta_po_odleglosci(con):
    """Decyzja Zdzinia 0808 i pomiar 5 stosów `no_candidates`: obraz mówi o nocy, w której archiwum
    nie ma nic, a materiał leży w sąsiednich. Pusta noc obrazu zostaje PIERWSZA (to o nią pytał
    użytkownik), reszta ustawia się po ODLEGŁOŚCI od niej — sesja sprzed dnia jest kandydatem
    mocniejszym niż sprzed roku."""
    fid = _master(con)
    _integracja(con, fid, reason="no_candidates")
    _light(con, "rok_wczesniej", date_obs="2022-04-21T22:00:00")
    _light(con, "dzien_pozniej", date_obs="2023-04-22T22:00:00")
    noce, _ = propose_lineage_candidates(con, fid)
    assert [n.night for n in noce] == ["2023-04-21", "2023-04-22", "2022-04-21"]
    assert noce[0].master_night is True and noce[0].frames == ()
    assert len(noce[1].frames) == 1 and len(noce[2].frames) == 1


def test_osie_zgodnosci_te_same_co_w_doborze(con):
    """Propozycja bez osi doboru nie byłaby propozycją, tylko spisem klatek obiektu. Filtr,
    ekspozycja, teleskop i obiekt odsiewają tak samo jak w oknie — inaczej lista kazałaby
    człowiekowi robić ręcznie tę robotę, którą maszyna umie."""
    fid = _master(con)
    _integracja(con, fid)
    _light(con, "dobra", date_obs="2023-04-21T20:00:00")
    _light(con, "inny_filtr", date_obs="2023-04-21T20:10:00", filter_canon="OIII")
    _light(con, "inna_ekspozycja", date_obs="2023-04-21T20:20:00", exptime=60.0)
    _light(con, "inny_teleskop", date_obs="2023-04-21T20:30:00", config_id=2)
    con.execute("INSERT INTO object(canon, catalog, kind) VALUES ('M81','catalog','deep_sky')")
    _light(con, "inny_obiekt", date_obs="2023-04-21T20:40:00", object_id=2)
    noce, _ = propose_lineage_candidates(con, fid)
    assert len(noce) == 1 and len(noce[0].frames) == 1
    assert noce[0].frames[0]["frame_id"] == con.execute(
        "SELECT id FROM frame WHERE sha1_data = 'dobra'").fetchone()[0]


def test_klatka_JUZ_OSADZONA_nie_wraca_jako_propozycja(con):
    """Werdykt „to NIE jest materiał tego obrazu" ma zostać werdyktem. Lista, która przywraca
    odrzuconego kandydata przy każdym otwarciu panelu, kazałaby wydawać ten sam werdykt w kółko —
    i tak samo nie ma po co proponować tego, co człowiek już potwierdził."""
    fid = _master(con)
    iid = _integracja(con, fid)
    potwierdzona = _light(con, "tak", date_obs="2023-04-21T20:00:00")
    odrzucona = _light(con, "nie", date_obs="2023-04-21T20:10:00")
    _light(con, "nietknieta", date_obs="2023-04-21T20:20:00")
    repo.judge_integration_input(con, integration_id=iid, input_frame_id=potwierdzona,
                                 excluded=False, now=NOW)
    repo.judge_integration_input(con, integration_id=iid, input_frame_id=odrzucona,
                                 excluded=True, now=NOW)
    noce, _ = propose_lineage_candidates(con, fid)
    assert [r["frame_id"] for n in noce for r in n.frames] == [
        con.execute("SELECT id FROM frame WHERE sha1_data = 'nietknieta'").fetchone()[0]]


def test_bez_obiektu_i_bez_ekspozycji_NIE_zgadujemy(con):
    """Zmierzone: 1 stos z 35 nie ma czym się przedstawić. Milczenie jest tu odpowiedzią —
    propozycja bez osi zgodności byłaby spisem archiwum podanym jako materiał obrazu."""
    fid = _master(con, object_id=None)
    _integracja(con, fid)
    _light(con, "s0", date_obs="2023-04-21T20:00:00")
    assert propose_lineage_candidates(con, fid) == ((), 0)

    con.execute("UPDATE frame SET object_id = 1 WHERE id = ?", (fid,))
    con.execute("UPDATE header SET raw_json = ? WHERE frame_id = ?",
                (json.dumps({"IMAGETYP": "Master Light", "DATE-OBS": "2023-04-21T20:00:00"}), fid))
    con.commit()
    assert propose_lineage_candidates(con, fid) == ((), 0), \
        "bez EXPTIME nie ma czym ograniczyć doboru"


def test_RAW_bez_odniesienia_nie_wchodzi_a_z_odniesieniem_ladzie_we_wlasciwej_nocy(con):
    """Granica przeniesiona wprost z `_in_window`: EXIF niesie czas LOKALNY, XISF UTC. Bez
    odniesienia nie wiadomo, do której NOCY taka klatka należy, a zgadnięcie doby jest gorsze niż
    milczenie — ze wskazanym odniesieniem RAW wraca i ląduje tam, gdzie naprawdę był."""
    fid = _master(con)
    _integracja(con, fid)
    _light(con, "raw", date_obs="2023-04-22T01:30:00", filetype="raw")
    noce, _ = propose_lineage_candidates(con, fid)
    assert noce[0].frames == ()

    repo.set_integration_offset(con, master_frame_id=fid, utc_offset_min=120, now=NOW)
    noce, _ = propose_lineage_candidates(con, fid)
    assert len(noce) == 1 and len(noce[0].frames) == 1, \
        "01:30 lokalnego = 23:30 UTC — ta sama noc, co obraz"


def test_RAW_bez_odniesienia_NIE_PRZEPADA_PO_CICHU_tylko_wraca_druga_wartoscia(con):
    """Bramka pakietu 3a (0808), zarzut BLOKUJĄCY — i to jest cała jego treść: pominięcie RAW-a
    przepisano z `_in_window`, ale JEGO DRUGĄ POŁOWĘ (licznik) już nie. Skutek zmierzony na żywym
    archiwum: 6 z 35 obrazów kubełka dostawało pustą listę pod zdaniem „archiwum nie ma ani jednej
    klatki tego obiektu", gdy stało w nim po 36 kandydatów przechodzących KAŻDĄ oś zgodności.

    „Kandydaci są, tylko liczą w innym zegarze" to inna recepta niż „kandydatów nie ma" — a tej
    różnicy nie da się wypowiedzieć bez liczby."""
    fid = _master(con)
    _integracja(con, fid)
    for i, godz in enumerate(("20:00:00", "21:00:00", "22:00:00")):
        _light(con, f"raw{i}", date_obs=f"2023-04-21T{godz}", filetype="raw")
    _light(con, "fits", date_obs="2023-04-21T23:00:00")

    noce, bez_zegara = propose_lineage_candidates(con, fid)
    assert bez_zegara == 3, "trzy RAW-y wypadły z listy i mają być POLICZONE, nie przemilczane"
    assert [r["frame_id"] for n in noce for r in n.frames] == [
        con.execute("SELECT id FROM frame WHERE sha1_data = 'fits'").fetchone()[0]], \
        "FITS-a zegar nie dotyczy — wchodzi normalnie"

    # Po wskazaniu odniesienia licznik gaśnie, bo pytanie przestało istnieć.
    repo.set_integration_offset(con, master_frame_id=fid, utc_offset_min=120, now=NOW)
    noce, bez_zegara = propose_lineage_candidates(con, fid)
    assert bez_zegara == 0
    assert sum(len(n.frames) for n in noce) == 4


# ================================ B3a-2 · oś teleskopu w PROPOZYCJI = ta sama reguła co w DOBORZE

def _karta_smieciowa(con):
    """Teleskop-śmieć z realnego archiwum (`EQMOD HEQ5/6` = nazwa MONTAŻU) i jego zestaw (id 3)."""
    con.execute("INSERT INTO telescope(telescop_canon, status, created_at) "
                "VALUES ('EQMOD HEQ5/6', 'proposed', ?)", (NOW,))
    con.execute("INSERT INTO config(telescope_id, camera_id, status, created_at) "
                "VALUES (3, 1, 'proposed', ?)", (NOW,))
    con.commit()
    return 3


def test_karta_smieciowa_dostaje_material_nocy_mastera_z_rozjazdem(con):
    """Gałąź środkowa reguły (`stacks._telescope_rule`): noc mastera JEDNORODNA, ale z innego
    teleskopu niż karta → materiał wchodzi i niesie rozjazd, żeby panel wskazał kartę do naprawy.
    Odsiew per klatkę pokazywał tu pustkę - master z kartą-śmieciem nie miał czym się naprawić.

    INNA NOC tego samego teleskopu NIE wchodzi: gałąź środkowa stoi na „drugim zeznaniu o tej samej
    nocy", a inna noc tej przesłanki nie ma.

    Falsyfikator: przywróć w `propose_lineage_candidates` odsiew `telescope_id` per klatkę przed
    podziałem na noce → noc mastera wraca pusta i bez rozjazdu."""
    fid = _master(con, config_id=_karta_smieciowa(con))
    _integracja(con, fid)
    seria = [_light(con, f"ed{i}", date_obs=f"2023-04-21T2{i}:00:00", config_id=2)
             for i in range(3)]
    _light(con, "ed_inna_noc", date_obs="2023-04-25T21:00:00", config_id=2)
    noce, _ = propose_lineage_candidates(con, fid)

    assert len(noce) == 1 and noce[0].master_night
    assert [r["frame_id"] for r in noce[0].frames] == seria
    assert noce[0].telescope_mismatch is True


def test_noc_mastera_MIESZANA_bez_teleskopu_mastera_jest_pusta_z_rozjazdem(con):
    """Gałąź trzecia: noc miesza dwa obce teleskopy i żaden nie jest masterowy - nie ma czym
    rozstrzygnąć, więc lista milczy, ale rozjazd zostaje (kandydaci BYLI, odrzuciła ich oś -
    lustro powodu `telescope_mismatch` w doborze)."""
    fid = _master(con, config_id=_karta_smieciowa(con))
    _integracja(con, fid)
    _light(con, "rc8", date_obs="2023-04-21T20:00:00", config_id=1)
    _light(con, "ed", date_obs="2023-04-21T21:00:00", config_id=2)
    noce, _ = propose_lineage_candidates(con, fid)

    assert len(noce) == 1 and noce[0].frames == ()
    assert noce[0].telescope_mismatch is True


def test_poprawna_karta_NIE_dostaje_rozjazdu_z_obcej_nocy(con):
    """Regresja, której reguła puszczona na KAŻDĄ noc by nie przeżyła: obiekt fotografowany przez
    lata dwoma teleskopami. Noc innego teleskopu nie jest ofertą dla mastera z poprawną kartą,
    a noc mastera - z klatkami jego teleskopu - nie niesie rozjazdu."""
    fid = _master(con)                                    # karta RC8R, poprawna
    _integracja(con, fid)
    wlasna = _light(con, "rc8", date_obs="2023-04-21T20:00:00", config_id=1)
    _light(con, "ed_obok", date_obs="2023-04-21T20:30:00", config_id=2)
    _light(con, "ed_rok_pozniej", date_obs="2024-04-21T21:00:00", config_id=2)
    noce, _ = propose_lineage_candidates(con, fid)

    assert [(n.night, [r["frame_id"] for r in n.frames], n.telescope_mismatch)
            for n in noce] == [("2023-04-21", [wlasna], False)]
