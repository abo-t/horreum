"""KURATELA CELÓW + PARK (planer T4): migracja 0011, klinga `repo`, odczyt parku i szew z `plan()`.

Dwa fakty o PRZYSZŁOŚCI wstawione do bazy, która zeznaje PRZESZŁOŚĆ — stąd nacisk testów na to,
czego NIE wolno zderywować: brak oznaczeń NIE znaczy „park pusty", a `skip` nie ma prawa zasłonić
odpowiedzi na pytanie wprost (`--find`).

Meta-testów nie kopiujemy — `test_repo_safety`/`test_gui_isolation` chodzą po `rglob` i kryją nowy
kod same (kanon T1 §7).
"""
import sqlite3
from datetime import date

import pytest

from horreum import cli, db, repo, sky, targets

NOW = "2026-07-31T12:00:00+00:00"


# ─────────────────────────────────────────────────────────────── migracja 0011

def test_migracja_zaklada_kuratele_i_park(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    # Bez literału wersji: właścicielem pinu liczby jest `test_schema.test_user_version_v*`
    # (SPOT). Tu sprawdzamy to, o czym ten test naprawdę jest — że `open_db` domigrowuje do końca
    # łańcucha i że 0011 w tym łańcuchu jest. Zduplikowany literał kazałby podnosić dwa miejsca.
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 11
    assert con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='target_plan'"
                       ).fetchone() is not None
    assert "in_park" in {r[1] for r in con.execute("PRAGMA table_info(telescope)")}
    con.close()


def test_slownik_statusow_trzyma_baza_nie_kod(tmp_path):
    """CHECK w DDL jest OSTATNIĄ bramką — przeżyje każdą powierzchnię, także tę napisaną jutro."""
    con = db.open_db(str(tmp_path / "h.db"))
    con.execute("INSERT INTO target_plan(canon, status, created_at, updated_at) "
                "VALUES ('NGC7000', 'planned', ?, ?)", (NOW, NOW))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO target_plan(canon, status, created_at, updated_at) "
                    "VALUES ('NGC6992', 'kiedys-tam', ?, ?)", (NOW, NOW))
    with pytest.raises(sqlite3.IntegrityError):          # ten sam cel dwa razy = jeden wiersz
        con.execute("INSERT INTO target_plan(canon, status, created_at, updated_at) "
                    "VALUES ('NGC7000', 'done', ?, ?)", (NOW, NOW))
    con.close()


def test_0011_na_bazie_z_danymi_nie_gubi_teleskopow(tmp_path):
    """Migracja PRZYROSTOWA na żywym archiwum: wiersze osi przeżywają, park startuje jako NULL
    (nie 0!) — „użytkownik nic nie powiedział" to inny stan niż „odrzucił"."""
    path = str(tmp_path / "h.db")
    con = db.connect(path)
    for v in ("0002_initial.sql", "0003_writeback.sql", "0004_observatory.sql", "0005_rename.sql",
              "0006_unreadable.sql", "0007_backup_hdu_nullable.sql", "0008_calibration.sql",
              "0009_calibration_lineage.sql", "0010_kind_source.sql"):
        con.executescript(db._migration_sql(v))
    con.execute("PRAGMA user_version = 10")
    for tel in ("A140R", "ED120R"):
        con.execute("INSERT INTO telescope(telescop_canon, status, created_at) VALUES (?, ?, ?)",
                    (tel, "proposed", NOW))
    con.commit()
    con.close()

    con = db.open_db(path)                                   # v10 → v11
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    rows = con.execute("SELECT telescop_canon, in_park FROM telescope ORDER BY id").fetchall()
    assert [(r["telescop_canon"], r["in_park"]) for r in rows] == [("A140R", None),
                                                                   ("ED120R", None)]
    con.close()


# ─────────────────────────────────────────────────────────────── klinga DB

@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "h.db"))
    c.execute("INSERT INTO camera(model_canon, pixel_um, is_mono, created_at) "
              "VALUES ('ASI2600MM', 3.76, 1, ?)", (NOW,))
    c.execute("INSERT INTO camera(model_canon, pixel_um, is_mono, created_at) "
              "VALUES ('ASI2600MC', 3.76, 0, ?)", (NOW,))
    for tel in ("A140R", "RC8", "ED120R"):
        c.execute("INSERT INTO telescope(telescop_canon, status, created_at) VALUES (?, ?, ?)",
                  (tel, "proposed", NOW))
    for tel_id, cam_id in ((1, 1), (2, 1), (3, 1)):        # A140R×MM, RC8×MM, ED120R×MM
        c.execute("INSERT INTO config(telescope_id, camera_id, status, created_at) "
                  "VALUES (?, ?, 'proposed', ?)", (tel_id, cam_id, NOW))
    c.execute("INSERT INTO observatory(name, lat, lon, status, created_at) "
              "VALUES ('Będargowo', 53.3890, 14.4424, 'proposed', ?)", (NOW,))
    c.commit()          # zapisy usera biorą BEGIN IMMEDIATE — otwarta transakcja fixture'u by je zablokowała
    yield c
    c.close()


def _light(con, *, config_id, sha1, focal, camera_id=1, object_id=None, filter_canon=None,
           exptime=600.0, observatory_id=1):
    con.execute("INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, "
                "filter_canon, observatory_id, first_seen_at) "
                "VALUES (?, 'light', 'fits', ?, ?, ?, ?, ?, ?)",
                (sha1, camera_id, config_id, object_id, filter_canon, observatory_id, NOW))
    fid = con.execute("SELECT id FROM frame WHERE sha1_data = ?", (sha1,)).fetchone()["id"]
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, focallen, xpixsz, exptime) "
                "VALUES (?, ?, '2026-01-02T22:00:00', ?, 3.76, ?)",
                (fid, '{"NAXIS1": 6248, "NAXIS2": 4176}', focal, exptime))
    con.commit()
    return fid


def _park_ready(con):
    """Trzy zestawy o RÓŻNYCH ogniskowych — park ma mieć co ograniczać."""
    for cfg, focal in ((1, 784.0), (2, 1600.0), (3, 789.0)):
        for i in range(4):
            _light(con, config_id=cfg, sha1=f"c{cfg}-{i}", focal=focal)


def _events(con, verb):
    return con.execute("SELECT payload FROM event WHERE verb = ? ORDER BY id", (verb,)).fetchall()


def test_oznaczenie_celu_i_idempotencja(con):
    assert repo.set_target_plan(con, canon="NGC7000", status="planned", priority=2,
                                note="domknac SII", now=NOW) is True
    row = con.execute("SELECT * FROM target_plan WHERE canon = 'NGC7000'").fetchone()
    assert (row["status"], row["priority"], row["note"]) == ("planned", 2, "domknac SII")
    # ten sam komplet → BEZ drugiego eventu (przeklikanie w GUI nie puchnie dziennika)
    assert repo.set_target_plan(con, canon="NGC7000", status="planned", priority=2,
                                note="domknac SII", now=NOW) is False
    assert len(_events(con, "target_plan.set")) == 1
    # zmiana samej noty JEST zmianą
    assert repo.set_target_plan(con, canon="NGC7000", status="planned", priority=2,
                                note="inna", now=NOW) is True
    ev = _events(con, "target_plan.set")
    assert len(ev) == 2
    assert '"before": null' in ev[0]["payload"]              # założenie odróżnialne od zmiany
    assert '"note": "domknac SII"' in ev[1]["payload"]       # payload niesie stan SPRZED


def test_status_spoza_slownika_nie_przechodzi_klinga(con):
    with pytest.raises(sqlite3.IntegrityError):
        repo.set_target_plan(con, canon="NGC7000", status="moze-kiedys", now=NOW)


def test_zdjecie_oznaczenia_kasuje_ale_niesie_caly_wiersz(con):
    """DELETE na tabeli TRWAŁEJ jest świadomym precedensem — dlatego event MUSI nieść komplet,
    inaczej „bieżąca lista życzeń" kupowana jest utratą historii."""
    repo.set_target_plan(con, canon="CTB1", status="active", priority=1, note="60 h", now=NOW)
    assert repo.clear_target_plan(con, canon="CTB1", now=NOW) is True
    assert con.execute("SELECT count(*) FROM target_plan").fetchone()[0] == 0
    payload = _events(con, "target_plan.cleared")[0]["payload"]
    for fragment in ('"canon": "CTB1"', '"status": "active"', '"priority": 1', '"note": "60 h"'):
        assert fragment in payload
    assert repo.clear_target_plan(con, canon="CTB1", now=NOW) is False     # drugi raz = no-op
    assert len(_events(con, "target_plan.cleared")) == 1


def test_park_klinga_trojstan_i_guardy(con):
    assert repo.set_telescope_park(con, telescope_id=1, in_park=1, now=NOW) is True
    assert repo.set_telescope_park(con, telescope_id=1, in_park=1, now=NOW) is False   # idempotent
    assert repo.set_telescope_park(con, telescope_id=3, in_park=0, now=NOW) is True
    assert repo.set_telescope_park(con, telescope_id=3, in_park=None, now=NOW) is True  # cofnięcie
    assert len(_events(con, "telescope.parked")) == 3
    with pytest.raises(ValueError, match="nie istnieje"):
        repo.set_telescope_park(con, telescope_id=99, in_park=1, now=NOW)
    with pytest.raises(ValueError, match="dozwolone"):
        repo.set_telescope_park(con, telescope_id=1, in_park=7, now=NOW)


def test_park_nie_wchodzi_na_teleskop_scalony(con):
    """Park wskazujący wiersz scalony w inny opisywałby oś, której już nie ma (lustro approve)."""
    con.execute("UPDATE telescope SET merged_into = 1 WHERE id = 3")
    con.commit()
    with pytest.raises(ValueError, match="scalony"):
        repo.set_telescope_park(con, telescope_id=3, in_park=1, now=NOW)


def _park_col(con, tid):
    return con.execute("SELECT in_park FROM telescope WHERE id = ?", (tid,)).fetchone()["in_park"]


def test_scalenie_przenosi_park_na_korzen(con):
    """Dług T4 §10: `sky.park` filtruje `merged_into IS NULL`, więc bez przeniesienia scalenie
    GASIŁO oznaczenie usera po cichu — park zdanie o SPRZĘCIE, nie o wierszu."""
    repo.set_telescope_park(con, telescope_id=1, in_park=1, now=NOW)      # A140R w parku
    assert sky.park(con) == ("A140R",)
    assert repo.merge_telescope(con, source_id=1, target_id=2, now=NOW) is True
    assert _park_col(con, 2) == 1 and _park_col(con, 1) == 1              # source trzyma swoje
    assert sky.park(con) == ("RC8",)                                      # park NIE zgasł
    ev = _events(con, "telescope.parked")[-1]["payload"]
    for fragment in ('"telescope": "RC8"', '"before": null', '"after": 1', '"via": "merge:1"'):
        assert fragment in ev
    # unmerge oddaje oba wiersze z oznaczeniami — nic nie zostało skasowane, więc nic nie wraca
    repo.unmerge_telescope(con, telescope_id=1, now=NOW)
    assert sky.park(con) == ("A140R", "RC8")


def test_scalenie_nie_nadpisuje_wlasnego_zdania_korzenia(con):
    """Korzeń, który już mówi 1, nie dostaje drugiego eventu; milczący source nie ma co przenieść."""
    repo.set_telescope_park(con, telescope_id=1, in_park=1, now=NOW)
    repo.set_telescope_park(con, telescope_id=2, in_park=1, now=NOW)
    before = len(_events(con, "telescope.parked"))
    assert repo.merge_telescope(con, source_id=1, target_id=2, now=NOW) is True
    assert len(_events(con, "telescope.parked")) == before                # zgodne = bez ruchu
    assert repo.merge_telescope(con, source_id=3, target_id=2, now=NOW) is True   # source milczy
    assert len(_events(con, "telescope.parked")) == before
    assert _park_col(con, 3) is None


def test_sprzeczny_park_odmawia_scalenia(con):
    """1 vs 0 to dwa zdania usera o tym samym sprzęcie — klinga nie rozstrzyga za niego."""
    repo.set_telescope_park(con, telescope_id=1, in_park=1, now=NOW)
    repo.set_telescope_park(con, telescope_id=2, in_park=0, now=NOW)
    with pytest.raises(ValueError, match="SPRZECZNE"):
        repo.merge_telescope(con, source_id=1, target_id=2, now=NOW)
    assert con.execute("SELECT merged_into FROM telescope WHERE id=1").fetchone()[0] is None
    assert len(_events(con, "telescope.merged")) == 0                     # rollback całości
    assert (_park_col(con, 1), _park_col(con, 2)) == (1, 0)


# ─────────────────────────────────────────────────────────────── odczyt parku (`sky.park`)

def test_park_pusty_to_None_a_nie_pusta_krotka(con):
    """Rozróżnienie nośne: pusta krotka znaczyłaby „park pusty" i wygasiła planer do zera."""
    assert sky.park(con) is None
    repo.set_telescope_park(con, telescope_id=2, in_park=0, now=NOW)
    assert sky.park(con) is None                              # samo „historyczny" parku nie tworzy


def test_park_czyta_tylko_oznaczone_i_kanoniczne(con):
    repo.set_telescope_park(con, telescope_id=1, in_park=1, now=NOW)
    repo.set_telescope_park(con, telescope_id=2, in_park=1, now=NOW)
    assert sky.park(con) == ("A140R", "RC8")
    con.execute("UPDATE telescope SET merged_into = 1 WHERE id = 2")
    assert sky.park(con) == ("A140R",)                        # scalony wypada mimo oznaczenia


# ─────────────────────────────────────────────────────────────── szew z `plan()`

def test_brak_parku_w_bazie_nie_zmienia_dzisiejszego_wyniku(con):
    """BRAMKA ANTY-REGRESJI T4: dopóki nikt nic nie oznaczył, planer liczy jak przed T4."""
    _park_ready(con)
    res = targets.plan(con, night=date(2026, 8, 15), limit=None)
    assert res.park_source == "none" and res.park == ()
    assert {r.telescope for r in res.rigs} == {"A140R", "RC8", "ED120R"}


def test_park_z_bazy_ogranicza_zestawy(con):
    _park_ready(con)
    repo.set_telescope_park(con, telescope_id=1, in_park=1, now=NOW)
    res = targets.plan(con, night=date(2026, 8, 15), limit=None)
    assert res.park_source == "db" and res.park == ("A140R",)
    assert {r.telescope for r in res.rigs} == {"A140R"}


def test_jawna_lista_bije_baze(con):
    """Wołanie jest silniejsze niż stan trwały — inaczej `--park` przestałby cokolwiek znaczyć."""
    _park_ready(con)
    repo.set_telescope_park(con, telescope_id=1, in_park=1, now=NOW)
    res = targets.plan(con, night=date(2026, 8, 15), park=["RC8"], limit=None)
    assert res.park_source == "arg" and {r.telescope for r in res.rigs} == {"RC8"}


def test_park_bez_zestawu_jest_powiedziany_wprost(con):
    """Teleskop bez lightów nie ma FOV, więc znika z listy zestawów — cichy ubytek to ta sama
    kategoria błędu co cichy sufit listy."""
    _park_ready(con)
    con.execute("INSERT INTO telescope(telescop_canon, status, created_at) "
                "VALUES ('ED', 'proposed', ?)", (NOW,))
    con.commit()
    tid = con.execute("SELECT id FROM telescope WHERE telescop_canon = 'ED'").fetchone()["id"]
    repo.set_telescope_park(con, telescope_id=1, in_park=1, now=NOW)
    repo.set_telescope_park(con, telescope_id=tid, in_park=1, now=NOW)
    res = targets.plan(con, night=date(2026, 8, 15), limit=None)
    assert res.park_without_rigs == ("ED",) and {r.telescope for r in res.rigs} == {"A140R"}


def test_skip_znika_z_licznikiem_done_zostaje(con):
    _park_ready(con)
    base = targets.plan(con, night=date(2026, 8, 15), limit=None)
    canon = base.rows[0].target.canon
    repo.set_target_plan(con, canon=canon, status="skip", now=NOW)
    res = targets.plan(con, night=date(2026, 8, 15), limit=None)
    assert canon not in {r.target.canon for r in res.rows}
    assert res.counts["hidden_by_status"] == 1 and len(res.rows) == len(base.rows) - 1

    repo.set_target_plan(con, canon=canon, status="done", now=NOW)
    res = targets.plan(con, night=date(2026, 8, 15), limit=None)
    row = [r for r in res.rows if r.target.canon == canon][0]
    assert row.plan_status == "done" and res.counts["hidden_by_status"] == 0


def test_find_przebija_wlasne_skreslenie(con):
    """Pytanie wprost jest silniejsze niż wcześniejsze „nie interesuje mnie" — spójnie z T3,
    gdzie `find` pomija także progi."""
    _park_ready(con)
    repo.set_target_plan(con, canon="CTB1", status="skip", now=NOW)
    assert "CTB1" not in {r.target.canon for r in targets.plan(con, night=date(2026, 8, 15)).rows}
    res = targets.plan(con, night=date(2026, 8, 15), find="CTB1")
    assert "CTB1" in {r.target.canon for r in res.rows}


def test_filtr_statusu_i_kolumny_wiersza(con):
    _park_ready(con)
    repo.set_target_plan(con, canon="CTB1", status="planned", priority=1, note="SII", now=NOW)
    res = targets.plan(con, night=date(2026, 8, 15), status="planned", limit=None)
    assert [r.target.canon for r in res.rows] == ["CTB1"]
    assert (res.rows[0].priority, res.rows[0].note) == (1, "SII")
    assert res.counts["marked"] == 1


def test_priorytet_nie_rusza_klucza_sortowania(con):
    """D-T4-c ROZSTRZYGNIĘTE 2026-07-31 (GO Zdzinia): priorytet NIE wchodzi do porządku listy.
    Człony `_sort_key` wywalczył firsthand T3 (plus kubełek kadru PL-1); priorytet przed
    „widoczny" postawiłby na czele listy cel pod horyzontem. Ten test pinuje rozstrzygnięcie, nie tylko stan przejściowy."""
    _park_ready(con)
    base = [r.target.canon for r in targets.plan(con, night=date(2026, 8, 15), limit=None).rows]
    repo.set_target_plan(con, canon=base[-1], status="planned", priority=1, now=NOW)
    after = [r.target.canon for r in targets.plan(con, night=date(2026, 8, 15), limit=None).rows]
    assert after == base


# ─────────────────────────────────────────────────────────────── walidacja kanonu

def test_kanon_rozpoznany_po_kanonie_i_aliasie_katalogowym():
    assert targets.resolve_plan_canon("ngc7000")[0] == "NGC7000"
    assert targets.resolve_plan_canon("WR134")[0] == "WR134"          # curated
    canon, _ = targets.resolve_plan_canon("M42")
    assert canon is not None and canon.startswith("NGC")             # alias katalogowy → kanon


def test_nazwa_dwuznaczna_odmawia_i_pokazuje_kandydatow():
    """Zmierzone w T3: „Eastern Veil" nosi NGC6992 ORAZ NGC6995. Wybór za użytkownika = zły zapis."""
    canon, candidates = targets.resolve_plan_canon("Eastern Veil")
    assert canon is None and len(candidates) == 2


def test_literowka_dostaje_kandydatow_nie_cisze():
    canon, candidates = targets.resolve_plan_canon("NGC70")
    assert canon is None and candidates                                # podciąg → propozycje
    assert targets.resolve_plan_canon("zzzzz") == (None, ())


# Wpis → (dokładne trafienia szukajki, wynik oznaczenia). `None` w drugim polu = brak trafienia
# dokładnego: oznaczenie oddaje wtedy najbliższych po podciągu (sprawdzane niżej regułą, nie listą
# - lista zależy od zawartości assetu).
_FORMY = [
    ("M 27", {"NGC6853"}, ("NGC6853", ())),
    ("m27", {"NGC6853"}, ("NGC6853", ())),
    ("M27", {"NGC6853"}, ("NGC6853", ())),
    ("NGC6853", {"NGC6853"}, ("NGC6853", ())),
    ("Arp244", {"NGC4038"}, ("NGC4038", ())),                 # cała nazwa po `norm_alnum`
    ("Arp 244", {"NGC4038"}, ("NGC4038", ())),
    ("Heart Nebula", {"IC1805"}, ("IC1805", ())),             # nazwa potoczna resolvera
    ("Eastern Veil", {"NGC6992", "NGC6995"}, (None, ("NGC6992", "NGC6995"))),   # dwuznaczna
    ("sh2 131", {"Sh2-131"}, ("Sh2-131", ())),
    ("G024.7+00.6", {"G024.7+00.6"}, ("G024.7+00.6", ())),    # znak rozróżnia dwa obiekty
    ("NGC70", set(), None),                                   # literówka: najbliżsi
    ("NGC 7oo0", set(), (None, ())),                          # literówka bez podobnych
    ("", set(), (None, ())),
    ("zzqq", set(), (None, ())),                              # nazwa spoza katalogu
    ("M 13", set(), (None, ())),                              # znana katalogowi, poza celami
]


@pytest.mark.parametrize("wpis, dokladne, oznaczenie", _FORMY)
def test_szukajka_i_oznaczenie_celu_mowia_jednym_glosem(wpis, dokladne, oznaczenie):
    """AR-149: oznaczenie celu (`resolve_plan_canon`, CLI `horreum target`) trzymało własną kopię
    reguły „ta nazwa to ten cel” i rozjeżdżało się ze szukajką planera: „Arp244” i „Heart Nebula”
    szukajka znajdowała, a oznaczenie odmawiało. Jedna tabela form dla obu wołających: dokładne
    trafienie szukajki == kanon oznaczenia, kilka trafień == kandydaci (nigdy cichy wybór), zero ==
    najbliżsi z podciągu szukajki, do 5.

    Jawnie nazwana różnica: szukajka w `plan` biegnie po warstwach WCZYTANYCH, oznaczenie po
    wszystkich - tabela porównuje obie na pełnym assecie (cel spoza wczytanych warstw dostaje
    w `plan` zdanie `find_outside`, nie trafienie)."""
    exact, rest = targets.find_matches(targets.load_targets(targets.ALL_LAYERS), wpis)
    trafione = {t.canon for t in exact}
    assert trafione == dokladne
    wynik = targets.resolve_plan_canon(wpis)
    if oznaczenie is not None:
        assert wynik == oznaczenie
    if len(trafione) == 1:
        assert wynik == (next(iter(trafione)), ())
    elif trafione:
        assert wynik == (None, tuple(sorted(trafione)))
    else:
        # Najbliżsi w kolejności pewności `find_matches`, kanon raz (AR-151) - nie alfabetem.
        assert wynik == (None, tuple(dict.fromkeys(t.canon for t in rest))[:5])
        assert oznaczenie is not None or wynik[1], "literówka bez kandydatów - fikstura bez sensu"


def test_oznaczenie_przycina_wpis_jak_stara_regula():
    """Szukajka trzyma surowy tekst (AR-146: nic, co trafiało, nie przestaje), ale oznaczenie celu
    przycinało wpis przed szukaniem. Wpis z samymi znakami spoza `norm_alnum` (` + `) bez przycięcia
    szukałby podciągu ze spacjami i nie dostał najbliższych, które stara reguła oddawała."""
    przyciety = targets.resolve_plan_canon("+")
    assert przyciety[0] is None and przyciety[1], "asset bez kanonu ze znakiem + - fikstura bez sensu"
    assert targets.resolve_plan_canon(" + ") == przyciety
    assert targets.resolve_plan_canon("  M 27 ") == ("NGC6853", ())


def test_szczebel_katalogowy_bije_nazwe_a_rekord_nazwy_zostaje_na_liscie():
    """`norm_alnum` gubi znak: `G024.7+00.6` i `G024.7-00.6` (dwa obiekty Greena) mają jeden klucz
    nazwy. Bez szczebli szukajka dawała oba jako DOKŁADNE, a oznaczenie wybrałoby jeden z nich
    tylko dzięki starej kopii reguły. Szczebel katalogowy rozstrzyga; rekord trafiony samą nazwą
    schodzi do podciągu - nie znika z listy szukajki."""
    pool = targets.load_targets(targets.ALL_LAYERS)
    for wpis, lustro in (("G024.7+00.6", "G024.7-00.6"), ("G024.7-00.6", "G024.7+00.6")):
        exact, rest = targets.find_matches(pool, wpis)
        assert [t.canon for t in exact] == [wpis]
        assert lustro in {t.canon for t in rest}
        assert targets.resolve_plan_canon(wpis) == (wpis, ())


# ─────────────────────────────────────────────────────────────── najbliżsi po pewności (AR-151)

def _cel(canon, *aliasy, layer="core"):
    return targets.Target(canon=canon, type="EN", ra_deg=90.0, dec_deg=45.0, major_arcmin=10.0,
                          minor_arcmin=None, mag=None, mag_from_b=False, aliases=tuple(aliasy),
                          layer=layer, why=None, size_source=None)


# Pula w porządku ASSETU - alfabet celowo inny niż pewność: szum (podciąg w środku słowa) stoi
# na początku alfabetu i na początku puli.
_PULA_AR151 = (
    _cel("AAA 1", "Supernebula"),                     # „neb” w środku słowa
    _cel("ESO351-030", "Sculptor Dwarf Elliptical"),  # „Fe” w środku słowa (dwarF Elliptical)
    _cel("ABB 2", "Xfe Cloud"),                       # „Fe” w środku słowa
    _cel("ZZZ 9", "Cave Nebula"),                     # „neb” od początku słowa aliasu
    _cel("C9", "Nebula Cave"),                        # „neb” prefiks aliasu
    _cel("Fe 7"),                                     # „Fe” prefiks kanonu (pula: 7 przed 6)
    _cel("Fe 6"),
    _cel("BBB 3", "Big Nebula"),                      # „neb” od początku słowa, za ZZZ 9 w puli
    _cel("NGC7007"),
    _cel("NGC7000", "North America Nebula"),
    _cel("ACC 4", "Ringfe"),                          # „Fe” w środku słowa
    _cel("ADD 5", "Fe Arc"),                          # „Fe” prefiks aliasu
    _cel("AEE 6", "Old Fe"),                          # „Fe” od początku słowa aliasu
    _cel("AFF 7", "Hafe"),                            # „Fe” w środku słowa
    _cel("Fe 7", layer="cirrus"),                     # ten sam kanon drugi raz (inna warstwa)
)

# Wpis → dokładna kolejność najbliższych (pierwsza piątka, kanon raz).
_NAJBLIZSI = [
    # Debet AR-151: szum sklejonych słów był pierwszy alfabetem i wypychał „Fe 6”/„Fe 7” poza
    # piątkę; teraz: prefiks kanonu (porządek puli), prefiks aliasu, początek słowa, środek słowa.
    ("Fe", ("Fe 7", "Fe 6", "ADD 5", "AEE 6", "ESO351-030")),
    # Literówka - prefiks kanonu, porządek puli (7007 przed 7000), bez alfabetu.
    ("NGC 700", ("NGC7007", "NGC7000")),
    ("ngc700", ("NGC7007", "NGC7000")),
    # Cztery szczeble naraz: prefiks aliasu, początek słowa (porządek puli: ZZZ 9, BBB 3, NGC7000),
    # środek słowa na końcu.
    ("neb", ("C9", "ZZZ 9", "BBB 3", "NGC7000", "AAA 1")),
    # Sam środek słowa - porządek puli (alfabet dałby AAA 1, BBB 3, C9, ESO351-030, NGC7000).
    ("ul", ("AAA 1", "ESO351-030", "ZZZ 9", "C9", "BBB 3")),
    ("dwarf", ("ESO351-030",)),
]


@pytest.mark.parametrize("wpis, szczebel", [
    ("eso35", 0), ("ESO 351", 0),                     # prefiks kanonu (surowo i `norm_alnum`)
    ("sculp", 1),                                     # prefiks aliasu
    ("dwarf", 2), ("elliptical", 2),                  # od początku słowa (spacja w surowym tekście)
    ("dwarfell", 2),                                  # od początku słowa w kluczu `norm_alnum`
    ("fe", 3), ("warf", 3), ("ptor dw", 3),           # w środku słowa
])
def test_szczebel_podciagu_ESO351_030(wpis, szczebel):
    """Szczebel pewności trafienia (`_szczebel_podciagu`) na rekordzie z debetu AR-151: „Fe”
    trafia go w środku słowa (dwarF Elliptical), więc staje za kandydatami z prefiksem."""
    k = _cel("ESO351-030", "Sculptor Dwarf Elliptical").find_keys
    assert targets._szczebel_podciagu(k, wpis.casefold(), targets.norm_alnum(wpis)) == szczebel


@pytest.mark.parametrize("wpis, najblizsi", _NAJBLIZSI)
def test_najblizsi_oznaczenia_po_pewnosci_nie_alfabetem(monkeypatch, wpis, najblizsi):
    """AR-151: `find_matches` skleja słowa nazwy (`norm_alnum`), więc `Fe` trafia „Sculptor
    DwarF Elliptical”; od AR-149 ta reguła zasila najbliższych oznaczenia, a `resolve_plan_canon`
    sortował je ALFABETEM i ucinał do pięciu - szum wypychał kandydata, którego nazwa zaczyna się
    wpisanym tekstem. Teraz kolejność pewności z `find_matches`, w obrębie szczebla porządek puli,
    kanon raz na miejscu pierwszego trafienia. Woła KOŃCOWE `resolve_plan_canon` (pula podstawiona -
    kolejność przypięta niezależnie od assetu)."""
    monkeypatch.setattr(targets, "load_targets", lambda layers=None: _PULA_AR151)
    assert targets.resolve_plan_canon(wpis) == (None, najblizsi)


def test_najblizsi_z_assetu_fe_i_literowka():
    """Ten sam debet na prawdziwym assecie: `Fe` - dwa kanony z prefiksem przed `ESO351-030`
    (dawniej pierwszy alfabetem), literówka `NGC 700` - kanony z prefiksem."""
    assert targets.resolve_plan_canon("Fe") == (None, ("Fe 6", "Fe 7", "ESO351-030"))
    assert targets.resolve_plan_canon("NGC 700") == (None, ("NGC7000", "NGC7007"))


def test_kolejnosc_podciagu_nie_zmienia_skladu_ani_dokladnych():
    """Sort pewności przestawia WYŁĄCZNIE listę podciągu `find_matches` - zbiór trafień i dokładne
    zostają (AR-146: nic, co trafiało, nie przestaje), a wiersze planera mają własny klucz."""
    pool = targets.load_targets(targets.ALL_LAYERS)
    for wpis in ("Fe", "neb", "NGC70", "Sh2 13", "veil", "+00.9"):
        exact, rest = targets.find_matches(pool, wpis)
        szczeble = [targets._szczebel_podciagu(t.find_keys, wpis.casefold(),
                                               targets.norm_alnum(wpis)) for t in rest]
        assert szczeble == sorted(szczeble), wpis
        przed = [t for t in pool if t in set(exact) | set(rest)]
        assert sorted(map(id, exact + rest)) == sorted(map(id, przed)), wpis


# ─────────────────────────────────────────────────────────────── CLI

def test_cli_park_dodaje_i_odmawia_nieznanego(tmp_path, capsys, con):
    path = con.execute("PRAGMA database_list").fetchone()["file"]
    assert cli.main(["park", path, "--add", "a140r"]) == 0            # dopasowanie bez case
    assert "TAK" in capsys.readouterr().out
    assert cli.main(["park", path, "--add", "Newton10"]) == 2
    out = capsys.readouterr().out
    assert "nieznany bazie" in out and "A140R" in out


def test_cli_park_clear_wycofuje_zdanie_do_null(tmp_path, capsys, con):
    """Dług P-A #7 po stronie CLI: `--add` daje 1, `--drop` 0, a trzeci stan (`NULL` = „nic nie
    powiedziałem") był osiągalny wyłącznie z `repo`. Raport odróżnia stany: `historyczny` vs `-`."""
    path = con.execute("PRAGMA database_list").fetchone()["file"]
    assert cli.main(["park", path, "--drop", "A140R"]) == 0
    assert "historyczny" in capsys.readouterr().out
    assert cli.main(["park", path, "--clear", "a140r"]) == 0          # dopasowanie bez case, jak --add
    out = capsys.readouterr().out
    assert "zmieniono 1" in out and "historyczny" not in out
    assert con.execute("SELECT in_park FROM telescope WHERE telescop_canon = 'A140R'"
                       ).fetchone()[0] is None
    assert cli.main(["park", path, "--clear", "A140R"]) == 0          # idempotentne — nic nie zmienia
    assert "zmieniono" not in capsys.readouterr().out


def test_cli_target_clear_zdejmuje_cel_spoza_katalogu(tmp_path, capsys, con):
    """Kuratela na kanonie, którego asset już nie zna (podmiana katalogu), była NIEUSUWALNA:
    lista (wywołanie BEZ argumentu `canon`) pokazywała ją z etykietą `[poza katalogiem]`, a `--clear` szedł przez
    `resolve_plan_canon` i kończył kodem 2. Fallback jest WYŁĄCZNIE dla kasowania — ścieżka zapisu
    dalej odmawia, bo tam zgadywanie kanonu tworzy cudzą decyzję, a tu ją zdejmuje.

    Drugi człon pilnuje, żeby fallback nie wyciął NORMALIZACJI: `M42` ma trafiać w `NGC1976`
    (asset odpowiada pierwszy), a nie zakładać kasowania po surowym stringu."""
    path = con.execute("PRAGMA database_list").fetchone()["file"]
    con.execute("INSERT INTO target_plan(canon, status, created_at, updated_at) "
                "VALUES ('NGC9999', 'planned', ?, ?)", (NOW, NOW))
    con.commit()

    assert cli.main(["target", path, "NGC9999", "--clear"]) == 0
    assert "dokladna nazwa" in capsys.readouterr().out
    assert con.execute("SELECT count(*) FROM target_plan WHERE canon='NGC9999'").fetchone()[0] == 0

    # Nadal odmawia, gdy nie ma czego zdjąć ANI w asecie, ANI w tabeli — cisza byłaby gorsza.
    assert cli.main(["target", path, "NGC9999", "--clear"]) == 2

    # Normalizacja żyje: `M42` idzie przez asset na `NGC1976`, fallback się nie odzywa.
    repo.set_target_plan(con, canon="NGC1976", status="planned", priority=None, note=None, now=NOW)
    assert cli.main(["target", path, "M42", "--clear"]) == 0
    assert "NGC1976" in capsys.readouterr().out
    assert con.execute("SELECT count(*) FROM target_plan WHERE canon='NGC1976'").fetchone()[0] == 0


def test_cli_target_clear_nazwa_dwuznaczna_nie_kasuje_po_cichu(tmp_path, capsys, con):
    """Nazwa POTOCZNA bywa dwuznaczna („Eastern Veil" wskazuje dwa rekordy) — asset zwraca wtedy
    `(None, kandydaci)`, tak samo jak dla sieroty. Fallback nie ma prawa udawać, że wie, o który
    cel chodzi: kasuje WYŁĄCZNIE wiersz o literalnie tej nazwie, a gdy takiego nie ma — user
    dostaje kandydatów i kod 2, nie ciche zero.

    Komunikat mówi „dokładna nazwa, poza rozstrzygnięciem katalogu", a NIE „cel spoza katalogu":
    to drugie byłoby zdaniem o katalogu, a wiemy tylko tyle, że asset tej nazwy nie rozstrzygnął."""
    path = con.execute("PRAGMA database_list").fetchone()["file"]
    igla = "Eastern Veil"
    assert targets.resolve_plan_canon(igla)[1], "fikstura wymaga nazwy DWUZNACZNEJ w asecie"

    # Bez wiersza o tej nazwie: odmowa z kandydatami — zachowanie sprzed fallbacku, nietknięte.
    assert cli.main(["target", path, igla, "--clear"]) == 2
    assert "nie wskazuje jednego celu" in capsys.readouterr().out

    # Z wierszem o literalnie tej nazwie: zdejmujemy JEGO i mówimy to wprost.
    con.execute("INSERT INTO target_plan(canon, status, created_at, updated_at) "
                "VALUES (?, 'planned', ?, ?)", (igla, NOW, NOW))
    con.commit()
    assert cli.main(["target", path, igla, "--clear"]) == 0
    assert "dokladna nazwa" in capsys.readouterr().out
    assert con.execute("SELECT count(*) FROM target_plan WHERE canon=?", (igla,)).fetchone()[0] == 0


def test_cli_park_bez_oznaczen_mowi_wprost(tmp_path, capsys, con):
    path = con.execute("PRAGMA database_list").fetchone()["file"]
    assert cli.main(["park", path]) == 0
    assert "NIEUSTAWIONY" in capsys.readouterr().out


def test_cli_target_literowka_konczy_kodem_2(tmp_path, capsys, con):
    path = con.execute("PRAGMA database_list").fetchone()["file"]
    assert cli.main(["target", path, "NGC 7oo0", "--status", "planned"]) == 2
    assert "nie wskazuje jednego celu" in capsys.readouterr().out


def test_cli_target_pelny_cykl(tmp_path, capsys, con):
    path = con.execute("PRAGMA database_list").fetchone()["file"]
    assert cli.main(["target", path, "CTB1", "--status", "planned", "--priority", "1",
                     "--note", "SII"]) == 0
    capsys.readouterr()
    assert cli.main(["target", path]) == 0
    out = capsys.readouterr().out
    assert "CTB1" in out and "planned" in out and "SII" in out
    assert cli.main(["target", path, "CTB1", "--clear"]) == 0
    capsys.readouterr()
    assert cli.main(["target", path]) == 0
    assert "brak oznaczonych" in capsys.readouterr().out


def test_cli_target_bez_statusu_nie_zgaduje(tmp_path, capsys, con):
    path = con.execute("PRAGMA database_list").fetchone()["file"]
    assert cli.main(["target", path, "CTB1"]) == 2
    assert "podaj --status" in capsys.readouterr().out


# ───────────────────────────────────────────── sierota kurateli (R-S0-7)
#
# Oznaczenie na kanonie, którego asset nie zna, jest w planerze NIEWIDOCZNE (wiersze powstają
# z puli katalogu, kuratela dokleja się przez `marks.get(t.canon)`) I NIEUSUWALNE (GUI kasuje
# wyłącznie z zaznaczonego wiersza). Generatorem jest przebudowa assetu — a ta częściej nazwę
# PRZENOSI, niż usuwa, więc predykat ma dwa stany, nie jeden.

def _mark_wprost(con, canon, status="planned", priority=None, note=None):
    """Oznaczenie wstawione Z POMINIĘCIEM walidacji nazwy — bo dokładnie tak powstaje sierota:
    kanon był w asecie w chwili zapisu, a wypadł z niego później."""
    con.execute("INSERT INTO target_plan(canon, status, priority, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)", (canon, status, priority, note, NOW, NOW))
    con.commit()


def test_sierota_nieznana_i_przeniesiona_to_dwa_rozne_stany(con):
    _mark_wprost(con, "NGC0000_NIEISTNIEJE")
    _mark_wprost(con, "LBN529")            # żywy ALIAS KATALOGOWY rekordu C9 (asset, ALL_LAYERS)
    _mark_wprost(con, "CTB1")              # zwykły kanon — sierotą NIE jest
    out = targets.orphan_marks(con)
    assert set(out) == {"NGC0000_NIEISTNIEJE", "LBN529"}
    assert out["NGC0000_NIEISTNIEJE"][0] == targets.ORPHAN_UNKNOWN
    assert out["NGC0000_NIEISTNIEJE"][2] is None
    # SEDNO DŁUGU: dla tego wiersza kasacja NIE jest jedyną odpowiedzią — cel żyje pod inną nazwą.
    assert out["LBN529"][0] == targets.ORPHAN_MOVED
    assert out["LBN529"][2] == "C9"


def test_sierota_niesie_caly_wiersz_a_nie_sam_kanon(con):
    """Bez statusu, priorytetu i noty nie da się ani PRZENIEŚĆ oznaczenia, ani go COFNĄĆ —
    a obie drogi powrotu stoją na tym, że nic z decyzji człowieka nie ginie."""
    _mark_wprost(con, "LBN576", status="active", priority=3, note="SII")
    _stan, row, gdzie = targets.orphan_marks(con)["LBN576"]
    assert (row["status"], row["priority"], row["note"], gdzie) == ("active", 3, "SII", "CTB1")


def test_sierota_liczona_wobec_PELNEGO_katalogu_nie_wczytanych_warstw(con):
    """`LDN825` leży w cirrusie. Predykat na DEFAULT_LAYERS ogłosiłby sierotą cel, który istnieje —
    ta sama granica, którą trzyma `PlanResult.unmatched`."""
    _mark_wprost(con, "LDN825")
    assert targets.orphan_marks(con)["LDN825"][0] == targets.ORPHAN_MOVED


def test_plan_wystawia_sieroty_bo_lista_nie_ma_jak(con):
    _park_ready(con)
    _mark_wprost(con, "NGC0000_NIEISTNIEJE")
    res = targets.plan(con, night=date(2026, 1, 2))
    assert set(res.orphan_marks) == {"NGC0000_NIEISTNIEJE"}
    assert not [r for r in res.rows if r.target.canon == "NGC0000_NIEISTNIEJE"]


def test_plan_bez_sierot_daje_pusty_slownik(con):
    _park_ready(con)
    assert targets.plan(con, night=date(2026, 1, 2)).orphan_marks == {}


def test_cli_target_rozroznia_dwa_stany_sieroctwa(capsys, con):
    path = con.execute("PRAGMA database_list").fetchone()["file"]
    _mark_wprost(con, "NGC0000_NIEISTNIEJE")
    _mark_wprost(con, "LBN529")
    assert cli.main(["target", path]) == 0
    out = capsys.readouterr().out
    assert "[poza katalogiem]" in out
    # Do S0 lista mówiła „poza katalogiem" także o TYM wierszu — czyli o celu, który stoi
    # w katalogu obok, pod swoją nową nazwą.
    assert "[w katalogu jako C9]" in out


# ─────────────────────────── AR-175: szukajka mówi nazwę, którą trafiła (alias), i pudło nazwy znanej

def test_find_matches_mowi_nazwe_trafienia():
    """AR-175 (wizytacja natywna): „M 4” trafiało M42/M43/M49 podciągiem, a wiersz mówił gołe „NGC1976” -
    nazwę, której nikt nie wpisał. `find_matches` mówi teraz, KTÓRĄ nazwą rekord trafił (ta sama pętla,
    te same klucze); kanon - bez aliasu. Rozpakowanie `(dokładne, podciąg)` działa jak dotąd.
    Mutant: `przez` zawsze z kanonu (aliasy znikają)."""
    pula = targets.load_targets(targets.ALL_LAYERS)
    traf = targets.find_matches(pula, "M 4")
    exact, rest = traf
    assert exact == () and len(traf) == 2 and traf[1] == rest
    przez = {t.canon: n for t, n in traf.przez.items()}
    assert {przez[c] for c in ("NGC1976", "NGC1982", "NGC4472")} == {"M42", "M43", "M49"}
    assert przez["NGC1976"] == "M42" and przez["NGC4472"] == "M49"
    fe = targets.find_matches(pula, "Fe")
    assert {t.canon: n for t, n in fe.przez.items()}["ESO351-030"] == "Sculptor Dwarf Elliptical"
    assert targets.find_matches(pula, "NGC 70").przez == {}            # prefiks kanonu - kanon
    m42 = targets.find_matches(pula, "M 42")
    assert [t.canon for t in m42[0]] == ["NGC1976"] and list(m42.przez.values()) == ["M42"]
    assert targets.find_matches(pula, "NGC 1976").przez == {}          # wpisany kanon
    assert targets.forma_nazwy_trafienia("M42") == "M 42"
    assert targets.forma_nazwy_trafienia("Sculptor Dwarf Elliptical") == "Sculptor Dwarf Elliptical"


def test_kandydaci_oznaczenia_niosa_alias_i_porownuja_sie_jak_kanon():
    """AR-175: kandydaci `resolve_plan_canon` niosą nazwę trafienia („NGC1976 (M 42)”), a porównania
    i deduplikacja zostają na kanonie (`Kandydat` to `str`). Mutant: kandydaci bez `przez`."""
    canon, kandydaci = targets.resolve_plan_canon("M 4")
    assert canon is None and kandydaci[:3] == ("NGC1976", "NGC1982", "NGC4472")
    assert [k.opis for k in kandydaci[:3]] == ["NGC1976 (M 42)", "NGC1982 (M 43)", "NGC4472 (M 49)"]
    assert targets.resolve_plan_canon("NGC 70")[1][0].opis == "NGC7000"     # kanonem - bez aliasu


def test_cli_target_kandydaci_z_aliasem_i_pudlem(tmp_path, capsys, con):
    """AR-175: `horreum target "M 4"` mówi kandydatów z aliasem, którym trafili, i że samo M4 to NGC6121
    spoza celów planera; zdanie odmowy i kod 2 bez zmian, wyjście w cp1250.
    Mutant: kandydaci bez aliasu; brak linii nazwy znanej."""
    path = con.execute("PRAGMA database_list").fetchone()["file"]
    assert cli.main(["target", path, "M 4", "--status", "planned"]) == 2
    out = capsys.readouterr().out
    assert "nie wskazuje jednego celu katalogu" in out
    assert "Kandydaci: NGC1976 (M 42), NGC1982 (M 43), NGC4472 (M 49)" in out
    assert "'M 4' = NGC6121: znane katalogowi, poza celami planera." in out
    out.encode("cp1250")
    assert cli.main(["target", path, "Eastern Veil", "--status", "planned"]) == 2
    assert "NGC6121" not in capsys.readouterr().out                     # tylko przy nazwie znanej
