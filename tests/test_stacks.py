"""RODOWÓD GOTOWYCH STOSÓW (`horreum.stacks`, segment I-2c paczki P-I).

Testy pinują to, co na realnym archiwum okazało się rozstrzygające, a nie samą szczęśliwą ścieżkę:
trójstan `asserted_by`, strażnik okna zdegenerowanego (24 ze 128 stosów NAS), rozjazd zeznań
o teleskopie (7 stosów — karta `ED`/`EQMOD HEQ5/6` przy klatkach `ED120R`), nierozłączność okien
(104 ze 128) oraz reconcile, który NIE rusza rozstrzygnięcia ręki.
"""
import json

import pytest

from horreum import db, repo
from horreum.stacks import REASON_DEGENERATE, REASON_MISMATCH, REASON_NO_OBJECT, \
    REASON_NO_CANDIDATES, REASON_TELESCOPE, inputs_of, run_stack_lineage

NOW = "2026-08-02T12:00:00+00:00"
LATER = "2026-08-02T13:00:00+00:00"
STOS = r"R:\ARCHIWUM\A140R\CTB1\WBPP\master\masterLight_EXPOSURE-600.00s_FILTER-H.xisf"

# Nazwa WBPP w wariancie PEŁNYM (z temperaturą) — jedyna, na której da się sprawdzić TOŻSAMOŚĆ
# zbioru, nie sam licznik (`resolve.stack.inputs_contained`).
_WBPP = ("D:/robocze/CTB1/wbpp/registered/"
         "CTB 1_LIGHT_GRP-MM_FILTER-H_600.00s_{idx}_2.98_0.56_{temp}C_c_r.xisf")


def _xml_historii(temperatury, *, drizzle=True, enabled=True):
    """Nagłówek XISF z własnością `PixInsight:ProcessingHistory` (treść zaescape'owana, jak
    w realnym pliku) — tabela `images` z wejściami plus `imageData` z własnymi wierszami."""
    wiersze = []
    for i, t in enumerate(temperatury):
        td = f'&lt;td id="enabled" value="{"true" if enabled else "false"}"/&gt;'
        td += f'&lt;td id="path"&gt;{_WBPP.format(idx=f"{i:04d}", temp=f"{t:.2f}")}&lt;/td&gt;'
        if drizzle:
            td += '&lt;td id="drizzlePath"&gt;x.xdrz&lt;/td&gt;'
        wiersze.append(f"&lt;tr&gt;{td}&lt;/tr&gt;")
    return ('<xisf><Property id="PCL:Signature:Integration" type="String">'
            'process=ImageIntegration,version=1.7.1</Property>'
            '<Property id="PixInsight:ProcessingHistory" type="String">'
            f'&lt;table id="images" rows="{len(temperatury)}"&gt;{"".join(wiersze)}&lt;/table&gt;'
            '&lt;table id="imageData" rows="1"&gt;&lt;tr&gt;&lt;td id="enabled" value="false"/&gt;'
            '&lt;/tr&gt;&lt;/table&gt;</Property></xisf>')


@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "h.db"))
    c.execute("INSERT INTO camera(model_canon, created_at) VALUES ('ASI2600MM', ?)", (NOW,))
    c.executemany("INSERT INTO telescope(telescop_canon, status, created_at) VALUES (?, ?, ?)",
                  [("A140R", "proposed", NOW), ("RC8", "proposed", NOW)])
    c.executemany("INSERT INTO config(telescope_id, camera_id, status, created_at) "
                  "VALUES (?, 1, 'proposed', ?)", [(1, NOW), (2, NOW)])
    c.execute("INSERT INTO object(canon, catalog, kind) VALUES ('CTB1', 'catalog', 'deep_sky')")
    c.commit()
    yield c
    c.close()


def _light(con, sha1, *, date_obs, exptime=600.0, ccd_temp=-10.0, filter_canon="Ha",
           config_id=1, object_id=1):
    cur = con.execute(
        "INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, "
        "filter_canon, first_seen_at) VALUES (?, 'light', 'fits', 1, ?, ?, ?, ?)",
        (sha1, config_id, object_id, filter_canon, NOW))
    fid = cur.lastrowid
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, exptime, ccd_temp) "
                "VALUES (?, '{}', ?, ?, ?)", (fid, date_obs, exptime, ccd_temp))
    con.commit()
    return fid


def _master(con, sha1="m1", *, start="2025-08-30T20:00:00", end="2025-08-30T23:00:00",
            exptime=600.0, filter_canon="Ha", config_id=1, object_id=1, path=STOS,
            telescop="A140R"):
    """Klatka stosu + jej ZEZNANIE (`header.raw_json` — okno czasu żyje TAM, nie w kolumnach)."""
    raw = {"IMAGETYP": "Master Light", "OBJECT": "CTB 1", "FILTER": "H", "EXPTIME": exptime,
           "TELESCOP": telescop, "DATE-OBS": start, "DATE-END": end}
    cur = con.execute(
        "INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, "
        "filter_canon, first_seen_at) VALUES (?, 'master_light', 'xisf', 1, ?, ?, ?, ?)",
        (sha1, config_id, object_id, filter_canon, NOW))
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


def test_okno_wybiera_klatki_nocy_i_odrzuca_sasiednie(con):
    """Ścieżka podstawowa: bez historii jedynym materiałem jest OKNO — klatki spoza niego nie
    wchodzą, a relacja jest KANDYDATEM (`window`), nigdy faktem."""
    m = _master(con)
    w1 = _light(con, "l1", date_obs="2025-08-30T20:30:00")
    w2 = _light(con, "l2", date_obs="2025-08-30T22:59:59")
    _light(con, "l3", date_obs="2025-08-31T01:00:00")            # następna noc — poza oknem
    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert (s.stacks, s.linked, s.inputs) == (1, 1, 2)
    assert s.by_assert == {"window": 1}
    assert [r["input_frame_id"] for r in inputs_of(con, m)] == [w1, w2]
    assert {r["asserted_by"] for r in inputs_of(con, m)} == {"window"}
    row = _integracja(con, m)
    assert row["unresolved_reason"] is None and row["declared_rows"] is None
    assert row["window_start"].startswith("2025-08-30T20:00")


def test_historia_potwierdza_zbior_i_podnosi_zrodlo_pewnosci(con):
    """Gdy plik zeznaje, z czego powstał, a test ZAWIERANIA przechodzi — relacja jest `history`.
    Fakty historii (ile wejść, drizzle, wyłączone) siedzą na INTEGRACJI, bo ścieżek z historii nie
    da się przypiąć do klatek archiwum (zmierzone 0/36 dopasowań po nazwie)."""
    m = _master(con)
    _light(con, "l1", date_obs="2025-08-30T20:30:00", ccd_temp=-10.0)
    _light(con, "l2", date_obs="2025-08-30T21:30:00", ccd_temp=-9.9)
    s = run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml_historii([-10.0, -9.9]))

    assert s.by_assert == {"history": 1} and s.inputs == 2
    assert {r["asserted_by"] for r in inputs_of(con, m)} == {"history"}
    row = _integracja(con, m)
    assert (row["declared_rows"], row["drizzle_inputs"], row["disabled_inputs"]) == (2, 2, 0)
    assert row["tool"].startswith("process=ImageIntegration")


def test_rozjazd_z_historia_gasi_relacje_zamiast_zmyslac(con):
    """Historia mówi o klatce -20 °C, której okno nie zna → myli się OKNO. Zero relacji i POWÓD
    w bazie; wariant „zapisz co znalazłeś" byłby cichą nieprawdą o zawartości obrazu."""
    m = _master(con)
    _light(con, "l1", date_obs="2025-08-30T20:30:00", ccd_temp=-10.0)
    s = run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml_historii([-10.0, -20.0]))

    assert s.linked == 0 and s.reasons == {REASON_MISMATCH: 1}
    assert _integracja(con, m)["unresolved_reason"] == REASON_MISMATCH
    assert inputs_of(con, m) == []


def test_okno_zdegenerowane_nie_dostaje_ani_jednej_relacji(con):
    """`DATE-END == DATE-OBS + EXPTIME` znaczy „nagłówek opisuje JEDNĄ klatkę" (24 ze 128 stosów
    NAS). Bez tego strażnika stos dostałby jeden sub i wyglądałby wiarygodnie."""
    m = _master(con, start="2025-08-30T20:00:00", end="2025-08-30T20:10:00")   # span == exptime
    _light(con, "l1", date_obs="2025-08-30T20:05:00")
    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert s.reasons == {REASON_DEGENERATE: 1} and s.inputs == 0
    row = _integracja(con, m)
    assert (row["degenerate"], row["unresolved_reason"]) == (1, REASON_DEGENERATE)


def test_stos_bez_obiektu_ma_wiersz_i_powod(con):
    """Wiersz integracji powstaje TAKŻE bez wejść: „to jest stos, ale nie wiem z czego" jest faktem
    i musi być odróżnialne od „jeszcze nie liczyliśmy" (18 ze 128 stosów NAS)."""
    m = _master(con, object_id=None)
    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert s.reasons == {REASON_NO_OBJECT: 1}
    assert _integracja(con, m)["unresolved_reason"] == REASON_NO_OBJECT


def test_puste_okno_to_inny_powod_niz_rozjazd_teleskopu(con):
    """Okno bez ANI JEDNEJ klatki (inna noc w archiwum) to `no_candidates` — powód rozłączny
    z rozjazdem osi, bo prowadzi do innej naprawy (dostawa klatek, nie edycja karty)."""
    _master(con)
    _light(con, "l1", date_obs="2025-09-30T20:30:00")
    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    assert s.reasons == {REASON_NO_CANDIDATES: 1}


def test_teleskop_rozstrzyga_gdy_umie(con):
    """Gdy okno MIESZA teleskopy, a jeden z nich jest masterowy — bierzemy wyłącznie jego klatki.
    Oś rozstrzyga tam, gdzie ma czym; rozluźnienie niżej dotyczy tylko okna JEDNORODNEGO."""
    m = _master(con, config_id=1)
    moje = _light(con, "l1", date_obs="2025-08-30T20:30:00", config_id=1)
    _light(con, "l2", date_obs="2025-08-30T20:31:00", config_id=2)            # inny teleskop
    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert [r["input_frame_id"] for r in inputs_of(con, m)] == [moje]
    assert s.telescope_mismatch == 0


def test_jednorodne_okno_z_innego_teleskopu_wchodzi_ale_z_flaga(con):
    """SZEW DWÓCH ZEZNAŃ: master niesie kartę przestarzałą (`ED` naprawione już w archiwum) albo
    śmieciową (nazwa montażu), a wszystkie klatki nocy są z jednego, INNEGO teleskopu. Zmierzone
    na realnym archiwum: 81 z 81 niepustych okien jest teleskopowo JEDNORODNYCH, więc ta oś nigdy
    nie wybierała MIĘDZY klatkami — umiała tylko odrzucić wszystkie (7 stosów). Bierzemy je jako
    kandydatów i podnosimy flagę: rodowód jest, a karta czeka na naprawę."""
    m = _master(con, config_id=2, telescop="ED")               # master: RC8; klatki: A140R
    lid = _light(con, "l1", date_obs="2025-08-30T20:30:00", config_id=1)
    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert s.linked == 1 and s.telescope_mismatch == 1
    assert [r["input_frame_id"] for r in inputs_of(con, m)] == [lid]
    assert _integracja(con, m)["telescope_mismatch"] == 1


def test_okno_mieszane_bez_teleskopu_mastera_odmawia_z_wlasnym_powodem(con):
    """Okno miesza dwa teleskopy i ŻADEN nie jest masterowy → nie ma czym rozstrzygnąć. Powód
    nazywa oś, nie brak kandydatów — inaczej raport kłamałby o przyczynie."""
    con.execute("INSERT INTO telescope(telescop_canon, status, created_at) VALUES ('N800', 'p', ?)",
                (NOW,))
    con.execute("INSERT INTO config(telescope_id, camera_id, status, created_at) "
                "VALUES (3, 1, 'p', ?)", (NOW,))
    con.commit()
    _master(con, config_id=3)
    _light(con, "l1", date_obs="2025-08-30T20:30:00", config_id=1)
    _light(con, "l2", date_obs="2025-08-30T20:31:00", config_id=2)
    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert s.reasons == {REASON_TELESCOPE: 1} and s.linked == 0
    # RECENZJA #11: rozjazd, który skończył się ODMOWĄ, siedzi już w `reasons` — wspólny licznik
    # meldował go drugi raz jako flagę i kazał raportowi mówić „karta do naprawy" o stosie, przy
    # którym nie zapisano niczego. Flagą jest wyłącznie rozjazd, który rodowodu NIE zablokował.
    assert s.telescope_mismatch == 0


def test_okna_nierozlaczne_flagowane_po_obu_stronach(con):
    """Reprocessing tej samej nocy: dwa stosy tej samej PÓŁKI o nakładających się oknach dzielą te
    same suby (104 ze 128 na realnym archiwum). `integration_input` jest wtedy POKRYCIEM, nie
    podziałem — most do planera musi taki sub policzyć RAZ."""
    a = _master(con, "m1")
    b = _master(con, "m2", start="2025-08-30T21:00:00", end="2025-08-31T00:00:00", path=None)
    _light(con, "l1", date_obs="2025-08-30T21:30:00")
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)

    assert _integracja(con, a)["ambiguous"] == 1 and _integracja(con, b)["ambiguous"] == 1


def test_drugi_przebieg_nie_pisze_nic(con):
    """Idempotencja stoi na UNIQUE z 0012, nie na kodzie: drugi przebieg = zero nowych wierszy
    i zero eventów `linked`/`recorded` (`lineage_summary` emituje się nadal — to event audytowy
    o STANIE, dlatego kryteria bramki liczą DISTINCT sprawy, nie zdarzenia)."""
    _master(con)
    _light(con, "l1", date_obs="2025-08-30T20:30:00")
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    przed = con.execute("SELECT count(*) FROM event WHERE verb IN ('integration.linked', "
                        "'integration.recorded', 'integration.updated')").fetchone()[0]

    s2 = run_stack_lineage(con, now=LATER, xml_reader=_brak_xml)
    po = con.execute("SELECT count(*) FROM event WHERE verb IN ('integration.linked', "
                     "'integration.recorded', 'integration.updated')").fetchone()[0]
    assert (s2.linked_new, s2.unlinked, po) == (0, 0, przed)
    assert con.execute("SELECT count(*) FROM integration").fetchone()[0] == 1


def test_powtorka_to_zero_wierszy_i_JEDNO_zdarzenie_zbiorcze_na_przebieg(con):
    """Pin zdania z docstringu `run_stack_lineage` (E2-1): powtórka na niezmienionych danych daje
    zero wierszy i zero zdarzeń ZAPISU, ale `integration.lineage_summary` leci RAZ na KAŻDY
    przebieg, gdy jest stos bez rodowodu - bo opisuje STAN, nie deltę. Stare zdanie („ZERO
    eventów") było prawdą tylko dla archiwum bez ani jednego powodu.

    Stąd reguła dla liczących: sprawy liczy się ze STANU albo `count(DISTINCT target)` -
    `count(event)` rośnie z liczbą przebiegów (tu: 1 sprawa, 2 zdarzenia po dwóch przebiegach)."""
    _master(con)                                         # bez klatek → `no_candidates`
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    wiersze = [con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
               for t in ("integration", "integration_input")]
    zapis = con.execute("SELECT count(*) FROM event WHERE verb IN ('integration.recorded', "
                        "'integration.updated', 'integration.linked', "
                        "'integration.unlinked')").fetchone()[0]

    run_stack_lineage(con, now=LATER, xml_reader=_brak_xml)
    assert [con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("integration", "integration_input")] == wiersze
    assert con.execute("SELECT count(*) FROM event WHERE verb IN ('integration.recorded', "
                       "'integration.updated', 'integration.linked', "
                       "'integration.unlinked')").fetchone()[0] == zapis
    assert con.execute("SELECT count(*), count(DISTINCT target) FROM event "
                       "WHERE verb = 'integration.lineage_summary'").fetchone()[:] == (2, 1)


def test_reconcile_zdejmuje_wypadle_wejscie_ale_nie_rusza_reki(con):
    """Zmiana dopasowania w modelu append-only: wiersz relacji znika, ślad zostaje w dzienniku
    (`integration.unlinked`). Relacji potwierdzonej RĘKĄ automat nie cofa — to warunek nierozłączny
    od trójstanu, bez niego powierzchnia I-2d oddawałaby decyzję usera przy każdym przebiegu."""
    m = _master(con)
    wypadnie = _light(con, "l1", date_obs="2025-08-30T20:30:00")
    reka = _light(con, "l2", date_obs="2025-08-30T20:40:00")
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    iid = _integracja(con, m)["id"]
    con.execute("UPDATE integration_input SET asserted_by = 'user' WHERE input_frame_id = ?",
                (reka,))
    con.execute("UPDATE header SET date_obs = '2024-01-01T00:00:00' WHERE frame_id = ?",
                (wypadnie,))
    con.commit()

    s = run_stack_lineage(con, now=LATER, xml_reader=_brak_xml)
    zostaly = {(r["input_frame_id"], r["asserted_by"]) for r in inputs_of(con, m)}
    assert s.unlinked == 1 and zostaly == {(reka, "user")}
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'integration.unlinked'"
                       ).fetchone()[0] == 1


def test_odcisk_zbioru_zmienia_sie_ze_skladem_i_zostawia_slad(con):
    """`integ_hash` to ODCISK BIEŻĄCEGO DOPASOWANIA, nie klucz (§4.1 briefu): dołożenie klatki
    w oknie zmienia odcisk i podnosi `integration.updated`, ale NIE tworzy drugiej integracji."""
    m = _master(con)
    _light(con, "l1", date_obs="2025-08-30T20:30:00")
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    odcisk1 = _integracja(con, m)["integ_hash"]

    _light(con, "l2", date_obs="2025-08-30T21:30:00")
    run_stack_lineage(con, now=LATER, xml_reader=_brak_xml)
    row = _integracja(con, m)
    assert row["integ_hash"] != odcisk1 and row["updated_at"] == LATER
    assert con.execute("SELECT count(*) FROM integration").fetchone()[0] == 1


def test_plik_poza_zasiegiem_schodzi_na_okno_i_jest_policzony(con):
    """Historia mieszka w PLIKU, nie w bazie. Gdy plik jest nieosiągalny (dysk odłączony), stos
    idzie ścieżką okna, a fakt braku odczytu jest LICZONY — nie przemilczany."""
    def _wybuch(_p):
        raise OSError("dysk odłączony")

    _master(con)
    _light(con, "l1", date_obs="2025-08-30T20:30:00")
    s = run_stack_lineage(con, now=NOW, xml_reader=_wybuch)
    assert (s.history_unread, s.by_assert) == (1, {"window": 1})


def test_nieprzeczytane_zeznanie_NIE_degraduje_gotowego_rodowodu(con):
    """RECENZJA P1 #2 — najgroźniejszy szew tego modułu. Gdy plik jest poza zasięgiem, plan spada
    na samo okno, bo `t.rows is None`; bez strażnika drugi przebieg (np. bez zamontowanego `R:`)
    NADPISYWAŁBY dowiedziony rodowód kandydatami: `history` → `window`, plus wejścia, których
    historia nie potwierdza (test zawierania jest wtedy pomijany).

    Dowód pewności ma przeżyć NIEOBECNOŚĆ dowodu — brak odczytu to brak wiedzy, nie nowa wiedza."""
    m = _master(con)
    _light(con, "l1", date_obs="2025-08-30T20:30:00", ccd_temp=-10.0)
    _light(con, "l2", date_obs="2025-08-30T21:30:00", ccd_temp=-9.9)
    run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml_historii([-10.0, -9.9]))
    assert {r["asserted_by"] for r in inputs_of(con, m)} == {"history"}

    def _wybuch(_p):
        raise OSError("dysk odłączony")

    s = run_stack_lineage(con, now=NOW, xml_reader=_wybuch)
    assert {r["asserted_by"] for r in inputs_of(con, m)} == {"history"}   # dowód przeżył
    assert (s.kept_unread, s.linked_new, s.unlinked) == (1, 0, 0)         # zero ruchu Z WYBORU


def test_powod_nie_dopisuje_sie_obok_zachowanych_wierszy_dowiedzionych(con):
    """TURA 2 #1 — defekt WPROWADZONY przez strażnika 4, zawężony w turze 3. Powodu NIE DA SIĘ
    zapisać, nie kasując wierszy (inwariant §5.14 „powód wyklucza wejścia automatu"), a kasować
    wierszy DOWIEDZIONYCH nie wolno, gdy plik akurat milczy. Taki stos zostaje w spokoju w całości.

    Dotyczy WYŁĄCZNIE rodowodu `history` — to on stoi na zeznaniu pliku."""
    m = _master(con)
    _light(con, "l1", date_obs="2025-08-30T20:30:00", ccd_temp=-10.0)
    run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml_historii([-10.0]))
    assert {r["asserted_by"] for r in inputs_of(con, m)} == {"history"}

    con.execute("UPDATE frame SET object_id = NULL WHERE id = ?", (m,))   # powód z BAZY
    con.commit()

    def _wybuch(_p):
        raise OSError("dysk odłączony")

    s = run_stack_lineage(con, now=NOW, xml_reader=_wybuch)
    assert _integracja(con, m)["unresolved_reason"] is None      # głowy też nie ruszamy
    assert len(inputs_of(con, m)) == 1
    assert s.kept_unread == 1 and s.reasons == {}


def test_rodowod_z_okna_aktualizuje_sie_mimo_nieczytelnego_pliku(con):
    """TURA 3 #3 — zakres strażnika idzie ZA ŹRÓDŁEM FAKTU. Rodowód `window` nie stoi na zeznaniu
    pliku ani w jednym kawałku (okno, osie i powód liczy się z BAZY), więc przebieg bez pliku ma
    o nim pełną wiedzę i MUSI go zaktualizować. Strażnik zamrażający wszystko zostawiał tu master
    po naprawie karty z relacjami do lightów INNEGO obiektu — cicha nieprawda, której zakazuje
    nagłówek modułu. Na realnym archiwum dotyczyło to 122 ze 128 stosów."""
    m = _master(con)
    _light(con, "l1", date_obs="2025-08-30T20:30:00")
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    assert {r["asserted_by"] for r in inputs_of(con, m)} == {"window"}

    con.execute("UPDATE frame SET object_id = NULL WHERE id = ?", (m,))
    con.commit()

    def _wybuch(_p):
        raise OSError("dysk odłączony")

    s = run_stack_lineage(con, now=NOW, xml_reader=_wybuch)
    assert _integracja(con, m)["unresolved_reason"] == REASON_NO_OBJECT
    assert inputs_of(con, m) == []          # reconcile zdjął relacje do cudzego obiektu
    assert s.kept_unread == 0 and s.reasons == {REASON_NO_OBJECT: 1}


def test_nieprzeczytane_zeznanie_nie_kasuje_faktow_historii(con):
    """TURA 2 #2 — druga połowa tego samego defektu. `t.rows`/`t.tool` są przy nieodczytanym pliku
    `None`, więc `upsert_integration` wołany bezwarunkowo KASOWAŁ fakty zeznania (`declared_rows`,
    `tool`, drizzle) na integracji, której wiersze `history` właśnie zachowaliśmy obok — panel
    mówił „plik zeznał" i nie umiał powiedzieć, ile ten plik deklaruje."""
    m = _master(con)
    _light(con, "l1", date_obs="2025-08-30T20:30:00", ccd_temp=-10.0)
    _light(con, "l2", date_obs="2025-08-30T21:30:00", ccd_temp=-9.9)
    run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml_historii([-10.0, -9.9]))
    przed = _integracja(con, m)
    assert (przed["declared_rows"], przed["drizzle_inputs"]) == (2, 2)

    def _wybuch(_p):
        raise OSError("dysk odłączony")

    run_stack_lineage(con, now=NOW, xml_reader=_wybuch)
    po = _integracja(con, m)
    assert (po["declared_rows"], po["drizzle_inputs"], po["tool"]) == \
           (przed["declared_rows"], przed["drizzle_inputs"], przed["tool"])


def test_potwierdzenie_reka_chroni_rodowod_tak_jak_zeznanie_pliku(con):
    """TURA 4 #4: predykat ochrony na literale `'history'` gubił werdykt ręki — a potwierdzenie
    („tak, ta klatka weszła") jest zeznaniem MOCNIEJSZYM niż plik. Stos potwierdzony ręką stawał
    się nieochroniony i przy powodzie z bazy dostawał `unresolved_reason` obok niewykluczonych
    wierszy `user`, czyli dokładnie ten stan, który tura 2 nazwała defektem — a bramka §5.14 jest
    na niego ślepa z założenia (`asserted_by <> 'user'`)."""
    m = _master(con)
    fid = _light(con, "l1", date_obs="2025-08-30T20:30:00")
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    iid = _integracja(con, m)["id"]
    repo.judge_integration_input(con, integration_id=iid, input_frame_id=fid,
                                 excluded=False, now=NOW)          # człowiek POTWIERDZA

    con.execute("UPDATE frame SET object_id = NULL WHERE id = ?", (m,))
    con.commit()

    def _wybuch(_p):
        raise OSError("dysk odłączony")

    s = run_stack_lineage(con, now=NOW, xml_reader=_wybuch)
    assert _integracja(con, m)["unresolved_reason"] is None
    assert len(inputs_of(con, m)) == 1
    assert s.kept_unread == 1 and s.by_assert == {"user": 1}


def test_nowy_sub_nie_rusza_werdyktu_reki_a_licznik_go_WIDZI(con):
    """P4-4 + warunek Zdzinia 0809 („wprowadzanie nowych subów nie może wpłynąć na wycofanie
    czegokolwiek ustawionego ręcznie") — na stosie MIESZANYM, czyli tam, gdzie wjazd materiału
    stawia stos, którego dziś w archiwum nie ma ani jednego (0 na 128).

    DWIE RZECZY NARAZ, i one się nie wykluczają: wiersz ręki przeżywa przebieg (broni go klinga
    PER WIERSZ), a nowy sub normalnie wchodzi (bo najsłabsze wiersze są tak samo mocne jak plan
    — zamrożenie całego stosu po jednym geście byłoby obroną za szeroką, patrz
    `test_reconcile_zdejmuje_wypadle_wejscie_ale_nie_rusza_reki`).

    Naprawą P4-4 jest więc LICZNIK: do 0809 `by_assert` meldował taki stos jako `window`, czyli
    jako robotę automatu, i ręki nie było widać w żadnej liczbie."""
    m = _master(con)
    l1 = _light(con, "l1", date_obs="2025-08-30T20:30:00")
    l2 = _light(con, "l2", date_obs="2025-08-30T21:30:00")
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    iid = _integracja(con, m)["id"]
    repo.judge_integration_input(con, integration_id=iid, input_frame_id=l1,
                                 excluded=False, now=NOW)      # ręka potwierdza JEDNO wejście
    assert {r["asserted_by"] for r in inputs_of(con, m)} == {"user", "window"}

    l3 = _light(con, "l3", date_obs="2025-08-30T22:00:00")      # nowy sub wjeżdża w to samo okno
    s = run_stack_lineage(con, now=LATER, xml_reader=_brak_xml)

    assert s.by_assert == {"user": 1}                           # licznik widzi rękę (P4-4)
    assert {r["input_frame_id"] for r in inputs_of(con, m)} == {l1, l2, l3}
    zrodla = {r["input_frame_id"]: r["asserted_by"] for r in inputs_of(con, m)}
    assert zrodla == {l1: "user", l2: "window", l3: "window"}   # werdykt nietknięty, materiał doszedł


def test_odrzucenie_wszystkiego_nie_kasuje_faktow_zeznania_w_glowie(con):
    """TURA 4 #3: „czy są zapisane fakty zeznania" (głowa) NIE zależy od tego, czy jakikolwiek
    wiersz przeżył. Stos, z którego człowiek odrzucił wszystkie kandydatury, wciąż ma
    `declared_rows` z czasu, gdy plik był czytelny — a warunek `EXISTS` na wierszach kasował je
    przez `None` w UPDATE, wskrzeszając defekt naprawiony turę wcześniej."""
    m = _master(con)
    fid = _light(con, "l1", date_obs="2025-08-30T20:30:00", ccd_temp=-10.0)
    run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml_historii([-10.0]))
    przed = _integracja(con, m)
    assert przed["declared_rows"] == 1
    repo.judge_integration_input(con, integration_id=przed["id"], input_frame_id=fid,
                                 excluded=True, now=NOW)           # człowiek ODRZUCA wszystko

    def _wybuch(_p):
        raise OSError("dysk odłączony")

    run_stack_lineage(con, now=NOW, xml_reader=_wybuch)
    po = _integracja(con, m)
    assert (po["declared_rows"], po["tool"]) == (przed["declared_rows"], przed["tool"])


def test_dwie_przyczyny_pominiecia_licza_sie_osobno(con):
    """TURA 4 #1: `no_location` liczy CAŁĄ populację, a `kept_unread` tylko pominiętych — próg
    porównujący te dwa potrafił wskazać receptę stosu, którego wcale nie pominięto. Recepty są
    różne („podłącz archiwum" vs „puść skan"), więc licznik pominiętych bez kopii jest osobny."""
    m = _master(con)
    _light(con, "l1", date_obs="2025-08-30T20:30:00", ccd_temp=-10.0)
    run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml_historii([-10.0]))
    assert {r["asserted_by"] for r in inputs_of(con, m)} == {"history"}
    con.execute("UPDATE location SET present = 0 WHERE frame_id = ?", (m,))   # kopia znika
    con.commit()

    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    assert (s.kept_unread, s.kept_no_location) == (1, 1)   # pominięty Z POWODU braku kopii
    assert s.no_location == 1


def test_brak_obecnej_lokacji_liczy_sie_jak_nieodczytane_zeznanie(con):
    """Klatka mastera bez OBECNEJ kopii to ten sam stan, co błąd odczytu: pliku nie ma pod ręką,
    więc jego zeznania NIE ZNAMY. Wcześniej ta połowa populacji nie wchodziła do licznika w ogóle
    — a to na nim stoi decyzja „nie ruszaj gotowego rodowodu"."""
    _master(con, path=None)
    _light(con, "l1", date_obs="2025-08-30T20:30:00")
    s = run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    assert s.history_unread == 1


def test_ekspozycja_ze_stosu_jest_TEKSTEM_i_musi_dopasowac(con):
    """XISF oddaje KAŻDĄ kartę jako tekst, więc `EXPTIME` stosu to `'600.00'`, a `header.exptime`
    klatki to REAL. Bez jawnej koercji dopasowanie stoi na powinowactwie typów SQLite — działa,
    dopóki porównanie idzie przez kolumnę, i pęka po cichu wszędzie indziej (półka `shelf`).
    Ten test pinuje zachowanie na kształcie ZEZNANIA REALNEGO PLIKU, nie wygodnego floata."""
    m = _master(con)
    con.execute("UPDATE header SET raw_json = json_set(raw_json, '$.EXPTIME', '600.00') "
                "WHERE frame_id = ?", (m,))
    con.commit()
    lid = _light(con, "l1", date_obs="2025-08-30T20:30:00", exptime=600.0)
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    assert [r["input_frame_id"] for r in inputs_of(con, m)] == [lid]


def test_wejsciem_jest_wylacznie_light(con):
    """Kalibracja i inne stosy nie są subami. Populacja pinowana WPROST do `kind='light'` —
    lustro reguły z `lineage`, gdzie master_light celowo NIE wchodzi do rachunku lightów."""
    m = _master(con)
    con.execute("INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, "
                "filter_canon, first_seen_at) VALUES ('f1', 'flat', 'fits', 1, 1, 1, 'Ha', ?)",
                (NOW,))
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, exptime, ccd_temp) "
                "VALUES ((SELECT id FROM frame WHERE sha1_data='f1'), '{}', "
                "'2025-08-30T20:30:00', 600.0, -10.0)")
    con.commit()
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    assert inputs_of(con, m) == []


def test_repo_odmawia_zrodla_spoza_trojstanu(con):
    """Słownik `asserted_by` trzyma CHECK w BAZIE (0012), nie kod: baza jest ostatnią bramką
    i przeżyje każdą powierzchnię."""
    m = _master(con)
    iid, _ = repo.upsert_integration(
        con, master_frame_id=m, integ_hash=None, tool=None, window_start=None, window_end=None,
        declared_rows=None, drizzle_inputs=None, disabled_inputs=None, degenerate=0, ambiguous=0,
        telescope_mismatch=0, unresolved_reason=None, now=NOW)
    with pytest.raises(Exception):
        repo.link_integration(con, integration_id=iid, input_frame_id=m,
                              asserted_by="zgadywanie", now=NOW)


# ═════════════════════════ S2b §4/14c (i) — GESTY OSI OBIEKTU vs RODOWÓD


def test_cofniecie_NA_STOSIE_nie_kasuje_rodowodu_DOWIEDZIONEGO(con):
    """§4/14c-h/i po **D-OW-7**: gest „Cofnij" sięga gotowego obrazu — i wtedy rodowód broni się
    SAM, w przebiegu, a nie tym, że gest go omija.

    Do D-OW-7 klinga pomijała stos, bo odebranie `object_id` rozbraja `_window_candidates`
    i najbliższy przebieg degradował dowiedziony rodowód do „brak wejść". Ochrona zeszła do
    przebiegu (RANGA), więc gest wolno było otworzyć — ale to TU trzeba dowieść, że otwarcie nie
    kosztowało dowodu. Plik czytelny: rodowód `history` przeżywa, głowa nie dostaje powodu."""
    m, a, b, czytelny = _historia_dwoch(con)
    przed = {(r["input_frame_id"], r["asserted_by"]) for r in inputs_of(con, m)}
    con.execute("UPDATE frame SET object_source = 'user' WHERE id = ?", (m,))
    con.commit()

    g = repo.clear_object_assignment(con, frame_ids=[m, a, b], now=LATER)
    assert (g.assigned, g.stacks) == (1, 1)            # lighty mają źródło spoza ręki → nietknięte
    s = run_stack_lineage(con, now=LATER, xml_reader=czytelny)
    assert {(r["input_frame_id"], r["asserted_by"]) for r in inputs_of(con, m)} == przed
    assert (s.unlinked, s.kept_proven) == (0, 1)
    assert _integracja(con, m)["unresolved_reason"] is None      # głowa BEZ powodu


def test_cofniecie_NA_STOSIE_z_rodowodem_z_OKNA_przelicza_sie_uczciwie(con):
    """Człon LUSTRZANY D-OW-7 — bez niego „chroń stos zawsze" przeszłoby test wyżej.

    Rodowód `window` to DOBÓR z bieżącego stanu, a stos bez obiektu okna nie ma z definicji.
    Musi się więc uczciwie przeliczyć na `no_object`, a nie zastygnąć — inaczej gotowy obraz
    zostawałby z relacjami do lightów, których nic już z nim nie łączy."""
    m = _master(con)
    _light(con, "l1", date_obs="2025-08-30T20:30:00")
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    assert len(inputs_of(con, m)) == 1
    con.execute("UPDATE frame SET object_source = 'user' WHERE id = ?", (m,))
    con.commit()

    assert repo.clear_object_assignment(con, frame_ids=[m], now=LATER).assigned == 1
    s = run_stack_lineage(con, now=LATER, xml_reader=_brak_xml)
    assert inputs_of(con, m) == []
    assert (s.unlinked, s.kept_proven) == (1, 0)
    assert _integracja(con, m)["unresolved_reason"] == REASON_NO_OBJECT


def test_gest_na_LIGHCIE_zdejmuje_go_z_okna_ale_reszta_rodowodu_stoi(con):
    """§4/14c-i, człon LUSTRZANY — bez niego nadmiarowa ochrona byłaby NIEWYKRYWALNA.

    Rodowód ma być odporny na gest, ale NIE zamrożony: stos z czytelnym plikiem musi się dalej
    rekoncyliować. Light, któremu ręka zdjęła obiekt, WYPADA z okna — i to jest poprawne, bo okno
    jest doborem z bieżącego stanu. Gdyby implementacja „chroniła" rodowód przez zamrożenie relacji,
    ten człon zostałby czerwony, a poprzedni i tak by przeszedł."""
    m = _master(con)
    zostaje = _light(con, "l1", date_obs="2025-08-30T20:30:00")
    wypadnie = _light(con, "l2", date_obs="2025-08-30T20:40:00")
    run_stack_lineage(con, now=NOW, xml_reader=_brak_xml)
    assert len(inputs_of(con, m)) == 2

    con.execute("UPDATE frame SET object_source = 'user' WHERE id = ?", (wypadnie,))
    con.commit()
    g = repo.clear_object_assignment(con, frame_ids=[wypadnie], now=LATER)
    assert g.assigned == 1

    s = run_stack_lineage(con, now=LATER, xml_reader=_brak_xml)
    assert {r["input_frame_id"] for r in inputs_of(con, m)} == {zostaje}
    assert s.unlinked == 1


# ── rodowód DOWIEDZIONY (plik czytelny) wobec obu gestów — R26#4, domknięte adjudykacją S2b ──
# Oba testy wyżej jadą `_brak_xml`, więc rodowód stoi na samym OKNIE i kasowanie relacji jest tam
# poprawne. Klasy, dla której powstał strażnik, nie dotykały: `history` przy pliku LEŻĄCYM NA
# MIEJSCU. Recenzja diffu S2b znalazła, że ochrona liczyła się wtedy WYŁĄCZNIE przy nieczytelnym
# pliku, więc gest osi obiektu kasował dowód zeznany przez plik — przy zielonej bramce.


def _historia_dwoch(con):
    """Stos z rodowodem DOWIEDZIONYM zeznaniem czytelnego pliku (dwa wejścia, temperatury z XML)."""
    m = _master(con)
    a = _light(con, "l1", date_obs="2025-08-30T20:30:00", ccd_temp=-10.0)
    b = _light(con, "l2", date_obs="2025-08-30T20:40:00", ccd_temp=-9.9)
    czytelny = lambda _p: _xml_historii([-10.0, -9.9])       # noqa: E731 — seam jednolinijkowy
    s = run_stack_lineage(con, now=NOW, xml_reader=czytelny)
    assert s.by_assert == {"history": 1}                     # rodowód NAPRAWDĘ dowiedziony
    return m, a, b, czytelny


def test_cofniecie_na_LIGHCIE_nie_kasuje_rodowodu_DOWIEDZIONEGO(con):
    """§4/14c-i: „Cofnij" na lighcie stosu z CZYTELNYM plikiem — dowód zeznany zostaje.

    Łańcuch, który tu pilnujemy (R26#4): light wypada z okna → `inputs_contained` nie przechodzi
    → `REASON_MISMATCH` → `_reconcile` kasuje relacje, z guardem wyłącznie na `user`. Ginęłyby
    więc wiersze `history` — DOWIEDZIONE zeznaniem pliku, którego nikt nie obalił. Ochrona idzie
    RANGĄ (`repo.RANGA_ASSERT`): zapisany `history` bije plan, który po odmowie nie ustala niczego."""
    m, _a, b, czytelny = _historia_dwoch(con)
    przed = {(r["input_frame_id"], r["asserted_by"]) for r in inputs_of(con, m)}

    con.execute("UPDATE frame SET object_source = 'user' WHERE id = ?", (b,))
    con.commit()
    assert repo.clear_object_assignment(con, frame_ids=[b], now=LATER).assigned == 1

    s = run_stack_lineage(con, now=LATER, xml_reader=czytelny)
    assert {(r["input_frame_id"], r["asserted_by"]) for r in inputs_of(con, m)} == przed
    assert (s.unlinked, s.kept_proven, s.kept_unread) == (0, 1, 0)   # POWÓD pominięcia własny
    assert _integracja(con, m)["unresolved_reason"] is None          # zero degradacji głowy


def test_nazwanie_LIGHTA_z_cudzego_stosu_nie_kasuje_rodowodu_DOWIEDZIONEGO(con):
    """§4/14c-i, człon „DOSTAJE" — druga strona tego samego łańcucha, bez własnego testu do dziś.

    Ręka nadaje kanon zaznaczeniu, w którym jest OBCA klatka; wchodzi ona do okna cudzego stosu
    jako NADWYŻKA, więc zeznanie pliku znów przestaje się domykać. Skutek byłby gorszy niż przy
    cofnięciu: `REASON_MISMATCH` na stosie, którego nikt nie dotykał."""
    m, _a, _b, czytelny = _historia_dwoch(con)
    przed = {(r["input_frame_id"], r["asserted_by"]) for r in inputs_of(con, m)}
    obca = _light(con, "obca", date_obs="2025-08-30T21:00:00", ccd_temp=-15.0, object_id=None)

    g = repo.user_assign_object(con, alias_norm=None, canon="CTB1", catalog="catalog",
                                kind="deep_sky", frame_ids=[obca], now=LATER)
    assert g.assigned == 1

    s = run_stack_lineage(con, now=LATER, xml_reader=czytelny)
    assert {(r["input_frame_id"], r["asserted_by"]) for r in inputs_of(con, m)} == przed
    assert (s.unlinked, s.kept_proven) == (0, 1)
    assert _integracja(con, m)["unresolved_reason"] is None


def test_creation_time_oba_ksztalty_wlasnosci_i_brak():
    """AR-10: `XISF:CreationTime` jako `String` (treść elementu - moduły 1.0.13 i 1.1.3) i jako
    `TimePoint` (atrybut `value=`); brak własności, pusta wartość i brak XML → None."""
    from horreum.resolve.stack import creation_time
    assert creation_time('<xisf><Property id="XISF:CreationTime" type="String">'
                         '2022-04-20T11:53:52Z</Property></xisf>') == "2022-04-20T11:53:52Z"
    assert creation_time('<Property id="XISF:CreationTime" type="TimePoint" '
                         'value="2023-09-13T18:16:53Z"/>') == "2023-09-13T18:16:53Z"
    assert creation_time('<Property id="XISF:CreationTime" type="String"></Property>') is None
    assert creation_time('<Property id="XISF:CreatorModule" type="String">x</Property>') is None
    assert creation_time(None) is None


def test_przebieg_zapisuje_creation_time_i_chroni_go_przy_nieczytelnym_pliku(con):
    """AR-10: najbliższy przebieg rodowodu zapisuje `XISF:CreationTime` w `integration` (fakt
    zeznania pliku jak sygnatura), a przebieg bez dostępu do pliku go nie kasuje. Falsyfikator:
    zdejmij `creation_time` z ochrony `history_unread` w `run_stack_lineage` - drugi przebieg
    zapisze NULL."""
    m = _master(con)
    _light(con, "l1", date_obs="2025-08-30T20:30:00")
    z_data = '<xisf><Property id="XISF:CreationTime" type="String">2023-04-22T08:49:00Z</Property></xisf>'

    def _wybuch(_p):
        raise OSError("dysk odłączony")

    run_stack_lineage(con, now=NOW, xml_reader=lambda _p: z_data)
    assert _integracja(con, m)["creation_time"] == "2023-04-22T08:49:00Z"
    run_stack_lineage(con, now=LATER, xml_reader=_wybuch)
    assert _integracja(con, m)["creation_time"] == "2023-04-22T08:49:00Z"
    ile = con.execute("SELECT count(*) FROM event WHERE verb = 'integration.updated'").fetchone()[0]
    run_stack_lineage(con, now=LATER, xml_reader=lambda _p: z_data)
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'integration.updated'"
                       ).fetchone()[0] == ile, "idempotencja: ta sama data, zero eventów"


def test_creation_time_trafia_takze_do_stosu_chronionego_z_powodem(con):
    """AR-10, obietnica 0026 („najbliższe Stosy uzupełnią całe archiwum"): stos z rodowodem
    DOWIEDZIONYM, któremu gest osi dał powód (`kept_proven`), omija `upsert_integration` w całości -
    a plik leży na miejscu i zeznaje `XISF:CreationTime`. Data ma wejść WĄSKO: wiersze, powód
    i reszta głowy nietknięte; plik bez daty i plik nieczytelny daty nie kasują.
    Falsyfikator: zdejmij zapis daty z gałęzi „chroniony + powód" w `run_stack_lineage`."""
    m, _a, b, _cz = _historia_dwoch(con)
    assert _integracja(con, m)["creation_time"] is None          # stos sprzed migracji 0026
    przed = {(r["input_frame_id"], r["asserted_by"]) for r in inputs_of(con, m)}
    con.execute("UPDATE frame SET object_source = 'user' WHERE id = ?", (b,))
    con.commit()
    assert repo.clear_object_assignment(con, frame_ids=[b], now=LATER).assigned == 1
    glowa_przed = dict(_integracja(con, m))
    z_data = _xml_historii([-10.0, -9.9]).replace(
        "</xisf>", '<Property id="XISF:CreationTime" type="String">2023-04-22T08:49:00Z'
                   '</Property></xisf>')

    s = run_stack_lineage(con, now=LATER, xml_reader=lambda _p: z_data)
    assert s.kept_proven == 1, "gałąź chroniona z powodem - ten sam stan co bez daty"
    glowa = dict(_integracja(con, m))
    assert glowa["creation_time"] == "2023-04-22T08:49:00Z"
    assert {k: v for k, v in glowa.items() if k not in ("creation_time", "updated_at")} == {
        k: v for k, v in glowa_przed.items() if k not in ("creation_time", "updated_at")}
    assert {(r["input_frame_id"], r["asserted_by"]) for r in inputs_of(con, m)} == przed
    zdarzenie = con.execute("SELECT payload FROM event WHERE verb = 'integration.updated' "
                            "ORDER BY id DESC LIMIT 1").fetchone()
    assert json.loads(zdarzenie["payload"])["after"] == {"creation_time": "2023-04-22T08:49:00Z"}

    ile = con.execute("SELECT count(*) FROM event").fetchone()[0]
    run_stack_lineage(con, now=LATER, xml_reader=lambda _p: z_data)       # idempotencja
    run_stack_lineage(con, now=LATER, xml_reader=lambda _p: _xml_historii([-10.0, -9.9]))

    def _wybuch(_p):
        raise OSError("dysk odłączony")

    run_stack_lineage(con, now=LATER, xml_reader=_wybuch)
    assert _integracja(con, m)["creation_time"] == "2023-04-22T08:49:00Z", "None nie kasuje daty"
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'integration.updated' "
                       "AND id > ?", (ile,)).fetchone()[0] == 0


def test_klinga_daty_stosu_odmawia_pustej_daty_i_braku_glowy(con):
    """EXPECT: wąska klinga daty nie jest drogą do skasowania faktu ani do założenia głowy."""
    m = _master(con)
    with pytest.raises(ValueError):
        repo.record_integration_creation_time(con, master_frame_id=m, creation_time=None, now=NOW)
    with pytest.raises(ValueError):
        repo.record_integration_creation_time(con, master_frame_id=m, creation_time="2023-04-22T08:49:00Z",
                                              now=NOW)


def test_ochrona_rangi_NIE_zamraza_odtworzenia_tej_samej_sily(con):
    """Człon LUSTRZANY ochrony rangowej — bez niego „chroń zawsze" przeszłoby oba testy wyżej.

    Rodowód `history` wobec planu `history` to TA SAMA siła: przebieg ma prawo go odtworzyć,
    a stos ma dalej śledzić stan. Falsyfikator: light dołożony do okna ZGODNIE z zeznaniem pliku
    (trzy temperatury w XML, trzy klatki) musi dostać relację — implementacja zamrażająca rodowód
    przy samym istnieniu zapisanego `history` zostawiłaby dwa wiersze i zaczerwieniła ten człon."""
    m, _a, _b, _cz = _historia_dwoch(con)
    trzeci = _light(con, "l3", date_obs="2025-08-30T20:50:00", ccd_temp=-9.8)

    s = run_stack_lineage(con, now=LATER, xml_reader=lambda _p: _xml_historii([-10.0, -9.9, -9.8]))
    assert {r["input_frame_id"] for r in inputs_of(con, m)} == {_a, _b, trzeci}
    assert (s.linked_new, s.kept_proven, s.by_assert) == (1, 0, {"history": 1})


def test_czytelny_plik_bez_daty_nie_kasuje_zapisanej(con):
    """AR-50 (4): plik CZYTELNY, ale bez `XISF:CreationTime` (zwykła gałąź zapisu głowy) daty
    zapisanej nie kasuje - ta sama reguła co w gałęzi chronionej z powodem i przy pliku
    nieczytelnym. Zero zdarzeń przy drugim przebiegu.

    Falsyfikator: zdejmij zachowanie `stan["creation_time"]` z gałęzi czytelnej → NULL."""
    m = _master(con)
    _light(con, "l1", date_obs="2025-08-30T20:30:00")
    z_data = ('<xisf><Property id="XISF:CreationTime" type="String">2023-04-22T08:49:00Z'
              '</Property></xisf>')
    run_stack_lineage(con, now=NOW, xml_reader=lambda _p: z_data)
    ile = con.execute("SELECT count(*) FROM event WHERE verb = 'integration.updated'").fetchone()[0]
    run_stack_lineage(con, now=LATER, xml_reader=lambda _p: "<xisf></xisf>")
    assert _integracja(con, m)["creation_time"] == "2023-04-22T08:49:00Z"
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'integration.updated'"
                       ).fetchone()[0] == ile


def test_historia_czytana_z_kopii_ktora_dala_naglowek(con):
    """AR-22 (3): zeznanie stosu to para - karty z `header` i XML historii z pliku. Przy dwóch
    obecnych kopiach historia ma przyjść z TEJ, której fakty (`hdr_*`) równają się nagłówkowi,
    a nie z najstarszej. Falsyfikator: przywróć `ORDER BY l.id LIMIT 1` w `_masters` - czytnik
    dostanie ścieżkę kopii obcej."""
    from horreum.resolve.headers import copy_testimony
    m = _master(con, path=r"R:\STARA\inna.xisf")
    con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                (m, STOS))
    raw = json.loads(con.execute("SELECT raw_json FROM header WHERE frame_id = ?",
                                 (m,)).fetchone()[0])
    zgodne = copy_testimony(raw)
    obce = {**zgodne, "hdr_object": "inny obiekt"}
    for sciezka, fakty in ((r"R:\STARA\inna.xisf", obce), (STOS, zgodne)):
        con.execute("UPDATE location SET header_hash = ?, hdr_hash = ?, hdr_rule = 1, "
                    "hdr_filter = ?, hdr_imagetyp = ?, hdr_object = ?, "
                    "hdr_telescop = ?, hdr_instrume = ?, hdr_exptime = ?, hdr_xbinning = ?, "
                    "hdr_date_obs = ? WHERE path = ?",
                    (f"h{sciezka}", f"h{sciezka}",
                     fakty["hdr_filter"], fakty["hdr_imagetyp"], fakty["hdr_object"],
                     fakty["hdr_telescop"], fakty["hdr_instrume"], fakty["hdr_exptime"],
                     fakty["hdr_xbinning"], fakty["hdr_date_obs"], sciezka))
    con.commit()
    czytane = []
    run_stack_lineage(con, now=NOW, xml_reader=lambda p: czytane.append(p))
    assert czytane == [STOS]


def test_historia_z_kopii_wskazanej_reka_bije_dopasowanie_faktow(con):
    """Z8: ważna kotwica ręki (`header.adopted` z aktorem `user:*` na obecnej kopii tej klatki)
    wskazuje kopię wiodącą wprost - historia idzie z niej, choć fakty żadnej kopii nie pasują."""
    m = _master(con, path=r"R:\STARA\inna.xisf")
    lid = con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                      (m, STOS)).lastrowid
    con.execute("INSERT INTO event(ts, actor, verb, target, payload) VALUES (?, 'user:local', "
                "'header.adopted', ?, ?)", (NOW, f"frame:{m}", json.dumps({"location_id": lid})))
    con.commit()
    czytane = []
    run_stack_lineage(con, now=NOW, xml_reader=lambda p: czytane.append(p))
    assert czytane == [STOS]


def test_historia_bez_kopii_zgodnej_z_naglowkiem_z_najstarszej_obecnej(con):
    """Żadna kopia nie zeznaje tego, co `header` (fakty nie zebrane) - zostaje dotychczasowa
    reguła: najstarsza obecna. Brak dowodu nie przestawia czytnika na losową kopię."""
    m = _master(con, path=r"R:\STARA\inna.xisf")
    con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                (m, STOS))
    con.commit()
    czytane = []
    run_stack_lineage(con, now=NOW, xml_reader=lambda p: czytane.append(p))
    assert czytane == [r"R:\STARA\inna.xisf"]
