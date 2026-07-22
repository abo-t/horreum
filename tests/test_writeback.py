"""Testy `horreum.writeback` — druga klinga, na PRAWDZIWYCH plikach FITS (astropy) i XISF (P6c).

Pełny cykl: skan pliku → staging → commit (os.replace) → undo. Weryfikuje: tożsamość `sha1_data`
PRZEŻYWA edycję nagłówka (brief T2), hash liczony z ZAPISANEGO pliku (T3), re-sync odświeża zeznanie
+ przelicza kamerę (R#2 — event frame.rederived), kontrola header_hash blokuje (T4), undo przywraca,
dwukrotne undo blocked, expected_header_hash blokuje stale-pending (R#7).

Sekcja XISF (P6c, kryteria §6 briefu P6): rekonstrukcja dokładna (pkt 2), odmowa bez tknięcia pliku
przy braku rezerwy (pkt 3), `sha1_data` niezmienione (pkt 4), undo bajtowe (pkt 6) i komplet bramek
odmowy (pkt 7). Pliki XISF budujemy tu SYNTETYCZNIE (`_xisf`) — realne archiwum sprawdza sonda
firsthand, bateria ma być hermetyczna."""

from __future__ import annotations

import hashlib
import sqlite3
import struct

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, repo, scan, writeback

NOW = "2026-07-03T00:00:00+00:00"


def _write_fits(path, **cards):
    """Zapisz minimalny plik FITS z danymi (identyczna sekcja danych = ta sama tożsamość)."""
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    for k, v in cards.items():
        hdu.header[k] = v
    hdu.writeto(path, overwrite=True)


def _scan_in(con, path, volume="V"):
    """Zeskanuj realny plik do bazy (frame+location+header+cards spójne ze skanem)."""
    rec = scan.scan_file(str(path))
    scan.ingest_record(con, rec, volume=volume, now=NOW, summary=scan.ScanSummary())
    return con.execute("SELECT id, sha1_data FROM frame ORDER BY id DESC LIMIT 1").fetchone()


def _loc_id(con, path):
    return con.execute("SELECT id FROM location WHERE path = ?", (str(path),)).fetchone()["id"]


def _stage(con, run_id, location_id, keyword, op, new_value, new_type, *, idx=None, expected):
    return repo.stage_pending(
        con, run_id=run_id, location_id=location_id, keyword=keyword, idx=idx, op=op,
        old_value=None, new_value=new_value, new_type=new_type, new_comment=None,
        expected_header_hash=expected)


def test_commit_edits_header_and_preserves_identity(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    p = tmp_path / "a.fits"
    _write_fits(p, INSTRUME="ASI2600MM Pro", TELESCOP="RC8", IMAGETYP="Light")
    fr = _scan_in(con, p)
    lid = _loc_id(con, p)
    hh = con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()["header_hash"]

    _stage(con, "R", lid, "TELESCOP", "set", "SkyWatcher RC8", "str", expected=hh)
    res = writeback.commit(con, "R", now=NOW)

    assert len(res.applied) == 1 and not res.blocked and not res.failed
    # plik na dysku ZMIENIONY
    assert fits.getheader(str(p))["TELESCOP"] == "SkyWatcher RC8"
    # tożsamość frame PRZEŻYWA (sha1_data ten sam — dane nietknięte)
    fr2 = con.execute("SELECT id, sha1_data FROM frame WHERE id=?", (fr["id"],)).fetchone()
    assert fr2["sha1_data"] == fr["sha1_data"]
    # zeznanie odświeżone (header.telescop nowy), header_hash location zmieniony
    hdr = con.execute("SELECT telescop FROM header WHERE frame_id=?", (fr["id"],)).fetchone()
    assert hdr["telescop"] == "SkyWatcher RC8"
    hh2 = con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()["header_hash"]
    assert hh2 and hh2 != hh
    # event mutacji pliku wyemitowany z actor=user:local (nie skan)
    evs = con.execute("SELECT verb FROM event WHERE actor='user:local'").fetchall()
    assert any(e["verb"] == "header.refreshed" for e in evs)
    con.close()


def test_commit_then_undo_restores(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    p = tmp_path / "b.fits"
    _write_fits(p, TELESCOP="RC8", IMAGETYP="Light")
    fr = _scan_in(con, p)
    lid = _loc_id(con, p)
    hh = con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()["header_hash"]

    _stage(con, "R", lid, "TELESCOP", "set", "EQ6", "str", expected=hh)
    cres = writeback.commit(con, "R", now=NOW)
    assert cres.commit_id is not None
    assert fits.getheader(str(p))["TELESCOP"] == "EQ6"

    ures = writeback.undo(con, cres.commit_id, now=NOW)
    assert len(ures.restored) == 1 and not ures.blocked
    assert fits.getheader(str(p))["TELESCOP"] == "RC8"       # przywrócone

    # dwukrotne undo → blocked (nagłówek != post_hash po pierwszym undo)
    ures2 = writeback.undo(con, cres.commit_id, now=NOW)
    assert len(ures2.blocked) == 1 and not ures2.restored
    con.close()


def test_header_hash_mismatch_blocks(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    p = tmp_path / "c.fits"
    _write_fits(p, TELESCOP="RC8", IMAGETYP="Light")
    _scan_in(con, p)
    lid = _loc_id(con, p)

    # expected_header_hash celowo ZŁY → write_changes blokuje, plik NIETKNIĘTY
    _stage(con, "R", lid, "TELESCOP", "set", "EQ6", "str", expected="deadbeef")
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.blocked) == 1 and not res.applied
    assert fits.getheader(str(p))["TELESCOP"] == "RC8"       # niezmieniony
    con.close()


def test_stale_pending_blocked_after_external_change(tmp_path):
    """R#7: plik zmieniony (re-skan) MIĘDZY stagingiem a commitem → expected_header_hash ≠ bieżący
    → blocked. Symulujemy edycją nagłówka poza writebackiem + re-skanem."""
    con = db.open_db(str(tmp_path / "h.db"))
    p = tmp_path / "d.fits"
    _write_fits(p, TELESCOP="RC8", IMAGETYP="Light")
    _scan_in(con, p)
    lid = _loc_id(con, p)
    hh = con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()["header_hash"]
    _stage(con, "R", lid, "FOCALLEN", "add", "600", "int", expected=hh)

    # ktoś zmienia plik i re-skan aktualizuje location.header_hash (stary staging = stęchły)
    _write_fits(p, TELESCOP="RC8", IMAGETYP="Light", GAIN=100)
    _scan_in(con, p)
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.blocked) == 1 and not res.applied
    con.close()


def test_porazka_backupu_po_zapisie_daje_failed_nie_wyjatek(tmp_path, monkeypatch):
    """D-X-14: backup wstawiany jest PO `os.replace`. Gdy padnie (dawniej: `hdu_index NOT NULL`
    kontra NULL dla XISF), pętla commitu NIE MOŻE wybuchnąć — plik jest już zmieniony. Kontrakt:
    baza re-syncowana do bajtów z dysku + status `failed` z powodem; reszta przebiegu leci dalej."""
    con = db.open_db(str(tmp_path / "h.db"))
    p = tmp_path / "f.fits"
    _write_fits(p, TELESCOP="RC8", IMAGETYP="Light")
    fr = _scan_in(con, p)
    lid = _loc_id(con, p)
    hh = con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()["header_hash"]
    _stage(con, "R", lid, "TELESCOP", "set", "EQ6", "str", expected=hh)

    def _boom(*a, **kw):
        raise sqlite3.IntegrityError("NOT NULL constraint failed: header_backups.hdu_index")
    monkeypatch.setattr(writeback.repo, "insert_header_backup", _boom)

    res = writeback.commit(con, "R", now=NOW)                 # ZERO wyjątku z pętli
    assert len(res.failed) == 1 and not res.applied
    assert "backup do undo NIE powstal" in res.failed[0].reason.replace("ł", "l")
    assert fits.getheader(str(p))["TELESCOP"] == "EQ6"        # plik ZMIENIONY (to nie jest rollback)
    # baza opisuje bajty z dysku: re-sync przeszedł mimo braku backupu
    assert con.execute("SELECT telescop FROM header WHERE frame_id=?",
                       (fr["id"],)).fetchone()["telescop"] == "EQ6"
    assert con.execute("SELECT count(*) FROM header_backups").fetchone()[0] == 0
    st = con.execute("SELECT status, reason FROM pending_changes WHERE run_id='R'").fetchone()
    assert st["status"] == "failed" and st["reason"]
    con.close()


# ============================================================ PISARZ XISF (P6c)

# Cele naprawy ED (brief §8): karta TELESCOP + karta FOCALLEN i ICH własności `<Property>`.
# `FOCALLEN` jest w MILIMETRACH, własność w METRACH — dlatego 796 ↔ 0.796.
_PROPS_ED = ('<Property id="Instrument:Telescope:FocalLength" type="Float64" value="0.796"/>'
             '<Property id="Instrument:Telescope:Name" type="String">ED</Property>')
_KW_ED = [("TELESCOP", "'ED'"), ("FOCALLEN", "796"), ("IMAGETYP", "'Flat'"),
          ("INSTRUME", "'ZWO ASI2600MM Pro'")]


def _xisf(tmp_path, name, *, keywords=_KW_ED, props=_PROPS_ED, payload=b"\x07" * 32, pad=64,
          reserved=b"\x00\x00\x00\x00", images=1):
    """Zapisz monolityczny XISF: nagłówek XML + REZERWA (`pad` bajtów wypełnienia) + attachment.

    Offset attachmentu zapisany na STAŁEJ szerokości (`{:08d}`), więc długość XML nie zależy od
    własnej wartości offsetu i nie trzeba szukać punktu stałego. `keywords` = `(nazwa, wartość
    [, komentarz])`, gdzie wartość podajesz DOKŁADNIE tak, jak ma stać w pliku (z apostrofami FITS
    albo bez — to materiał testu konwencji). `pad` = REZERWA nagłówka: ile bajtów może urosnąć,
    zanim pisarz musi odmówić. `images` > 1 → karty pod dwoma `<Image>` (poligon bramki D-X-11)."""
    def kw_xml():
        return "".join(f'<FITSKeyword name="{k[0]}" value="{k[1]}" '
                       f'comment="{k[2] if len(k) > 2 else ""}"/>' for k in keywords)

    def body(start):
        img = "".join(
            f'<Image geometry="4:4:1" sampleFormat="UInt16" '
            f'location="attachment:{start:08d}:{len(payload)}">{kw_xml()}</Image>'
            for _ in range(images))
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
                + props + img + '</xisf>').encode("utf-8")

    xml = body(scan.XISF_XML_OFFSET + len(body(0)) + pad)
    path = tmp_path / name
    with open(path, "wb") as fh:
        fh.write(b"XISF0100" + struct.pack("<I", len(xml)) + reserved
                 + xml + b"\x00" * pad + payload)
    return path


def _sha_pliku(path):
    return hashlib.sha1(path.read_bytes()).hexdigest()


def test_xisf_commit_naprawia_karte_i_wlasnosc_zachowujac_tozsamosc(tmp_path):
    """Naprawa ED end-to-end przez ORKIESTRACJĘ (ta sama `commit`, co dla FITS — dyspozycja po
    rozszerzeniu). Jeden staging na kartę rusza CZTERY wartości pliku: dwie karty i dwie własności
    (D-X-10), bo zapis samej karty zostawiłby plik sprzeczny ze sobą. Tożsamość klatki
    (`sha1_data` = sha1 attachmentu) przeżywa zapis — inaczej re-sync rozdwoiłby klatkę."""
    con = db.open_db(str(tmp_path / "h.db"))
    p = _xisf(tmp_path, "flat.xisf")
    fr = _scan_in(con, p)
    lid = _loc_id(con, p)
    hh = con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()["header_hash"]

    _stage(con, "R", lid, "TELESCOP", "set", "ED120R", "str", expected=hh)
    _stage(con, "R", lid, "FOCALLEN", "set", "789", "str", expected=hh)
    res = writeback.commit(con, "R", now=NOW)

    assert len(res.applied) == 1 and not res.blocked and not res.failed
    xml = scan.read_xisf_meta_full(str(p)).xml_bytes
    assert b"""value="'ED120R'\"""" in xml and b'value="789"' in xml     # karty (apostrofy z oryginału)
    assert b'value="0.789"' in xml and b">ED120R<" in xml               # własności: mm→m i tekst
    fr2 = con.execute("SELECT id, sha1_data FROM frame WHERE id=?", (fr["id"],)).fetchone()
    assert fr2["sha1_data"] == fr["sha1_data"]                          # TOŻSAMOŚĆ stoi
    assert scan.scan_file(str(p)).sha1_data == fr["sha1_data"]          # …i zgadza się z plikiem
    hdr = con.execute("SELECT telescop FROM header WHERE frame_id=?", (fr["id"],)).fetchone()
    assert hdr["telescop"] == "ED120R"                                  # re-sync odświeżył zeznanie
    hh2 = con.execute("SELECT header_hash, hdu_index FROM location WHERE id=?",
                      (lid,)).fetchone()
    assert hh2["header_hash"] != hh and hh2["hdu_index"] is None        # D-X-7: HDU obce formatowi
    con.close()


def test_xisf_undo_wraca_bajtowo_calym_plikiem(tmp_path):
    """§6 pkt 6: undo przywraca nagłówek BAJTOWO. Dla XISF (inaczej niż dla FITS, gdzie astropy
    kanonizuje karty strukturalne) wraca bajtowo CAŁY plik — bo wypełnienie jest zerowe, a łata
    nie tyka attachmentu. Backup XISF to `hdu_index` NULL: przed migracją 0007 ten INSERT
    wybuchałby PO `os.replace`."""
    con = db.open_db(str(tmp_path / "h.db"))
    p = _xisf(tmp_path, "u.xisf")
    przed = p.read_bytes()
    _scan_in(con, p)
    lid = _loc_id(con, p)
    hh = con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()["header_hash"]
    _stage(con, "R", lid, "TELESCOP", "set", "ED120R", "str", expected=hh)

    cres = writeback.commit(con, "R", now=NOW)
    assert cres.commit_id is not None and p.read_bytes() != przed
    assert con.execute("SELECT hdu_index FROM header_backups").fetchone()["hdu_index"] is None

    ures = writeback.undo(con, cres.commit_id, now=NOW)
    assert len(ures.restored) == 1 and not ures.blocked
    assert p.read_bytes() == przed                       # CAŁY plik bajtowo jak przed zapisem
    ures2 = writeback.undo(con, cres.commit_id, now=NOW)  # dwukrotne undo → blocked (post_hash)
    assert len(ures2.blocked) == 1 and not ures2.restored
    con.close()


def test_xisf_zapis_wlasna_wartoscia_nie_rusza_ani_bajtu(tmp_path):
    """§6 pkt 1 na POZIOMIE PISARZA: przepisanie kart ich AKTUALNYMI wartościami zostawia plik
    bajtowo identyczny — razem z własnościami, bo bramka zrozumienia gwarantuje, że własność jest
    dokładnie tym, co reguła liczy z karty. Implementacja, która gubi apostrofy, dokłada padding
    albo przelicza własność inaczej, pęka TUTAJ, a nie na archiwum."""
    p = _xisf(tmp_path, "id.xisf")
    przed = _sha_pliku(p)
    ops = [writeback.WriteOp("TELESCOP", "set", "ED", "str"),
           writeback.WriteOp("FOCALLEN", "set", "796", "str")]
    res = writeback.write_xisf_changes(str(p), ops, None)
    assert res.status == "applied" and _sha_pliku(p) == przed


def test_xisf_rekonstrukcja_dokladna_przy_zmianie_dlugosci(tmp_path):
    """§6 pkt 2 (kryterium FALSYFIKOWALNE — „nic nie napisałem" go nie przejdzie): nowy nagłówek
    to dokładnie `xml[:start] + nowe_bajty + xml[end:]` na wycinku karty, przy zmienionej długości."""
    p = _xisf(tmp_path, "rek.xisf", props="")            # bez własności — jeden wycinek
    stary = scan.read_xisf_meta_full(str(p)).xml_bytes
    start, end = scan.locate_value_span(stary, keyword="TELESCOP")

    res = writeback.write_xisf_changes(str(p), [writeback.WriteOp("TELESCOP", "set", "ED120R", "str")],
                                       None)
    nowy = scan.read_xisf_meta_full(str(p)).xml_bytes
    assert res.status == "applied"
    assert nowy == stary[:start] + b"'ED120R'" + stary[end:] and len(nowy) == len(stary) + 4
    assert res.post_hash == hashlib.sha1(nowy).hexdigest()     # hash z ZAPISANEGO pliku (T3)
    assert res.backup_text.encode("utf-8") == stary            # backup = oryginalny XML (D-X-9)


def test_xisf_rezerwa_jest_sufitem_a_nie_sugestia(tmp_path):
    """§6 pkt 3 + granica D-X-2: nagłówek może urosnąć DOKŁADNIE o rezerwę (attachmenty stoją
    w miejscu), a bajt więcej to `blocked` z plikiem NIETKNIĘTYM. Para przypadków pinuje `<=`
    — pomyłka o jeden w bramce przewraca dokładnie jeden z tych dwóch testów."""
    tuz = _xisf(tmp_path, "tuz.xisf", keywords=[("TELESCOP", "'ED'")], props="", pad=4)
    res = writeback.write_xisf_changes(str(tuz), [writeback.WriteOp("TELESCOP", "set", "ED120R", "str")],
                                       None)
    assert res.status == "applied"                       # +4 B w rezerwie 4 B — mieści się CO DO BAJTU

    za_duzo = _xisf(tmp_path, "za.xisf", keywords=[("TELESCOP", "'ED'")], props="", pad=4)
    przed = _sha_pliku(za_duzo)
    res2 = writeback.write_xisf_changes(
        str(za_duzo), [writeback.WriteOp("TELESCOP", "set", "ED120RX", "str")], None)
    assert res2.status == "blocked" and "nie mieści się" in res2.reason
    assert _sha_pliku(za_duzo) == przed                  # ODMOWA nie tyka pliku ani jednym bajtem


def test_xisf_wlasnosc_o_nieznanej_konwencji_blokuje(tmp_path):
    """BRAMKA ZROZUMIENIA (D-X-10): własność, której bieżąca wartość NIE jest tym, co reguła liczy
    z bieżącej karty, zatrzymuje zapis. Realny przypadek z archiwum: `FOCALLEN=105` i własność
    `0.1049999967217445` (artefakt Float32). Bez bramki wpisalibyśmy tam `0.105`, po cichu zmieniając
    semantykę pliku; z bramką user dostaje powód, a plik zostaje nietknięty."""
    p = _xisf(tmp_path, "float32.xisf", keywords=[("FOCALLEN", "105")],
              props='<Property id="Instrument:Telescope:FocalLength" type="Float64" '
                    'value="0.1049999967217445"/>')
    przed = _sha_pliku(p)
    res = writeback.write_xisf_changes(str(p), [writeback.WriteOp("FOCALLEN", "set", "789", "str")],
                                       None)
    assert res.status == "blocked" and "NIE ROZUMIEM" in res.reason
    assert _sha_pliku(p) == przed


def test_xisf_wlasnosc_nieobecna_jest_pomijana_nie_tworzona(tmp_path):
    """D-X-10: plik, który własności NIGDY nie miał, nie jest ze sobą sprzeczny — karta idzie do
    zapisu, własność NIE POWSTAJE (insercja elementu to inna klasa ryzyka, D-X-12)."""
    p = _xisf(tmp_path, "nomap.xisf", props="")
    res = writeback.write_xisf_changes(str(p), [writeback.WriteOp("TELESCOP", "set", "ED120R", "str")],
                                       None)
    xml = scan.read_xisf_meta_full(str(p)).xml_bytes
    assert res.status == "applied" and b"Instrument:Telescope:Name" not in xml


def test_xisf_komentarz_latany_jako_atrybut(tmp_path):
    """D-X-12 (ogon): `WriteOp.comment` dla XISF łatamy jako atrybut `comment` TĄ SAMĄ techniką —
    wartość i komentarz to dwa wycinki tego samego znacznika, składane jednym przejściem."""
    p = _xisf(tmp_path, "kom.xisf", keywords=[("TELESCOP", "'ED'", "stary")], props="")
    res = writeback.write_xisf_changes(
        str(p), [writeback.WriteOp("TELESCOP", "set", "ED120R", "str", comment="poprawione")], None)
    meta = scan.read_xisf_meta_full(str(p))
    assert res.status == "applied"
    assert [(c.value_raw, c.comment) for c in meta.cards] == [("ED120R", "poprawione")]


def test_xisf_stale_header_hash_blokuje_bez_tkniecia(tmp_path):
    """Kontrola `header_hash` jest kotwicą także dla XISF: plik zmieniony od podglądu → 'blocked',
    zero zapisu (T4). Bramka stoi PRZED wszystkimi innymi — nie liczymy łaty na stęchłym stanie."""
    p = _xisf(tmp_path, "stale.xisf")
    przed = _sha_pliku(p)
    res = writeback.write_xisf_changes(
        str(p), [writeback.WriteOp("TELESCOP", "set", "ED120R", "str")], "nie-ten-hash")
    assert res.status == "blocked" and res.reason == "header_hash mismatch"
    assert _sha_pliku(p) == przed


@pytest.mark.parametrize("nazwa, buduj, ops, fragment", [
    ("nieparsowalny",
     lambda tp: _uszkodz(_xisf(tp, "zly.xisf")),
     [writeback.WriteOp("TELESCOP", "set", "ED120R", "str")], "nieczytelny"),
    ("operacja add",
     lambda tp: _xisf(tp, "add.xisf"),
     [writeback.WriteOp("FILTER", "add", "Ha", "str")], "D-X-12"),
    ("karta nieobecna",
     lambda tp: _xisf(tp, "brak.xisf"),
     [writeback.WriteOp("FILTER", "set", "Ha", "str")], "nieobecna"),
    ("degenerat tożsamości",
     lambda tp: _xisf(tp, "degen.xisf", keywords=[("TELESCOP", "'ED'")], props="", images=0),
     [writeback.WriteOp("TELESCOP", "set", "ED120R", "str")], "rozdwoiłby"),
    ("własność poza nagłówkiem",
     lambda tp: _xisf(tp, "loc.xisf", keywords=[("TELESCOP", "'ED'")],
                      props='<Property id="Instrument:Telescope:Name" type="String" '
                            'location="attachment:900:4"/>'),
     [writeback.WriteOp("TELESCOP", "set", "ED120R", "str")], "location="),
    ("karty pod dwoma <Image>",
     lambda tp: _xisf(tp, "dwa.xisf", props="", images=2),
     [writeback.WriteOp("TELESCOP", "set", "ED120R", "str")], "D-X-11"),
])
def test_xisf_bramki_odmowy_zero_zapisu(tmp_path, nazwa, buduj, ops, fragment):
    """§6 pkt 7 — komplet bramek odmowy. KAŻDA daje 'blocked' z czytelnym powodem i zostawia plik
    bajtowo nietknięty. Odmowa nie jest awarią: user ma zobaczyć, CZEGO nie zrobiliśmy i dlaczego,
    a nie stack trace ani cichy sukces."""
    p = buduj(tmp_path)
    przed = _sha_pliku(p)
    res = writeback.write_xisf_changes(str(p), ops, None)
    assert res.status == "blocked", f"{nazwa}: {res}"
    assert fragment in res.reason and _sha_pliku(p) == przed


def _uszkodz(path):
    """Zepsuj XML nagłówka NIE ruszając długości (plik zostaje monolitycznym XISF-em o nieczytelnym
    nagłówku — dokładnie stan `frame 15629` z archiwum)."""
    raw = bytearray(path.read_bytes())
    i = raw.index(b"<xisf")
    raw[i:i + 5] = b"<<isf"
    path.write_bytes(bytes(raw))
    return path


def test_xisf_awaria_io_to_failed_nie_blocked(tmp_path):
    """Granica odmowa↔awaria: brak pliku to `OSError`, czyli AWARIA ('failed') — jutro może się
    udać. Gdyby wpadła do wspólnego worka 'blocked', raport twierdziłby, że wydaliśmy werdykt
    o pliku, którego nawet nie otworzyliśmy."""
    res = writeback.write_xisf_changes(str(tmp_path / "nie-ma.xisf"),
                                       [writeback.WriteOp("TELESCOP", "set", "X", "str")], None)
    assert res.status == "failed" and "FileNotFoundError" in res.reason


def test_gone_copy_skipped(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    p = tmp_path / "e.fits"
    _write_fits(p, TELESCOP="RC8", IMAGETYP="Light")
    _scan_in(con, p)
    lid = _loc_id(con, p)
    hh = con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()["header_hash"]
    _stage(con, "R", lid, "TELESCOP", "set", "EQ6", "str", expected=hh)
    # oznacz kopię jako zniknętą przez repo? present ustawiamy wprost (test poza bramką)
    con.execute("UPDATE location SET present=0 WHERE id=?", (lid,))
    con.commit()
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.skipped) == 1 and not res.applied
    con.close()
