"""R1 — oś sprzętu wskazana RĘKĄ (`frame.config_source`, #DR2 segment R1, D-DR-3).

Populacja, dla której to powstało, nie ma jak zeznać: RAW zrobiony PRZEZ TELESKOP nie niesie nazwy
niczego (EXIF mapuje na `TELESCOP` nazwę OBIEKTYWU — E3-3), a plik jest read-only, więc droga
writebacku jest zamknięta na zawsze. Testy pilnują czterech odmów klingi, LEPKOŚCI źródła wobec
przebiegu (R1b — bez niej pierwsze „Przetwórz wszystko" zdejmuje fakt człowieka), parytetu
dziennika i przeżycia podmiany pliku (szew z R4).

Bramki briefu: G1-2 (CHECK w DDL), G1-4 (parytet), G1-5 (ręka przeżywa automat), G1-6 (odmowa
kalibracji), G1-8 (podmiana nie gubi ręki), G1-12 (przerwanie gestu).
"""
import sqlite3

import pytest

from horreum import audit, db, grouper, repo, resolver, supersede

NOW = "2026-08-08T10:00:00+00:00"


def _baza():
    return db.open_db(":memory:")


def _kamera(con, model="Sony ILCE-7S", pixel=8.4):
    cid, _ = repo.upsert_camera(con, model_canon=model, pixel_um=pixel, is_mono=0,
                                is_mono_source="bayer", raw_instrume=model, now=NOW)
    return cid


def _teleskop(con, canon="RC8R", focal=1200):
    tid, _ = repo.propose_telescope(con, telescop_canon=canon, focal_nominal=focal, now=NOW)
    return tid


def _klatka(con, sha, *, kind="light", camera_id=None, telescop=None, filetype="raw"):
    """Klatka Z NAGŁÓWKIEM — grouper czyta `frame JOIN header`, więc bez zeznania nie istnieje."""
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind=kind, filetype=filetype,
                               camera_id=camera_id, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json="{}", now=NOW, telescop=telescop)
    return fid


# ---------------------------------------------------------------- G1-2: słownik ma dno w DDL

def test_check_w_ddl_odrzuca_zrodlo_spoza_stalej(tmp_path):
    """Baza jest OSTATNIĄ bramką słownika: wstrzyknięcie z pominięciem klingi ma się odbić o CHECK,
    a nie zamieszkać w kolumnie jako wartość, o której nie wie żaden konsument (wzorzec 0012:93)."""
    path = str(tmp_path / "h.db")
    con = db.open_db(path)
    fid = _klatka(con, "aaa", camera_id=_kamera(con))
    con.close()

    goly = sqlite3.connect(path)                     # z pominięciem `repo` — jak ręczny SQL w konsoli
    with pytest.raises(sqlite3.IntegrityError):
        goly.execute("UPDATE frame SET config_source = 'zgadywanie' WHERE id = ?", (fid,))
    for legalne in sorted(repo.CONFIG_SOURCES):      # lustro kodu przechodzi przez to samo dno
        goly.execute("UPDATE frame SET config_source = ? WHERE id = ?", (legalne, fid))
    goly.close()


def test_stala_w_kodzie_jest_lustrem_ddl():
    """Dwie listy tego samego słownika rozjeżdżają się po cichu — ta para ma jednego właściciela
    (`CONFIG_SOURCES`), a `STICKY_*` jest jej ALIASEM, nie kopią (SIN-DUP)."""
    assert repo.CONFIG_SOURCES == frozenset({"user"})
    assert repo.STICKY_CONFIG_SOURCES is repo.CONFIG_SOURCES


# ---------------------------------------------------------------- gest: zapis i cztery odmowy

def test_gest_przypisuje_zestaw_i_znaczy_zrodlo():
    """Ścieżka szczęśliwa: ręka wskazuje TELESKOP, kamera wynika z klatki (inwariant DDL §1),
    config powstaje jako iloczyn, a `config_source='user'` mówi, skąd to wiadomo."""
    con = _baza()
    cam, tel = _kamera(con), _teleskop(con)
    a = _klatka(con, "aaa", camera_id=cam)
    b = _klatka(con, "bbb", camera_id=cam)

    g = repo.user_assign_config(con, frame_ids=[a, b], telescope_id=tel, now=NOW)
    assert (g.assigned, g.configs_created) == (2, 1)          # jeden config na (teleskop × kamera)
    cfg = con.execute("SELECT id, telescope_id, camera_id FROM config").fetchone()
    assert (cfg["telescope_id"], cfg["camera_id"]) == (tel, cam)
    for fid in (a, b):
        row = con.execute(
            "SELECT config_id, config_source FROM frame WHERE id=?", (fid,)).fetchone()
        assert tuple(row) == (cfg["id"], "user")
    # G1-1: zapis osi ręką MUSI mieć aktora człowieka — bez tego bramka nie odróżni gestu od automatu
    aktorzy = {r[0] for r in con.execute(
        "SELECT actor FROM event WHERE verb='config.assigned'")}
    assert aktorzy == {"user:local"}


def test_gest_odmawia_kalibracji():
    """G1-6. Dark i bias powstają przy ZAMKNIĘTEJ migawce — optyka ich nie opisuje. Guard stoi
    w KLINDZE, więc broni także każdej przyszłej powierzchni (lekcja S2b)."""
    con = _baza()
    cam, tel = _kamera(con), _teleskop(con)
    dark = _klatka(con, "ddd", kind="dark", camera_id=cam)

    g = repo.user_assign_config(con, frame_ids=[dark], telescope_id=tel, now=NOW)
    assert (g.assigned, g.kind_skip) == (0, 1)
    assert con.execute("SELECT config_id FROM frame WHERE id=?", (dark,)).fetchone()[0] is None
    assert con.execute("SELECT count(*) FROM event WHERE verb='config.assigned'").fetchone()[0] == 0
    # Rodzaj bez osi bierzemy od WŁAŚCICIELA zbioru, nie z wyliczanki w teście
    assert "dark" in grouper.NO_TELESCOPE_KINDS


def test_gest_odmawia_klatce_bez_kamery():
    """Configu nie da się złożyć z jednej osi — zgadywanie kamery łamałoby inwariant DDL §1."""
    con = _baza()
    tel = _teleskop(con)
    a = _klatka(con, "aaa", camera_id=None)

    g = repo.user_assign_config(con, frame_ids=[a], telescope_id=tel, now=NOW)
    assert (g.assigned, g.no_camera) == (0, 1)
    assert con.execute("SELECT count(*) FROM config").fetchone()[0] == 0


def test_gest_nie_nadpisuje_bez_zgody():
    """„Guard nadpisania jawny" (D-DR-3): bez niego pierwsza pomyłka ręki byłaby wieczna, ale
    i cudzy zapis nie ma prawa zniknąć po cichu."""
    con = _baza()
    cam = _kamera(con)
    stary, nowy = _teleskop(con, "ED120R", 789), _teleskop(con, "RC8R", 1200)
    a = _klatka(con, "aaa", camera_id=cam)
    repo.user_assign_config(con, frame_ids=[a], telescope_id=stary, now=NOW)
    cfg_stary = con.execute("SELECT config_id FROM frame WHERE id=?", (a,)).fetchone()[0]

    g = repo.user_assign_config(con, frame_ids=[a], telescope_id=nowy, now=NOW)
    assert (g.assigned, g.occupied) == (0, 1)
    assert con.execute("SELECT config_id FROM frame WHERE id=?", (a,)).fetchone()[0] == cfg_stary


def test_nadpisanie_emituje_pare_verbow():
    """PARYTET (G1-4): przepięcie zmienia stan o ZERO (dalej jeden config), więc samo
    `config.assigned` zawyżyłoby dziennik na zawsze — a bramka świeciłaby zielono."""
    con = _baza()
    cam = _kamera(con)
    stary, nowy = _teleskop(con, "ED120R", 789), _teleskop(con, "RC8R", 1200)
    a = _klatka(con, "aaa", camera_id=cam)
    repo.user_assign_config(con, frame_ids=[a], telescope_id=stary, now=NOW)

    g = repo.user_assign_config(con, frame_ids=[a], telescope_id=nowy, now=NOW, overwrite=True)
    assert g.assigned == 1
    parytet = {p.name: p for p in audit.entity_event_parity(con)}["frame.config_id"]
    assert parytet.ok, (parytet.entities, parytet.events, parytet.retracted)


def test_gest_powtorzony_jest_idempotentny():
    """Kanon repo: powtórzony gest nie zaśmieca dziennika. Ten sam zestaw tą samą ręką ⇒ zero DML,
    zero eventu — i osobny licznik, żeby raport nie nazywał tego „zajęte"."""
    con = _baza()
    cam, tel = _kamera(con), _teleskop(con)
    a = _klatka(con, "aaa", camera_id=cam)
    repo.user_assign_config(con, frame_ids=[a], telescope_id=tel, now=NOW)

    g = repo.user_assign_config(con, frame_ids=[a], telescope_id=tel, now=NOW)
    assert (g.assigned, g.unchanged, g.occupied) == (0, 1, 0)
    assert con.execute("SELECT count(*) FROM event WHERE verb='config.assigned'").fetchone()[0] == 1


def test_przerwanie_gestu_nie_zostawia_polowy():
    """G1-12. Klatka, której nie ma, znaczy nieaktualną listę u wołającego — cała grupa wraca,
    a nie „ile się dało" (jedna transakcja `_immediate`, jak `user_assign_object`)."""
    con = _baza()
    cam, tel = _kamera(con), _teleskop(con)
    a = _klatka(con, "aaa", camera_id=cam)

    with pytest.raises(ValueError):
        repo.user_assign_config(con, frame_ids=[a, 99999], telescope_id=tel, now=NOW)
    assert con.execute("SELECT config_id FROM frame WHERE id=?", (a,)).fetchone()[0] is None
    assert con.execute("SELECT count(*) FROM config").fetchone()[0] == 0     # także POWOŁANY config
    assert con.execute("SELECT count(*) FROM event WHERE verb LIKE 'config.%'").fetchone()[0] == 0


def test_gest_odmawia_nieistniejacego_teleskopu():
    con = _baza()
    a = _klatka(con, "aaa", camera_id=_kamera(con))
    with pytest.raises(ValueError):
        repo.user_assign_config(con, frame_ids=[a], telescope_id=4242, now=NOW)


# ---------------------------------------------------------------- R1b: lepkość wobec przebiegu

def test_reka_przezywa_dwa_przebiegi_groupera():
    """G1-5 — SEDNO R1b. Bez tego pierwsze „Przetwórz wszystko" po geście zdejmowało fakt
    człowieka, a dla RAW-a przez teleskop robiło to wartością WPROST fałszywą (nazwa OBIEKTYWU)."""
    con = _baza()
    cam, tel = _kamera(con), _teleskop(con)
    # Klatka z nazwą OBIEKTYWU w nagłówku — dokładnie sytuacja RAW-a z lustrzanki (E3-3)
    a = _klatka(con, "aaa", camera_id=cam, telescop="105mm F1.4 DG HSM | Art 018")
    repo.user_assign_config(con, frame_ids=[a], telescope_id=tel, now=NOW)
    cfg_reki = con.execute("SELECT config_id FROM frame WHERE id=?", (a,)).fetchone()[0]

    grouper.run_grouper(con, now=NOW)
    s = grouper.run_grouper(con, now=NOW)              # DRUGI przebieg — tu pękał fakt człowieka
    assert s.config_by_hand == 1 and s.config_review == 0
    row = con.execute("SELECT config_id, config_source FROM frame WHERE id=?", (a,)).fetchone()
    assert tuple(row) == (cfg_reki, "user")
    # …i ANI JEDNEGO zdarzenia przeglądu: kolejka roboty nie ma prawa mówić o robocie wykonanej
    assert con.execute("SELECT count(*) FROM event WHERE verb='config.review'").fetchone()[0] == 0


def test_licznik_kubelka_spada_po_gescie():
    """Kubełek `config-review` liczy ze STANU (`resolver.review_state`), więc gest ma go ZMNIEJSZYĆ.
    To jest sprawdzenie odwrotnej strony R1b: nie tylko „automat nie psuje", ale „licznik reaguje"."""
    con = _baza()
    cam, tel = _kamera(con), _teleskop(con)
    a = _klatka(con, "aaa", camera_id=cam)
    grouper.run_grouper(con, now=NOW)
    assert resolver.review_state(con).no_config == 1

    repo.user_assign_config(con, frame_ids=[a], telescope_id=tel, now=NOW)
    assert resolver.review_state(con).no_config == 0


def test_klinga_automatu_odmawia_klatce_reki():
    """Guard stoi TAKŻE w `assign_config` — to jedyne miejsce, przez które przechodzą OBAJ pisarze
    osi. Grouper ma własne wyjście z pętli, ale klinga broni każdego przyszłego wołającego."""
    con = _baza()
    cam, tel = _kamera(con), _teleskop(con)
    a = _klatka(con, "aaa", camera_id=cam)
    repo.user_assign_config(con, frame_ids=[a], telescope_id=tel, now=NOW)
    obcy, _ = repo.propose_config(con, telescope_id=_teleskop(con, "N800", 800),
                                  camera_id=cam, now=NOW)

    assert repo.assign_config(con, frame_id=a, config_id=obcy, now=NOW) is False
    assert con.execute("SELECT config_source FROM frame WHERE id=?", (a,)).fetchone()[0] == "user"


# ---------------------------------------------------------------- G1-8: szew z R4 (podmiana pliku)

def _podmiana(con, path, stara, nowa):
    lid, _ = repo.add_location(con, frame_id=stara, volume="TESTVOL", path=path, now=NOW)
    repo.rebind_location(con, location_id=lid, frame_after=nowa, now=NOW)
    repo.mark_superseded(con, frame_id=stara, superseded_by=nowa, now=NOW)


def test_podmiana_pliku_przenosi_oba_fakty_reki():
    """G1-8. Edytor RAW dopisuje XMP wprost do DNG, więc `sha1` całego pliku się zmienia i ta sama
    fotografia wraca jako INNA tożsamość. Oba werdykty ręki mają przejść — obiekt i zestaw."""
    con = _baza()
    cam, tel = _kamera(con), _teleskop(con)
    oid, _ = repo.upsert_object(con, canon="IC443", catalog="IC", kind=None, now=NOW)
    stara = _klatka(con, "aaa", camera_id=cam)
    nowa = _klatka(con, "bbb", camera_id=cam)
    repo.assign_object(con, frame_id=stara, object_id=oid, object_source="user", now=NOW)
    repo.user_assign_config(con, frame_ids=[stara], telescope_id=tel, now=NOW)
    cfg = con.execute("SELECT config_id FROM frame WHERE id=?", (stara,)).fetchone()[0]
    _podmiana(con, r"R:\ASTRO_\LIGHTS\IC443\portable\DSC5560.dng", stara, nowa)

    assert supersede.pending_transfer(con) == [(stara, nowa, "obiekt+config")]
    t = repo.transfer_human_facts(con, frame_id=stara, now=NOW)
    assert (t.object_moved, t.config_moved, t.skipped) == (True, True, "")
    row = con.execute("SELECT object_id, object_source, config_id, config_source "
                      "FROM frame WHERE id=?", (nowa,)).fetchone()
    assert tuple(row) == (oid, "user", cfg, "user")
    assert supersede.pending_transfer(con) == []               # kubełek się domknął
    # Stara ZOSTAJE nietknięta (append-only); parytet dziennika nie ma prawa drgnąć
    assert con.execute("SELECT config_id FROM frame WHERE id=?", (stara,)).fetchone()[0] == cfg
    assert {p.name: p for p in audit.entity_event_parity(con)}["frame.config_id"].ok


def test_inwarianty_5_16_sa_zielone_po_gescie():
    """§5.16 — bramka zbudowana jak §5.15: pyta o INWARIANTY, nie o liczbę, bo na świeżej bazie
    dawcy populacja ręcznych zestawów jest zerowa. Zielone po realnym geście, nie na pustej bazie."""
    con = _baza()
    cam, tel = _kamera(con), _teleskop(con)
    a = _klatka(con, "aaa", camera_id=cam)
    repo.user_assign_config(con, frame_ids=[a], telescope_id=tel, now=NOW)

    assert audit.config_source_invariants(con) == {
        "reka_bez_sladu": 0, "reka_bez_osi": 0, "reka_na_kalibracji": 0}


def test_inwariant_lapie_wstrzykniecie_z_pominieciem_klingi(tmp_path):
    """Falsyfikator inwariantu: zapis gołym SQL-em (bez klingi) MA zaczerwienić bramkę — inaczej
    §5.16 pinowałaby własną nieobecność zamiast czegokolwiek."""
    path = str(tmp_path / "h.db")
    con = db.open_db(path)
    cam, tel = _kamera(con), _teleskop(con)
    a = _klatka(con, "aaa", camera_id=cam)
    cfg, _ = repo.propose_config(con, telescope_id=tel, camera_id=cam, now=NOW)
    con.close()

    goly = sqlite3.connect(path)                     # z pominięciem `repo` — brak eventu człowieka
    goly.execute("UPDATE frame SET config_id = ?, config_source = 'user' WHERE id = ?", (cfg, a))
    goly.commit()
    goly.close()

    con = db.open_db(path)
    assert audit.config_source_invariants(con)["reka_bez_sladu"] == 1


def test_nastepczyni_z_wlasnym_configiem_nie_dostaje_cudzego():
    """Guard osi sprzętu pyta o CAŁĄ oś, nie o źródło — bo `config_source` zapisuje wyłącznie ręka
    (0015), więc predykat „źródło puste" przepuszczałby zawsze i zamalowywał zeznanie pliku."""
    con = _baza()
    cam, tel = _kamera(con), _teleskop(con)
    stara = _klatka(con, "aaa", camera_id=cam)
    nowa = _klatka(con, "bbb", camera_id=cam, telescop="ED120R")
    repo.user_assign_config(con, frame_ids=[stara], telescope_id=tel, now=NOW)
    _podmiana(con, r"R:\ASTRO_\LIGHTS\IC443\portable\DSC5560.dng", stara, nowa)
    grouper.run_grouper(con, now=NOW)                  # następczyni sama zeznała o teleskopie
    wlasny = con.execute("SELECT config_id FROM frame WHERE id=?", (nowa,)).fetchone()[0]
    assert wlasny is not None

    assert supersede.pending_transfer(con) == []       # nie ma czego przenosić — przemówiła sama
    t = repo.transfer_human_facts(con, frame_id=stara, now=NOW)
    assert (t.config_moved, t.skipped) == (False, "nastepczyni ma wlasne zrodlo")
    assert con.execute("SELECT config_id, config_source FROM frame WHERE id=?",
                       (nowa,)).fetchone()[:] == (wlasny, None)
