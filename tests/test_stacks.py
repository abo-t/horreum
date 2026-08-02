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
STOS = r"R:\!!ASTROFOTO\A140R\CTB1\WBPP\master\masterLight_EXPOSURE-600.00s_FILTER-H.xisf"

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
