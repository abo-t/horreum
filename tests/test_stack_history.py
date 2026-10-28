"""HISTORIA STOSU W BAZIE, ALIASY NAZW LIGHTÓW, PODSTAWA RODOWODU (migracja 0034).

Pinujemy to, na czym stoi zmiana zachowania rodowodu stosów, a nie samą szczęśliwą ścieżkę:
  * kolejność źródeł wejść w `stacks._plan` - nazwa → temperatura → „N z M” → `history_mismatch`,
    z odmową (nie wyborem) przy nazwie dwóch klatek;
  * historia z bazy zamiast pliku: druga Dostawa czyta ZERO nagłówków stosów (falsyfikator),
    a rozjazd kotwicy wraca do pliku i odświeża wiersz;
  * komplet pisarzy: skan (`_ingest_in_tx`), uzupełnienie (`backfill_stack_history`), odświeżenie
    w rodowodzie, alias przy zmianie nazwy (`_apply_relocation`) i import Custos (skrypt).
"""
import dataclasses
import hashlib
import html
import importlib.util
import json
import os
import sqlite3
import struct
import zipfile

import pytest

from horreum import db, repo, scan, stacks
from horreum.resolve import stack as rstack

NOW = "2026-10-11T12:00:00+00:00"
LATER = "2026-10-11T13:00:00+00:00"
STOS = r"R:\ASTRO_\STACKS\CTB1\masterLight_EXPOSURE-600.00s_FILTER-H.xisf"
LIGHTS = "R:\\ASTRO_\\LIGHTS\\CTB1\\A140R_2600MM\\Ha\\"
# Nazwa lightu Z CHWILI OBRÓBKI (konwencja WBPP, z temperaturą) i wejście historii z dopiskami.
_OBROBKA = "CTB 1_LIGHT_GRP-MM_FILTER-H_600.00s_{idx}_2.98_0.56_{temp}C"
_WEJSCIE = "D:/robocze/CTB1/registered/" + _OBROBKA + "_c_r.xisf"


@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "h.db"))
    c.execute("INSERT INTO camera(model_canon, created_at) VALUES ('ASI2600MM', ?)", (NOW,))
    c.execute("INSERT INTO telescope(telescop_canon, status, created_at) VALUES ('A140R', 'proposed', ?)",
              (NOW,))
    c.execute("INSERT INTO config(telescope_id, camera_id, status, created_at) VALUES (1, 1, 'proposed', ?)",
              (NOW,))
    c.execute("INSERT INTO object(canon, catalog, kind) VALUES ('CTB1', 'catalog', 'deep_sky')")
    c.commit()
    yield c
    c.close()


def _historia_property(wejscia, *, rows=None):
    """Własność `PixInsight:ProcessingHistory` (treść zaescape'owana jak w pliku): `wejscia` =
    lista `(ścieżka, enabled)`."""
    tr = "".join(
        f'<tr><td id="enabled" value="{"true" if en else "false"}"/><td id="path">{p}</td></tr>'
        for p, en in wejscia)
    tabela = f'<table id="images" rows="{len(wejscia) if rows is None else rows}">{tr}</table>'
    return ('<Property id="PCL:Signature:Integration" type="String">process=ImageIntegration,'
            'version=1.7.1,timestamp=2025-08-31T02:00:00.000Z</Property>'
            '<Property id="XISF:CreationTime" type="String">2025-08-31T02:02:00Z</Property>'
            f'<Property id="PixInsight:ProcessingHistory" type="String">{html.escape(tabela, quote=False)}'
            '</Property>')


def _xml(temperatury, *, idx0=0, wylaczone=()):
    """XML nagłówka stosu (jak `xml_reader`) z wejściami WBPP o podanych temperaturach."""
    wejscia = [(_WEJSCIE.format(idx=f"{idx0 + i:04d}", temp=f"{t:.2f}"), i not in wylaczone)
               for i, t in enumerate(temperatury)]
    return "<xisf>" + _historia_property(wejscia) + "</xisf>"


def _light(con, sha1, *, date_obs, ccd_temp=-10.0, idx=None, temp=-10.0, obj=1, path=None):
    """Light w oknie (Ha, 600 s, A140R) z lokacją pod nazwą archiwum; `idx` → nazwa z czasu obróbki
    jako ALIAS (nazwa bieżąca archiwum jest inna, jak po przenosinach Custos)."""
    cur = con.execute(
        "INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, filter_canon, "
        "first_seen_at) VALUES (?, 'light', 'fits', 1, 1, ?, 'Ha', ?)", (sha1, obj, NOW))
    fid = cur.lastrowid
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, exptime, ccd_temp) "
                "VALUES (?, '{}', ?, 600.0, ?)", (fid, date_obs, ccd_temp))
    con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                (fid, path or f"{LIGHTS}CTB1_{sha1}_LIGHT_Ha_600s_.fits"))
    con.commit()
    if idx is not None:
        stem = rstack.raw_stem(_OBROBKA.format(idx=f"{idx:04d}", temp=f"{temp:.2f}") + ".fits")
        repo.record_light_name_aliases(con, aliases=[(fid, stem)], source="custos", now=NOW,
                                       actor="test")
    return fid


def _master(con, *, start="2025-08-30T20:00:00", end="2025-08-30T23:00:00", header_hash=None,
            sha="m1", path=STOS):
    raw = {"IMAGETYP": "Master Light", "OBJECT": "CTB 1", "FILTER": "H", "EXPTIME": 600.0,
           "TELESCOP": "A140R", "DATE-OBS": start, "DATE-END": end}
    cur = con.execute(
        "INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, filter_canon, "
        "first_seen_at) VALUES (?, 'master_light', 'xisf', 1, 1, 1, 'Ha', ?)", (sha, NOW))
    fid = cur.lastrowid
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, exptime) VALUES (?, ?, ?, 600.0)",
                (fid, json.dumps(raw), start))
    con.execute("INSERT INTO location(frame_id, volume, path, present, header_hash) VALUES (?, 'V', ?, 1, ?)",
                (fid, path, header_hash))
    con.commit()
    return fid


def _okno(con, n=10, *, z_aliasem=True):
    """`n` lightów w oknie mastera; i-ty ma alias nazwy z obróbki o indeksie i (temperatura -10)."""
    return [_light(con, f"l{i}", date_obs=f"2025-08-30T{20 + i // 6}:{(i % 6) * 10:02d}:00",
                   idx=i if z_aliasem else None) for i in range(n)]


def _glowa(con, m):
    return con.execute("SELECT * FROM integration WHERE master_frame_id = ?", (m,)).fetchone()


def _wiersze(con, m):
    return sorted((r["input_frame_id"], r["asserted_by"]) for r in stacks.inputs_of(con, m))


def _sha(xml):
    return hashlib.sha1(xml.encode("utf-8")).hexdigest()


# ============================================================ migracja 0034


def test_0034_check_domen_podstawy_aliasu_i_historii(con):
    m = _master(con)
    for t in stacks.LINEAGE_BASES:
        repo.upsert_integration(con, master_frame_id=m, integ_hash=None, tool=None, window_start=None,
                                window_end=None, declared_rows=None, drizzle_inputs=None,
                                disabled_inputs=None, degenerate=0, ambiguous=0, telescope_mismatch=0,
                                unresolved_reason=None, lineage_basis=t, now=NOW)
    for zle in ("UPDATE integration SET lineage_basis = 'nazwa'",
                "UPDATE integration SET lineage_basis = 'temp', outside_window = 1",
                "UPDATE integration SET outside_window = 2",
                "UPDATE integration SET used_rows = -1"):
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(zle)
    light = _light(con, "a", date_obs="2025-08-30T20:00:00")
    con.execute("INSERT INTO light_name_alias(frame_id, stem, source) VALUES (?, 'x', 'custos')", (light,))
    for zle in ("INSERT INTO light_name_alias(frame_id, stem, source) VALUES (?, 'x', 'custos')",
                "INSERT INTO light_name_alias(frame_id, stem, source) VALUES (?, 'y', 'reka')",
                "INSERT INTO light_name_alias(frame_id, stem, source) VALUES (?, '', 'custos')"):
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(zle, (light,))
    con.execute("INSERT INTO stack_history(location_id, hdr_hash) VALUES (1, 'h')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO stack_history_input(location_id, seq, path, enabled, has_drizzle) "
                    "VALUES (1, 0, 'p', 2, 0)")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO stack_history(location_id, hdr_hash) VALUES (2, '')")


# ============================================================ klingi repo


def test_historia_stosu_cas_idempotencja_i_przepisanie(con):
    m = _master(con, header_hash="h1")
    loc = con.execute("SELECT id FROM location WHERE frame_id = ?", (m,)).fetchone()[0]
    hist = rstack.read_history(_xml([-10.0, -9.9], wylaczone=(1,)))
    assert repo.record_stack_history(con, location_id=loc, hdr_hash="inny", history=hist, now=NOW) is False
    assert con.execute("SELECT count(*) FROM stack_history").fetchone()[0] == 0
    assert repo.record_stack_history(con, location_id=loc, hdr_hash="h1", history=hist, now=NOW) is True
    assert repo.record_stack_history(con, location_id=loc, hdr_hash="h1", history=hist, now=LATER) is False
    ev = con.execute("SELECT payload FROM event WHERE verb = 'stack_history.recorded'").fetchall()
    assert len(ev) == 1 and json.loads(ev[0][0])["enabled"] == 1
    zapis = stacks._stored_histories(con)[loc]
    assert zapis[0] == "h1" and zapis[1] == hist and zapis[1].created == "2025-08-31T02:02:00Z"
    assert [i.set_temp_c for i in zapis[1][1]] == [-10.0, -9.9] and zapis[1][1][1].enabled is False
    con.execute("UPDATE location SET header_hash = 'h2' WHERE id = ?", (loc,))
    con.commit()
    nowa = rstack.read_history(_xml([-8.0]))
    assert repo.record_stack_history(con, location_id=loc, hdr_hash="h2", history=nowa, now=LATER) is True
    assert con.execute("SELECT count(*) FROM stack_history_input").fetchone()[0] == 1
    assert stacks._stored_histories(con)[loc][0] == "h2"


def test_aliasy_wsadem_expect_i_idempotencja(con):
    m = _master(con)
    a = _light(con, "a", date_obs="2025-08-30T20:00:00")
    with pytest.raises(ValueError, match="spoza lightów"):
        repo.record_light_name_aliases(con, aliases=[(a, "x"), (m, "y")], source="custos", now=NOW,
                                       actor="t")
    with pytest.raises(ValueError, match="nieznormalizowany"):
        repo.record_light_name_aliases(con, aliases=[(a, "Duze")], source="custos", now=NOW, actor="t")
    with pytest.raises(ValueError, match="źródło"):
        repo.record_light_name_aliases(con, aliases=[(a, "x")], source="reka", now=NOW, actor="t")
    assert con.execute("SELECT count(*) FROM light_name_alias").fetchone()[0] == 0
    kropki = "ctb 1_light_600.00s_0000_2.98_0.56_-10.00c"
    assert repo.record_light_name_aliases(con, aliases=[(a, kropki), (a, "x")], source="custos",
                                          now=NOW, actor="t") == 2
    assert repo.record_light_name_aliases(con, aliases=[(a, kropki)], source="custos", now=LATER,
                                          actor="t") == 0
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'light_name_alias.imported'").fetchone()[0] == 1


def test_zmiana_nazwy_lightu_zostawia_alias_dawnej_nazwy(con):
    """Pisarz aliasu = `_apply_relocation` (droga `guard_file_rename` i `relocate_location`): dawna
    nazwa przed `UPDATE`, insert idempotentny, event tylko przy nowym. Sam katalog i nie-light - nic."""
    a = _light(con, "a", date_obs="2025-08-30T20:00:00", path=LIGHTS + "Stara_Nazwa_0001.fits")
    loc = con.execute("SELECT id FROM location WHERE frame_id = ?", (a,)).fetchone()[0]
    repo.relocate_location(con, location_id=loc, new_path=LIGHTS + "nowa_0001.fits", now=NOW)
    repo.relocate_location(con, location_id=loc, new_path="R:\\inny\\nowa_0001.fits", now=NOW)
    repo.relocate_location(con, location_id=loc, new_path=LIGHTS + "Stara_Nazwa_0001.fits", now=NOW)
    repo.relocate_location(con, location_id=loc, new_path=LIGHTS + "nowa_0001.fits", now=LATER)
    assert sorted(tuple(r) for r in con.execute("SELECT frame_id, stem, source FROM light_name_alias")) \
        == [(a, "nowa_0001", "horreum"), (a, "stara_nazwa_0001", "horreum")]
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'light_name_alias.added'").fetchone()[0] == 2
    m = _master(con)
    mloc = con.execute("SELECT id FROM location WHERE frame_id = ?", (m,)).fetchone()[0]
    repo.relocate_location(con, location_id=mloc, new_path=STOS + ".old.xisf", now=NOW)
    assert con.execute("SELECT count(*) FROM light_name_alias WHERE frame_id = ?", (m,)).fetchone()[0] == 0


# ============================================================ kolejność źródeł w `_plan`


def test_nazwy_wybieraja_podzbior_okna_zamiast_okna(con):
    """Okno ma 10 klatek, plik zeznaje 8 nazw → ranga `history` dla DOKŁADNIE tych 8 (podstawa `name`),
    dwie pozostałe nie wchodzą - dawniej `history_mismatch` i zero wierszy."""
    m = _master(con)
    lighty = _okno(con)
    s = stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml([-10.0] * 8))
    assert _wiersze(con, m) == sorted((f, "history") for f in lighty[:8])
    g = _glowa(con, m)
    assert (g["unresolved_reason"], g["lineage_basis"], g["outside_window"], g["used_rows"]) == \
        (None, "name", 0, None)
    assert s.by_basis == {"name": 1} and s.reasons == {}


def test_nazwy_poza_oknem_i_przy_pustym_oknie_z_flaga(con):
    m = _master(con)
    lighty = _okno(con, 4)
    poza = _light(con, "poza", date_obs="2025-08-31T01:00:00", idx=4)
    stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml([-10.0] * 5))
    assert _wiersze(con, m) == sorted((f, "history") for f in lighty + [poza])
    assert (_glowa(con, m)["lineage_basis"], _glowa(con, m)["outside_window"]) == ("name", 1)
    # Okno puste (inny obiekt lightów) - `no_candidates` przestaje być powodem, gdy nazwy niosą zbiór.
    con.execute("UPDATE frame SET object_id = NULL WHERE kind = 'light'")
    con.commit()
    s = stacks.run_stack_lineage(con, now=LATER, xml_reader=lambda _p: _xml([-10.0] * 5))
    assert s.reasons == {} and _glowa(con, m)["outside_window"] == 1
    assert _wiersze(con, m) == sorted((f, "history") for f in lighty + [poza])


def test_nazwa_dwoch_klatek_to_odmowa_a_nie_wybor(con):
    """Rdzeń nazwy przy dwóch klatkach (`light_name_alias` dopuszcza) → zbiór z nazw odrzucony,
    plan schodzi do temperatur: okno 8 = 8 wejść → `temp`, licznik `names_ambiguous`."""
    m = _master(con)
    lighty = _okno(con, 8)
    stem0 = rstack.raw_stem(_OBROBKA.format(idx="0000", temp="-10.00") + ".fits")
    obcy = _light(con, "obcy", date_obs="2025-08-29T20:00:00")
    repo.record_light_name_aliases(con, aliases=[(obcy, stem0)], source="custos", now=NOW, actor="t")
    s = stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml([-10.0] * 8))
    assert s.names_ambiguous == 1 and _glowa(con, m)["lineage_basis"] == "temp"
    assert _wiersze(con, m) == sorted((f, "history") for f in lighty)


def test_brak_nazw_podzbior_temperatur_to_werdykt_n_z_m(con):
    """Bez nazw: 8 wejść o temperaturach z okna 10 klatek → wiersze okna (`window`, M=10), N=8, bez
    powodu; rozjazd temperatury dalej daje `history_mismatch`."""
    m = _master(con)
    lighty = _okno(con, z_aliasem=False)
    s = stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml([-10.0] * 8))
    assert _wiersze(con, m) == sorted((f, "window") for f in lighty)
    g = _glowa(con, m)
    assert (g["unresolved_reason"], g["lineage_basis"], g["used_rows"]) == (None, None, 8)
    assert s.by_basis == {"subset": 1}
    stacks.run_stack_lineage(con, now=LATER, xml_reader=lambda _p: _xml([-10.0] * 7 + [-25.0]))
    g = _glowa(con, m)
    assert (g["unresolved_reason"], g["used_rows"]) == (stacks.REASON_MISMATCH, None)
    assert _wiersze(con, m) == []


def test_temperatury_i_licznik_jako_podstawa(con):
    m = _master(con)
    _okno(con, 8, z_aliasem=False)
    stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml([-10.0] * 8))
    assert _glowa(con, m)["lineage_basis"] == "temp"
    bez_temp = "<xisf>" + _historia_property(
        [(f"D:/w/LBN_{i:04d}_c_r.xisf", True) for i in range(8)]) + "</xisf>"
    stacks.run_stack_lineage(con, now=LATER, xml_reader=lambda _p: bez_temp)
    assert _glowa(con, m)["lineage_basis"] == "count"


# ============================================================ historia z bazy


def test_druga_dostawa_nie_czyta_naglowkow_stosow(con):
    """Falsyfikator historii w bazie: odczyt pliku, którego odcisk równa się odciskowi kopii, zostawia historię
    w bazie; następny przebieg nie dotyka pliku (czytnik rzuca) i daje ten sam rodowód."""
    xml = _xml([-10.0] * 8)
    m = _master(con, header_hash=_sha(xml))
    _okno(con)
    s1 = stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: xml)
    assert (s1.history_reads, s1.history_refreshed) == (1, 1)
    przed = _wiersze(con, m)

    def nie_czytaj(_p):
        raise AssertionError("odczyt nagłówka stosu z udziału")
    s2 = stacks.run_stack_lineage(con, now=LATER, xml_reader=nie_czytaj)
    assert (s2.history_reads, s2.history_unread, s2.linked_new) == (0, 0, 0)
    assert _wiersze(con, m) == przed and _glowa(con, m)["creation_time"] == "2025-08-31T02:02:00Z"


def test_rozjazd_kotwicy_wraca_do_pliku_i_odswieza_wiersz(con):
    xml = _xml([-10.0] * 8)
    m = _master(con, header_hash=_sha(xml))
    _okno(con)
    stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: xml)
    nowy = _xml([-10.0] * 9)
    con.execute("UPDATE location SET header_hash = ? WHERE frame_id = ?", (_sha(nowy), m))
    con.commit()
    s = stacks.run_stack_lineage(con, now=LATER, xml_reader=lambda _p: nowy)
    assert (s.history_reads, s.history_refreshed) == (1, 1) and len(_wiersze(con, m)) == 9


def test_tekst_spoza_kopii_planuje_z_pliku_bez_zapisu_historii(con):
    """Tekst, którego odcisk NIE jest odciskiem kopii (plik zmieniony od skanu, czytnik testowy) -
    plan z pliku jak dotąd, ale bez zapisu historii: następny przebieg czyta znowu."""
    m = _master(con, header_hash="odcisk-skanu")
    _okno(con)
    for _ in range(2):
        s = stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml([-10.0] * 8))
        assert (s.history_reads, s.history_refreshed) == (1, 0)
    assert len(_wiersze(con, m)) == 8 and stacks._stored_histories(con) == {}


# ============================================================ pisarze: skan i uzupełnienie


def _xisf_stosu(path, wejscia, *, obj="CTB 1", payload=b"\x01\x02" * 16, imagetyp="Master Light"):
    """Monolityczny XISF stosu z kartami okna i historią (offset attachmentu do punktu stałego)."""
    karty = [("IMAGETYP", imagetyp), ("OBJECT", obj), ("FILTER", "H"), ("EXPTIME", "600.00"),
             ("DATE-OBS", "2025-08-30T20:00:00"), ("DATE-END", "2025-08-30T23:00:00")]

    def xml_for(start):
        k = "".join(f'<FITSKeyword name="{n}" value="\'{v}\'" comment=""/>' for n, v in karty)
        return ('<?xml version="1.0" encoding="UTF-8"?><xisf version="1.0" '
                'xmlns="http://www.pixinsight.com/xisf"><Image geometry="4:4:1" sampleFormat="UInt16" '
                f'location="attachment:{start}:{len(payload)}">{k}</Image>'
                + _historia_property(wejscia) + '</xisf>').encode("utf-8")
    start = 0
    for _ in range(4):
        nowy = 16 + len(xml_for(start))
        if nowy == start:
            break
        start = nowy
    xml = xml_for(start)
    with open(path, "wb") as fh:
        fh.write(b"XISF0100" + struct.pack("<I", len(xml)) + b"\x00" * 4 + xml + payload)
    return str(path)


def test_skan_pisze_historie_stosu_z_tego_samego_odczytu(con, tmp_path):
    p = _xisf_stosu(tmp_path / "stos.xisf", [(f"D:/w/a_{i}_c_r.xisf", True) for i in range(3)])
    s = scan.ScanSummary()
    scan.ingest_record(con, scan.scan_file(p), volume="V", now=NOW, summary=s, pochodzenie=repo.ZEWNETRZNE)
    loc = con.execute("SELECT id, header_hash FROM location").fetchone()
    zapis = stacks._stored_histories(con)[loc["id"]]
    assert zapis[0] == loc["header_hash"] and zapis[1][0] == 3 and len(zapis[1][1]) == 3
    assert scan.stack_history_candidates(con) == []
    scan.ingest_record(con, scan.scan_file(p), volume="V", now=LATER, summary=s, pochodzenie=repo.ZEWNETRZNE)
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'stack_history.recorded'").fetchone()[0] == 1
    # Nagłówek zmieniony w miejscu → nowy odczyt skanu przepisuje historię pod nowym odciskiem.
    _xisf_stosu(p, [(f"D:/w/a_{i}_c_r.xisf", True) for i in range(2)], obj="CTB 2")
    scan.ingest_record(con, scan.scan_file(p), volume="V", now=LATER, summary=s, pochodzenie=repo.ZEWNETRZNE)
    loc = con.execute("SELECT id, header_hash FROM location").fetchone()
    zapis = stacks._stored_histories(con)[loc["id"]]
    assert zapis[0] == loc["header_hash"] and zapis[1][0] == 2


def test_uzupelnienie_dociaga_stosy_bez_historii_i_milknie(con, tmp_path):
    """Rekord bez historii (import dawcy syntetyzuje `ScanRecord` z cache) → kandydat uzupełnienia;
    jeden odczyt nagłówka, drugi przebieg bez kandydatów. Plik zmieniony od skanu → `stale`."""
    p = _xisf_stosu(tmp_path / "stos.xisf", [(f"D:/w/a_{i}_c_r.xisf", True) for i in range(3)])
    rec = dataclasses.replace(scan.scan_file(p), history=None)
    scan.ingest_record(con, rec, volume="V", now=NOW, summary=scan.ScanSummary(), pochodzenie=repo.ZEWNETRZNE)
    assert len(scan.stack_history_candidates(con)) == 1
    h = scan.backfill_stack_history(con, now=NOW)
    assert (h.rows, h.headers_read, h.written, h.stale, h.remaining) == (1, 1, 1, 0, 0)
    assert scan.backfill_stack_history(con, now=LATER).rows == 0
    con.execute("UPDATE location SET header_hash = 'stary', hdr_hash = 'stary' WHERE id = 1")
    con.commit()
    h = scan.backfill_stack_history(con, now=LATER)
    assert (h.rows, h.written, h.stale, h.remaining) == (1, 0, 1, 1)


# ============================================================ panel


def test_zdanie_podstawy_w_panelu():
    pytest.importorskip("PySide6")
    from horreum.gui import i18n
    from horreum.gui.grid_lineage import _lineage_basis_text
    i18n.set_lang("pl")
    glowa = {"lineage_basis": "name", "outside_window": 1, "used_rows": None, "window_rows": 0}
    assert _lineage_basis_text(glowa) == "wejścia z nazw plików · część klatek leży poza oknem nagłówka"
    glowa = {"lineage_basis": None, "outside_window": 0, "used_rows": 31, "window_rows": 34}
    assert _lineage_basis_text(glowa) == "plik użył 31 z 34 klatek okna"
    glowa = {"lineage_basis": "temp", "outside_window": 0, "used_rows": None, "window_rows": 0}
    assert _lineage_basis_text(glowa) == "wejścia potwierdzone temperaturami z nazw"
    assert _lineage_basis_text({"lineage_basis": None, "outside_window": 0, "used_rows": None,
                                "window_rows": 0}) == ""


def test_m_w_n_z_m_to_kandydaci_okna_a_nie_wejscia_dopiete_reka(con):
    """M = wiersze `window` + odrzucone werdyktem (`queries.stack_lineage_head.window_rows`): wejście
    dopięte ręką spoza okna nie zawyża M."""
    from horreum.gui import queries
    m = _master(con)
    _okno(con, z_aliasem=False)
    stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml([-10.0] * 8))
    reka = _light(con, "reka", date_obs="2025-08-29T20:00:00")
    iid = _glowa(con, m)["id"]
    repo.link_integration(con, integration_id=iid, input_frame_id=reka, asserted_by="user", now=LATER)
    glowa = queries.stack_lineage_head(con, m)
    assert (glowa["used_rows"], glowa["window_rows"], glowa["inputs"]) == (8, 10, 11)


# ============================================================ import aliasów Custos (skrypt)


def _skrypt():
    sciezka = os.path.join(os.path.dirname(__file__), "..", "scripts", "import_aliasow_custos.py")
    spec = importlib.util.spec_from_file_location("import_aliasow_custos", sciezka)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _zip_manifestu(tmp_path, ruchy):
    m = tmp_path / "manifest.sqlite"
    c = sqlite3.connect(m)
    c.execute("CREATE TABLE moves(id INTEGER PRIMARY KEY, old_path, new_path, state, sha_pre, sha_post)")
    c.executemany("INSERT INTO moves(old_path, new_path, state, sha_pre, sha_post) VALUES (?, ?, ?, ?, ?)",
                  ruchy)
    c.commit()
    c.close()
    z = tmp_path / "Custos.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(m, "Custos-Messium/manifest.sqlite")
    return str(z)


def test_import_aliasow_lancuch_odcisk_i_idempotencja(con, tmp_path):
    """Łańcuch A → B → C (bieżąca C) daje aliasy A i B; krawędź `planned` wchodzi wyłącznie z drugim
    świadkiem (odcisk kopii), `collision` bez świadka - nie; ruch z odciskiem kopii daje alias spod
    innej litery dysku; alias zderzony z BIEŻĄCĄ nazwą innej klatki liczy się jako niejednoznaczny;
    DRY nie pisze; drugi `--apply` dopisuje zero."""
    a = _light(con, "a", date_obs="2025-08-30T20:00:00", path=LIGHTS + "C_0001.fits")
    _light(con, "b", date_obs="2025-08-30T21:00:00", path=LIGHTS + "D_0001.fits")
    con.execute("UPDATE location SET file_sha1 = 'f1' WHERE frame_id = ?", (a,))
    con.commit()
    z = _zip_manifestu(tmp_path, [
        ("F:\\stare\\A_0001.fits", "R:\\ASTRO_\\tmp\\B_0001.fits", "done", None, None),
        ("R:\\ASTRO_\\tmp\\B_0001.fits", LIGHTS + "C_0001.fits", "planned", "f1", None),
        ("X:\\zly_0001.fits", LIGHTS + "C_0001.fits", "collision", None, None),
        ("E:\\kopia\\D_0001.fits", "E:\\kopia\\D2_0001.fits", "done", "f1", None),
        ("X:\\obcy_0001.fits", "X:\\obcy_0002.fits", "done", None, None)])
    mod = _skrypt()
    plan = mod.plan_aliases(con, mod.read_moves(z))
    assert sorted(plan.pary) == [(a, "a_0001"), (a, "b_0001"), (a, "d_0001")]
    assert plan.niejednoznaczne == 1                    # `d_0001` = bieżąca nazwa lightu `b`
    baza = str(tmp_path / "h.db")
    assert mod.main(["--db", baza, "--zip", z]) == 0
    assert con.execute("SELECT count(*) FROM light_name_alias").fetchone()[0] == 0
    assert mod.main(["--db", baza, "--zip", z, "--apply"]) == 0
    assert mod.main(["--db", baza, "--zip", z, "--apply"]) == 0
    assert sorted(tuple(r) for r in con.execute("SELECT frame_id, stem, source FROM light_name_alias")) \
        == [(a, "a_0001", "custos"), (a, "b_0001", "custos"), (a, "d_0001", "custos")]
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'light_name_alias.imported'").fetchone()[0] == 1


def test_import_aliasow_idzie_za_przeniesieniem_horreum(con, tmp_path):
    """AR-139: plik przeniesiony przez Horreum PO Custosie leży pod ścieżką, której zapis przenosin nie
    zna - łańcuch startuje też od dawnej ścieżki z `location.renamed`, więc dawna nazwa z Custosa
    wraca; sama nazwa sprzed przeniesienia Horreum NIE staje się aliasem `custos`."""
    a = _light(con, "a", date_obs="2025-08-30T20:00:00", path=LIGHTS + "C_0001.fits")
    lid = con.execute("SELECT id FROM location WHERE frame_id = ?", (a,)).fetchone()[0]
    with con:
        repo._apply_relocation(con, location_id=lid, old_path=LIGHTS + "C_0001.fits",
                               new_path="R:\\ASTRO_\\LIGHTS\\IC405\\A140R_2600MM\\Ha\\E_0001.fits",
                               now=NOW, actor="test")
    z = _zip_manifestu(tmp_path, [("F:\\stare\\A_0001.fits", LIGHTS + "C_0001.fits", "done", None, None)])
    mod = _skrypt()
    plan = mod.plan_aliases(con, mod.read_moves(z))
    assert plan.pary == [(a, "a_0001")]
    assert plan.z_aliasem == 1


# ============================================================ tura naprawcza: szwy i granice


def test_zniwa_nie_kasuja_podstawy_rodowodu(con):
    """Rodowód z żniw podstawy nie liczy, więc jej nie kasuje: `basis='name'` i flaga poza oknem
    przeżywają `record_harvest_inputs` tego samego mastera (wartość wstrzymująca klingi)."""
    m = _master(con)
    lighty = _okno(con, 4)
    poza = _light(con, "poza", date_obs="2025-08-31T01:00:00", idx=4)
    stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml([-10.0] * 5))
    stacks.record_harvest_inputs(con, master_sha1_data="m1", input_frame_ids=lighty + [poza], now=LATER)
    g = _glowa(con, m)
    assert (g["lineage_basis"], g["outside_window"], g["used_rows"]) == ("name", 1, None)
    assert {a for _f, a in _wiersze(con, m)} == {"harvest"}


def test_nazwa_akwizycyjna_z_tokenem_wbpp_na_koncu_nie_psuje_trafienia(con):
    """Bieżąca nazwa archiwum `…_C` (filtr Clear) NIE wchodzi do luźnego rdzenia: wejście `m31_0001_c_r`
    trafia dokładnie light `m31_0001` (`match_stem`), a nie jeszcze `m31_0001_C` przez ścięcie `_c`."""
    m = _master(con)
    cel = _light(con, "cel", date_obs="2025-08-30T20:00:00", path=LIGHTS + "M31_0001.fits")
    _light(con, "clear", date_obs="2025-08-30T20:10:00", path=LIGHTS + "M31_0001_C.fits")
    xml = "<xisf>" + _historia_property([("D:/w/M31_0001_c_r.xisf", True)]) + "</xisf>"
    s = stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: xml)
    assert s.names_ambiguous == 0 and _wiersze(con, m) == [(cel, "history")]
    assert _glowa(con, m)["lineage_basis"] == "name"


def test_przepiecie_kopii_stosu_na_inny_rodzaj_zdejmuje_historie(con, tmp_path):
    p = _xisf_stosu(tmp_path / "stos.xisf", [(f"D:/w/a_{i}_c_r.xisf", True) for i in range(3)])
    s = scan.ScanSummary()
    scan.ingest_record(con, scan.scan_file(p), volume="V", now=NOW, summary=s, pochodzenie=repo.ZEWNETRZNE)
    assert con.execute("SELECT count(*) FROM stack_history").fetchone()[0] == 1
    _xisf_stosu(p, [(f"D:/w/a_{i}_c_r.xisf", True) for i in range(3)], imagetyp="Light",
                payload=b"\x09" * 32)
    scan.ingest_record(con, scan.scan_file(p), volume="V", now=LATER, summary=s, pochodzenie=repo.ZEWNETRZNE)
    assert s.locations_rebound == 1
    assert con.execute("SELECT count(*) FROM stack_history").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM stack_history_input").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'stack_history.cleared'").fetchone()[0] == 1


def test_cofniecie_zmiany_nazwy_nie_aliasuje_nazwy_tranzytowej(con):
    """Rename A → B dopisuje alias A; undo B → A (kierunek `undo`) nie dopisuje B - nazwy, której żaden
    program obróbki nie widział."""
    a = _light(con, "a", date_obs="2025-08-30T20:00:00", path=LIGHTS + "Akwizycja_0001.fits")
    loc = con.execute("SELECT id FROM location WHERE frame_id = ?", (a,)).fetchone()[0]
    for cel, kierunek in ((LIGHTS + "Tranzyt_0001.fits", "commit"),
                          (LIGHTS + "Akwizycja_0001.fits", "undo")):
        with repo.guard_file_rename(con, location_id=loc, new_path=cel,
                                    generation=repo.inplace_generation(con), now=NOW, kierunek=kierunek):
            pass
    assert [tuple(r) for r in con.execute("SELECT stem, source FROM light_name_alias")] == \
        [("akwizycja_0001", "horreum")]


def test_0034_pusta_sygnatura_i_data_to_brak_faktu(con):
    m = _master(con, header_hash="h1")
    loc = con.execute("SELECT id FROM location WHERE frame_id = ?", (m,)).fetchone()[0]
    for kol in ("tool", "creation_time"):
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(f"INSERT INTO stack_history(location_id, hdr_hash, {kol}) VALUES (?, 'h', '')", (loc,))
    con.rollback()
    hist = rstack.History(1, (), "", created="")
    assert repo.record_stack_history(con, location_id=loc, hdr_hash="h1", history=hist, now=NOW) is True
    assert tuple(con.execute("SELECT tool, creation_time FROM stack_history").fetchone()) == (None, None)


def test_zniwa_i_rodowod_jedna_regula_tozsamosci_wejscia():
    """Wejście bez `_c` (`x_r`, lighty nieskalibrowane) - ten sam werdykt w żniwach i w rodowodzie."""
    from horreum import harvest
    zniwa = harvest._names_index({"zestawy": {"A": {"names": {"M31_0001.fits": 7, "M31_0002.fits": 8}}}})
    rodowod = rstack.NameIndex.build(dawne=[(7, "m31_0001"), (8, "m31_0002")])
    for wejscie, klatka in (("D:/w/M31_0001_r.xisf", 7), ("D:/w/M31_0002_c_r.xisf", 8)):
        assert zniwa.hits(wejscie) == {("A", klatka)} and rodowod.hits(wejscie) == {klatka}


def test_poza_oknem_to_czas_a_nie_dobor_okna(con):
    """Klatka z nazw w CZASIE okna, ale z innym filtrem (`_in_window` jej nie wybrał) - nie jest „poza
    oknem nagłówka”; rozjazd teleskopu okna zostaje przy planie z nazw."""
    m = _master(con)
    lighty = _okno(con, 3)
    inny_filtr = _light(con, "oiii", date_obs="2025-08-30T21:30:00", idx=3)
    con.execute("UPDATE frame SET filter_canon = 'OIII' WHERE id = ?", (inny_filtr,))
    con.commit()
    stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml([-10.0] * 4))
    g = _glowa(con, m)
    assert (g["lineage_basis"], g["outside_window"]) == ("name", 0)
    assert _wiersze(con, m) == sorted((f, "history") for f in lighty + [inny_filtr])


def test_odcisk_odswiezenia_z_surowych_bajtow(con):
    """Nagłówek z bajtem spoza UTF-8: odcisk liczony z bajtów, jak `header_hash` - wiersz historii
    powstaje, a następny przebieg nie czyta pliku."""
    surowe = _xml([-10.0] * 8).encode("utf-8").replace(b"<xisf>", b"<xisf><!-- \xff -->")
    m = _master(con, header_hash=hashlib.sha1(surowe).hexdigest())
    _okno(con)
    s = stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: surowe)
    assert (s.history_reads, s.history_refreshed) == (1, 1) and len(_wiersze(con, m)) == 8
    assert stacks.run_stack_lineage(con, now=LATER, xml_reader=lambda _p: surowe).history_reads == 0


def test_plan_nazwowy_i_n_z_m_nie_tykaja_reki_ani_zniw(con):
    """Wiersze `user` (także odrzucony werdykt) i `harvest` obok planu nazwowego i werdyktu „N z M”
    zostają co do wartości - klinga nie obniża rangi, a reconcile zdejmuje tylko `window`/`history`."""
    m = _master(con)
    lighty = _okno(con)
    reka = _light(con, "reka", date_obs="2025-08-29T20:00:00")
    zniwa = _light(con, "zniwa", date_obs="2025-08-29T21:00:00")
    stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml([-10.0] * 8))
    iid = _glowa(con, m)["id"]
    repo.link_integration(con, integration_id=iid, input_frame_id=reka, asserted_by="user", now=NOW)
    repo.link_integration(con, integration_id=iid, input_frame_id=zniwa, asserted_by="harvest", now=NOW)
    repo.judge_integration_input(con, integration_id=iid, input_frame_id=lighty[9], excluded=1, now=NOW)

    def reka_i_zniwa():
        return sorted(tuple(r) for r in con.execute(
            "SELECT input_frame_id, asserted_by, excluded FROM integration_input "
            "WHERE asserted_by IN ('user', 'harvest') ORDER BY input_frame_id"))
    przed = reka_i_zniwa()
    for xml in (_xml([-10.0] * 8), _xml([-10.0] * 5, idx0=20)):   # nazwy; potem bez nazw → „N z M”
        stacks.run_stack_lineage(con, now=LATER, xml_reader=lambda _p, x=xml: x)
        assert reka_i_zniwa() == przed


def test_klatki_rozlaczne_przy_dwoch_masterach_z_dublem_wejscia(con):
    """Dwa wejścia w jedną klatkę (duplikat w WBPP) - zbiór liczony rozłącznie, u KAŻDEGO z dwóch
    masterów dzielących lighty."""
    m1 = _master(con)
    m2 = _master(con, sha="m2", path=STOS + ".v2.xisf")
    lighty = _okno(con, 2)
    wejscia = [(_WEJSCIE.format(idx=f"{i:04d}", temp="-10.00"), True) for i in (0, 0, 1)]
    xml = "<xisf>" + _historia_property(wejscia) + "</xisf>"
    stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: xml)
    for m in (m1, m2):
        assert _wiersze(con, m) == sorted((f, "history") for f in lighty)
        assert _glowa(con, m)["lineage_basis"] == "name"


def test_historia_stosow_po_przejeciu_zeznania(monkeypatch):
    """Etap `stack_history` idzie PO `adopt_testimony`: przejęcie przepisuje `header_hash` kopii, więc
    historia zapisana przed nim od razu byłaby kandydatem następnej Dostawy."""
    from types import SimpleNamespace

    from horreum import derive
    wynik = SimpleNamespace(cancelled=False, adopted=0)
    for kandydat in ("copy_facts_candidates", "adopt_candidates", "stack_history_candidates"):
        monkeypatch.setattr(scan, kandydat, lambda con, root=None, **k: [1])
    for etap in ("backfill_copy_facts", "adopt_orphan_testimony", "backfill_stack_history"):
        monkeypatch.setattr(scan, etap, lambda con, **k: wynik)
    assert [n for n, _w in derive.adopt_stages(None, None, NOW)] == \
        ["copy_facts", "adopt_testimony", "stack_history"]


def test_pelny_zbior_z_nazw_rowny_oknu_stoi_na_nazwie(con):
    """N == M: nazwy i okno wskazują te same 8 klatek - podstawą jest NAZWA, nie temperatura."""
    m = _master(con)
    lighty = _okno(con, 8)
    s = stacks.run_stack_lineage(con, now=NOW, xml_reader=lambda _p: _xml([-10.0] * 8))
    assert _glowa(con, m)["lineage_basis"] == "name" and s.by_basis == {"name": 1}
    assert _wiersze(con, m) == sorted((f, "history") for f in lighty)
