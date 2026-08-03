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
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 13
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
    Pięć członów `_sort_key` wywalczył firsthand T3; priorytet przed „widoczny" postawiłby na czele
    listy cel pod horyzontem. Ten test pinuje rozstrzygnięcie, nie tylko stan przejściowy."""
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
    `--list` pokazywał ją z etykietą `[poza katalogiem]`, a `--clear` szedł przez
    `resolve_plan_canon` i kończył kodem 2. Fallback jest WYŁĄCZNIE dla kasowania — ścieżka zapisu
    dalej odmawia, bo tam zgadywanie kanonu tworzy cudzą decyzję, a tu ją zdejmuje.

    Drugi człon pilnuje, żeby fallback nie wyciął NORMALIZACJI: `M42` ma trafiać w `NGC1976`
    (asset odpowiada pierwszy), a nie zakładać kasowania po surowym stringu."""
    path = con.execute("PRAGMA database_list").fetchone()["file"]
    con.execute("INSERT INTO target_plan(canon, status, created_at, updated_at) "
                "VALUES ('NGC9999', 'planned', ?, ?)", (NOW, NOW))
    con.commit()

    assert cli.main(["target", path, "NGC9999", "--clear"]) == 0
    assert "spoza katalogu" in capsys.readouterr().out
    assert con.execute("SELECT count(*) FROM target_plan WHERE canon='NGC9999'").fetchone()[0] == 0

    # Nadal odmawia, gdy nie ma czego zdjąć ANI w asecie, ANI w tabeli — cisza byłaby gorsza.
    assert cli.main(["target", path, "NGC9999", "--clear"]) == 2

    # Normalizacja żyje: `M42` idzie przez asset na `NGC1976`, fallback się nie odzywa.
    repo.set_target_plan(con, canon="NGC1976", status="planned", priority=None, note=None, now=NOW)
    assert cli.main(["target", path, "M42", "--clear"]) == 0
    assert "NGC1976" in capsys.readouterr().out
    assert con.execute("SELECT count(*) FROM target_plan WHERE canon='NGC1976'").fetchone()[0] == 0


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
