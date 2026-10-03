"""Fakty KOPII z jej nagłówka (migracja 0021): liczba i role obrazów, zeznanie pól osi, kotwica
`hdr_hash` - od czytnika XISF, przez klingę kopii i skan, po uzupełnienie wierszy sprzed migracji
i predykat „kopie jednej klatki mówią różnie" liczony z samego stanu.

Pliki syntetyczne w `tmp_path` (zero archiwum, zero żywej bazy). Pomiar na kopii żywej bazy nie
mieszka w teście - bazy prywatnej w repo publicznym nie ma i mieć nie może."""
import json
import os
import shutil
import sqlite3
import struct
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, repo, scan
from horreum.gui import queries
from horreum.resolve import headers
from horreum.resolve.headers import COPY_TESTIMONY_RULE, copy_testimony

NOW = "2026-09-26T12:00:00+00:00"
PAYLOAD = b"\x05" * 32


def _xisf(path, keywords=(), images=({"id": "integration"},), payload=PAYLOAD):
    """XISF z REALNYM attachmentem PIERWSZEGO obrazu (tożsamość klatki = sha1 `payload`) i dowolną
    liczbą kolejnych `<Image>` o zadanych atrybutach (`imageType`/`id` albo żadnego). Kolejne obrazy
    wskazują ten sam blok - czytnik nie sięga po ich bajty, a tożsamość bierze pierwszy."""
    def xml_for(start):
        loc = f"attachment:{start}:{len(payload)}"
        karty = "".join(f'<FITSKeyword name="{k}" value="{v}" comment=""/>' for k, v in keywords)
        obrazy = []
        for i, attrs in enumerate(images):
            a = "".join(f' {k}="{v}"' for k, v in attrs.items())
            obrazy.append(f'<Image geometry="4:4:1" sampleFormat="UInt16"{a} location="{loc}">'
                          + (karty if i == 0 else "") + "</Image>")
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
                + "".join(obrazy) + "</xisf>").encode("utf-8")
    start = 0
    for _ in range(4):
        nowy = 16 + len(xml_for(start))
        if nowy == start:
            break
        start = nowy
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"XISF0100" + struct.pack("<I", len(xml_for(start))) + b"\x00" * 4)
        fh.write(xml_for(start))
        fh.write(payload)
    return path


def _fits(path, filt, n=7):
    hdu = fits.PrimaryHDU(data=np.full((4, 4), n, np.uint16))
    hdu.header["INSTRUME"] = "ZWO ASI2600MM Pro"
    hdu.header["IMAGETYP"] = "Master Flat"
    hdu.header["FILTER"] = filt
    hdu.header["EXPTIME"] = 1.5
    path.parent.mkdir(parents=True, exist_ok=True)
    fits.HDUList([hdu]).writeto(str(path))
    return path


_FLAT = (("IMAGETYP", "'Master Flat'"), ("INSTRUME", "'ZWO ASI2600MC Pro'"),
         ("EXPTIME", "1.34"), ("XBINNING", "1"))


def _loc(con, path):
    return con.execute("SELECT * FROM location WHERE path = ?", (str(path),)).fetchone()


# ═════════════════════════ czytnik: liczba i role obrazów


def test_role_obrazow_imageType_potem_id_potem_brak(tmp_path):
    """Rola = `imageType` (§11.5.1), a gdy go brak - `id`, a gdy i tego brak - None; KAŻDY `<Image>`
    w kolejności dokumentu. Plik bez `imageType` (konwencja WBPP: same `id`) i pojedynczy obraz bez
    obu atrybutów (248 plików archiwum) to dwa realne warianty, nie teoria."""
    f = _xisf(tmp_path / "m.xisf", _FLAT, images=(
        {"id": "integration", "imageType": "MasterFlat"}, {"id": "rejection_low"}, {}))
    meta = scan.read_xisf_meta_full(str(f))
    assert meta.image_roles == ("MasterFlat", "rejection_low", None)
    goly = _xisf(tmp_path / "g.xisf", _FLAT, images=({},))
    assert scan.read_xisf_meta_full(str(goly)).image_roles == (None,)


def test_scan_file_niesie_role_tylko_dla_XISF(tmp_path):
    """FITS dostaje None: liczba HDU wymagałaby czytania nagłówków za blokami danych (dodatkowe I/O
    na 15,6 tys. plików) - kolumna mówi „nie wiem", a nie zgaduje „1"."""
    x = scan.scan_file(str(_xisf(tmp_path / "x.xisf", _FLAT, images=(
        {"id": "integration"}, {"id": "rejection_low"}, {"id": "rejection_high"}))))
    assert x.image_roles == ("integration", "rejection_low", "rejection_high")
    assert scan.scan_file(str(_fits(tmp_path / "f.fits", "Ha"))).image_roles is None


def test_fakty_kopii_z_nagłowka_koercja_i_kotwica(tmp_path):
    """`copy_header_facts` rzutuje tą samą drogą, co pola gorące `header` (XISF-owy tekst `'1.34'`
    staje się liczbą), role jadą jako lista JSON, a kotwicą jest odcisk tego nagłówka. Bez nagłówka
    albo bez odcisku faktów NIE MA - CHECK 0021 i tak nie przyjąłby faktu bez kotwicy."""
    rec = scan.scan_file(str(_xisf(tmp_path / "x.xisf", _FLAT + (("FILTER", "'CLS'"),),
                                   images=({"id": "integration"}, {}))))
    f = scan.copy_header_facts(rec.header, rec.header_hash, rec.image_roles)
    assert set(f) == set(repo.COPY_FACTS)
    assert (f["hdr_filter"], f["hdr_imagetyp"], f["hdr_exptime"], f["hdr_xbinning"]) == (
        "CLS", "Master Flat", 1.34, 1)
    assert (f["image_count"], json.loads(f["image_roles"]), f["hdr_hash"], f["hdr_rule"]) == (
        2, ["integration", None], rec.header_hash, COPY_TESTIMONY_RULE)
    assert scan.copy_header_facts(None, None, None) == dict.fromkeys(repo.COPY_FACTS)
    assert scan.copy_header_facts(rec.header, None, rec.image_roles) == dict.fromkeys(repo.COPY_FACTS)


# ═════════════════════════ skan → klinga kopii


def _dwie_kopie(tmp_path):
    """Jedna klatka (ten sam attachment), dwie kopie: CLS z trzema obrazami, L-Pro z jednym."""
    a = _xisf(tmp_path / "ARCH" / "A_CLS" / "m.xisf", _FLAT + (("FILTER", "'CLS'"),),
              images=({"imageType": "MasterFlat"}, {"imageType": "RejectionMapLow"},
                      {"imageType": "RejectionMapHigh"}))
    b = _xisf(tmp_path / "ARCH" / "B_LPRO" / "m.xisf", _FLAT + (("FILTER", "'L-Pro'"),),
              images=({"id": "integration"},))
    return tmp_path / "ARCH", a, b


def test_skan_zapisuje_fakty_KAZDEJ_kopii_a_header_zostaje_przy_pierwszej(tmp_path):
    """Druga kopia istniejącej klatki NIE nagrywa zeznania `header` (reguła N-lokacji), ale jej
    fakty kopii lądują na jej `location` - inaczej rozjazd byłby niewyliczalny. Ponowny skan (brama
    OFF, obie kopie czytane od nowa) niczego nie przełącza i nie emituje ani jednego zdarzenia:
    `header` zmienia się wyłącznie, gdy zmienia się odcisk nagłówka KTÓREJŚ kopii (badanie pkt 2)."""
    root, a, b = _dwie_kopie(tmp_path)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    la, lb = _loc(con, a), _loc(con, b)
    assert la["frame_id"] == lb["frame_id"]
    assert (la["hdr_filter"], la["image_count"], lb["hdr_filter"], lb["image_count"]) == (
        "CLS", 3, "L-Pro", 1)
    assert json.loads(la["image_roles"]) == ["MasterFlat", "RejectionMapLow", "RejectionMapHigh"]
    assert la["hdr_hash"] == la["header_hash"] and lb["hdr_hash"] == lb["header_hash"]
    assert con.execute("SELECT filter_raw FROM header").fetchone()[0] == "CLS"
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    scan.scan_tree(con, root, volume="?", now=NOW)
    assert con.execute("SELECT filter_raw FROM header").fetchone()[0] == "CLS"
    assert con.execute("SELECT count(*) FROM event WHERE id > ?", (ev,)).fetchone()[0] == 0
    con.close()


def test_kopia_nieczytelna_nie_ma_faktow(tmp_path):
    """W1 (nagłówek nie parsuje się) → wszystkie fakty kopii NULL, kotwica NULL - „nie wiem" ma jedną
    postać i nie udaje zgodności ani rozjazdu."""
    zly = tmp_path / "ARCH" / "zly.xisf"
    zly.parent.mkdir(parents=True)
    zly.write_bytes(b"XISF0100" + struct.pack("<I", 8) + b"\x00" * 4 + b"<xisf><<" + b"\x00" * 8)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, tmp_path / "ARCH", volume="?", now=NOW)
    row = _loc(con, zly)
    assert all(row[k] is None for k in repo.COPY_FACTS)
    con.close()


def test_zmiana_naglowka_kopii_odswieza_jej_fakty_jednym_zapisem(tmp_path):
    """Nagłówek kopii zmieniony na dysku → skan odświeża odcisk I fakty tym samym UPDATE-em (kotwica
    idzie za odciskiem), a zdarzenie `location.refreshed` niesie przejście pola zeznania."""
    root, a, _b = _dwie_kopie(tmp_path)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    _xisf(a, _FLAT + (("FILTER", "'CLX'"),), images=({"imageType": "MasterFlat"},))
    scan.scan_tree(con, root, volume="?", now="2026-09-26T13:00:00+00:00")
    la = _loc(con, a)
    assert (la["hdr_filter"], la["image_count"], la["hdr_hash"]) == ("CLX", 1, la["header_hash"])
    payload = json.loads(con.execute(
        "SELECT payload FROM event WHERE verb = 'location.refreshed' AND target = ? "
        "ORDER BY id DESC", (f"location:{la['id']}",)).fetchone()[0])
    assert payload["hdr_filter"] == {"before": "CLS", "after": "CLX"}
    assert payload["image_count"] == {"before": 3, "after": 1}
    con.close()


# ═════════════════════════ bramki zapisu


def test_klinga_odbija_zly_ksztalt_i_zwietrzale_fakty(tmp_path):
    """Trzy bramki: słownik faktów bez kompletu kluczy (literał SQL wymienia kolumny po nazwie -
    brak klucza byłby cichym NULL-em), zmiana odcisku nagłówka kopii BEZ odświeżenia jej faktów
    (CHECK 0021 - IntegrityError zamiast cichej nieprawdy) i uzupełnienie bez kotwicy."""
    con = db.open_db(str(tmp_path / "h.db"))
    fid, _ = repo.upsert_frame(con, sha1_data="s1", kind="flat", filetype="xisf", camera_id=None,
                               now=NOW)
    with pytest.raises(ValueError):
        repo.add_location(con, frame_id=fid, volume="V", path="/a.xisf", header_hash="h1",
                          copy_facts={"hdr_filter": "Ha"}, now=NOW)
    fakty = dict.fromkeys(repo.COPY_FACTS)
    fakty.update(hdr_filter="Ha", hdr_hash="h1")
    with pytest.raises(ValueError):                  # kotwica bez reguły koercji (0025)
        repo.add_location(con, frame_id=fid, volume="V", path="/a.xisf", header_hash="h1",
                          copy_facts=fakty, now=NOW)
    fakty["hdr_rule"] = COPY_TESTIMONY_RULE
    lid, _ = repo.add_location(con, frame_id=fid, volume="V", path="/a.xisf", header_hash="h1",
                               copy_facts=fakty, now=NOW)
    with pytest.raises(sqlite3.IntegrityError):
        repo.refresh_location(con, location_id=lid, frame_id=fid, mtime="m", file_sha1=None,
                              header_hash="h2", hdu_index=None, compressed=None, size_bytes=None,
                              unreadable_since=None, unreadable_kind=None, unreadable_reason=None,
                              present=1, now=NOW)
    with pytest.raises(ValueError):
        repo.record_copy_facts(con, location_id=lid, copy_facts=dict.fromkeys(repo.COPY_FACTS),
                               now=NOW)
    con.close()


def test_uzupelnienie_nie_nadpisuje_i_nie_wyprzedza_skanu(tmp_path):
    """`record_copy_facts` pisze WYŁĄCZNIE, gdy odcisk przeczytanego nagłówka == `header_hash`
    wiersza i faktów jeszcze nie ma. Inny odcisk (kopia zmieniona od skanu) albo fakty już zebrane →
    False, ZERO UPDATE, ZERO zdarzenia."""
    con = db.open_db(str(tmp_path / "h.db"))
    fid, _ = repo.upsert_frame(con, sha1_data="s1", kind="flat", filetype="xisf", camera_id=None,
                               now=NOW)
    lid, _ = repo.add_location(con, frame_id=fid, volume="V", path="/a.xisf", header_hash="h1",
                               now=NOW)
    obce = dict.fromkeys(repo.COPY_FACTS)
    obce.update(hdr_filter="Ha", hdr_hash="INNY", hdr_rule=COPY_TESTIMONY_RULE)
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    assert repo.record_copy_facts(con, location_id=lid, copy_facts=obce, now=NOW) is False
    swoje = dict(obce, hdr_hash="h1")
    assert repo.record_copy_facts(con, location_id=lid, copy_facts=swoje, now=NOW) is True
    assert repo.record_copy_facts(con, location_id=lid, copy_facts=dict(swoje, hdr_filter="OIII"),
                                  now=NOW) is False
    assert con.execute("SELECT hdr_filter FROM location WHERE id = ?", (lid,)).fetchone()[0] == "Ha"
    assert con.execute("SELECT count(*) FROM event WHERE id > ?", (ev,)).fetchone()[0] == 1
    con.close()


# ═════════════════════════ uzupełnienie wierszy sprzed migracji


def _baza_sprzed_0021(tmp_path, pliki):
    """Kopie wciągnięte klingą BEZ faktów (tak wyglądają wiersze sprzed 0021): odcisk nagłówka
    znany, fakty kopii NULL. Frame per sha1 danych - dwie kopie jednej klatki dzielą frame."""
    con = db.open_db(str(tmp_path / "h.db"))
    for p in pliki:
        rec = scan.scan_file(str(p))
        fid, _ = repo.upsert_frame(con, sha1_data=rec.sha1_data, kind="master_flat",
                                   filetype=scan._filetype(rec.path), camera_id=None, now=NOW)
        repo.add_location(con, frame_id=fid, volume="V", path=rec.path, mtime=rec.mtime,
                          header_hash=rec.header_hash, now=NOW)
    return con


def test_uzupelnienie_czyta_same_naglowki_i_jest_idempotentne(tmp_path):
    """Kandydaci = XISF wszystkie + każda kopia klatki z >1 obecną kopią (FITS też); pojedynczy FITS
    NIE (nie ma z czym porównać, a 15 tys. odczytów nie kupuje niczego). Drugie wywołanie: zero
    kandydatów, zero odczytu, zero zdarzeń. Zeznania `header` klatki uzupełnienie nie rusza."""
    root, a, b = _dwie_kopie(tmp_path)
    f1 = _fits(root / "F" / "jeden.fits", "Ha", n=1)
    f2a = _fits(root / "F" / "dwa_a.fits", "Ha", n=2)
    f2b = _fits(root / "G" / "dwa_b.fits", "OIII", n=2)          # ta sama treść, inny FILTER
    con = _baza_sprzed_0021(tmp_path, [a, b, f1, f2a, f2b])
    kand = {r["path"] for r in scan.copy_facts_candidates(con)}
    assert kand == {str(a), str(b), str(f2a), str(f2b)}
    s = scan.backfill_copy_facts(con, now=NOW)
    assert (s.rows, s.read, s.written, s.stale, s.failed, s.remaining) == (4, 4, 4, 0, 0, 0)
    assert (_loc(con, a)["image_count"], _loc(con, b)["image_count"]) == (3, 1)
    assert (_loc(con, f2a)["image_count"], _loc(con, f2a)["hdr_filter"]) == (None, "Ha")
    assert _loc(con, f1)["hdr_hash"] is None
    assert con.execute("SELECT count(*) FROM header").fetchone()[0] == 0
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    s2 = scan.backfill_copy_facts(con, now=NOW)
    assert (s2.rows, s2.read, s2.written) == (0, 0, 0)
    assert con.execute("SELECT count(*) FROM event WHERE id > ?", (ev,)).fetchone()[0] == 0
    con.close()


def test_kandydaci_porownywalni_to_kopie_klatek_z_wiecej_niz_jedna_lokacja(tmp_path):
    """Pojedynczy XISF jest kandydatem uzupełnienia (liczba i role obrazów żyją tylko tam), ale jego
    fakty nie zmienią ani „Kopii niezgodnych", ani „Zeznania z nieobecnej kopii" - obie liczby
    porównują kopie JEDNEJ klatki. `porownywalne=True` zostawia wyłącznie kopie klatek o >1
    lokacji ogółem: tym pyta licznik „?" Porządków, żeby 412 pojedynczych XISF archiwum nie
    zamieniało zera w „nie wiem".

    Falsyfikator: zdejmij gałąź `porownywalne` z SELECT-a → pierwsza asercja widzi `solo`."""
    root, a, b = _dwie_kopie(tmp_path)
    solo = _xisf(root / "S" / "solo.xisf", _FLAT, payload=b"\x09" * 32)
    con = _baza_sprzed_0021(tmp_path, [a, b, solo])
    assert {r["path"] for r in scan.copy_facts_candidates(con, porownywalne=True)} == {
        str(a), str(b)}
    assert {r["path"] for r in scan.copy_facts_candidates(con)} == {str(a), str(b), str(solo)}
    assert [r["path"] for r in scan.copy_facts_candidates(con, root / "S", porownywalne=True)] == []
    con.close()


# Dawny literał kandydatów (sprzed AR-35) - klasa wpisana w SELECT. Zamrożony tu jako wzorzec
# porównania: nowa droga (klasa z `queries.copy_facts_class`) ma dać na tej samej populacji to samo.
_KANDYDACI_DAWNI = (
    "SELECT l.id FROM location l JOIN frame f ON f.id = l.frame_id "
    "WHERE l.present = 1 AND l.header_hash IS NOT NULL AND l.hdr_hash IS NULL "
    "  AND l.unreadable_since IS NULL "
    "  AND NOT EXISTS (SELECT 1 FROM inplace_op o WHERE o.location_id = l.id "
    "                  AND o.phase IN (SELECT value FROM json_each(?))) "
    "  AND ((f.filetype = 'xisf' AND ? = 0) OR l.frame_id IN ("
    "       SELECT frame_id FROM location GROUP BY frame_id HAVING COUNT(*) > 1)) "
    "ORDER BY l.id")


def test_klasa_kandydata_jeden_literal_dla_dostawy_i_komorki_obrazy(tmp_path):
    """AR-35: „?" w kolumnie „Obrazy" liczył klasę kandydata lustrem po stronie Pythona (XISF albo
    `n_present + n_vanished > 1`), a etap Dostawy - literałem SQL w `copy_facts_candidates`: jeden
    fakt w dwóch miejscach. Teraz klasę liczy jeden literał (`queries.copy_facts_class`), a read-model
    (`queries.base_rows`) oddaje z niego flagę `copy_facts_class`.

    Zachowanie bez zmian, dowód na tej samej populacji (każdy kształt klatki: XISF i FITS, jedna
    kopia obecna albo zniknięta, dwie obecne, obecna z martwą siostrą): flaga == dawne lustro
    komórki, a kandydaci == dawny literał, w obu trybach `porownywalne`.

    Falsyfikator: zdejmij kolumnę `copy_facts_class` z `base_rows` - pierwsza asercja pada na
    brakującym kluczu; wróć z klasą do lustra w gridzie - test komórki w `test_gui_grid` widzi „?"
    mimo flagi 0."""
    con = db.open_db(str(tmp_path / "h.db"))
    # frame_id → (filetype, obecność kolejnych kopii)
    populacja = {1: ("xisf", [1]), 2: ("fits", [1]), 3: ("fits", [1, 0]), 4: ("fits", [1, 1]),
                 5: ("xisf", [1, 1]), 6: ("fits", [0]), 7: ("xisf", [0]), 8: ("fits", [0, 0])}
    lid = 0
    for fid, (typ, kopie) in populacja.items():
        con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
                    "VALUES (?, 'light', ?, ?, ?)", (fid, typ, f"s{fid}", NOW))
        for obecna in kopie:
            lid += 1
            con.execute("INSERT INTO location(id, frame_id, volume, path, header_hash, present) "
                        "VALUES (?, ?, 'V', ?, 'hh', ?)", (lid, fid, f"/a/{lid}.{typ}", obecna))
    con.commit()

    wiersze = queries.base_rows(con, list(populacja))
    dawne_lustro = {r["frame_id"]: r["filetype"] == "xisf"
                    or (r["n_present"] or 0) + (r["n_vanished"] or 0) > 1 for r in wiersze}
    flaga = {r["frame_id"]: bool(r["copy_facts_class"]) for r in wiersze}
    assert flaga == dawne_lustro
    assert {fid for fid, k in flaga.items() if k} == set(queries.copy_facts_class(con)) == {
        1, 3, 4, 5, 7, 8}
    assert queries.copy_facts_class(con, porownywalne=True) == [3, 4, 5, 8]
    fazy = json.dumps(list(repo.INPLACE_ISOLATING_PHASES))
    for por in (False, True):
        dawni = [r[0] for r in con.execute(_KANDYDACI_DAWNI, (fazy, int(por)))]
        assert [r["id"] for r in scan.copy_facts_candidates(con, porownywalne=por)] == dawni
    con.close()


def test_read_model_nie_ciagnie_astropy():
    """Konwencja „queries bez astropy": read-model czytają komendy CLI, które nie ładują numpy ani
    astropy (`sky`, `targets`, `presence`, `projection`). Klasa kandydata faktów kopii mieszka
    w `queries`, a `scan` sięga po nią leniwie - import read-modelu nie ciągnie skanu.

    Świeży proces, bo w procesie testów `scan` siedzi już w `sys.modules`.
    Falsyfikator: wróć z importem `copy_facts_class` z `scan` na górę `queries` - astropy wraca."""
    import subprocess
    import sys
    kod = ("import sys, horreum.gui.queries; "
           "print(sorted(m for m in ('astropy', 'numpy', 'horreum.scan') if m in sys.modules))")
    wynik = subprocess.run([sys.executable, "-c", kod], capture_output=True, text=True, check=True)
    assert wynik.stdout.strip() == "[]", wynik.stdout + wynik.stderr


def test_uzupelnienie_fakty_zebrane_rownolegle_nie_sa_stale(tmp_path, monkeypatch):
    """Między wyborem kandydatów a zapisem fakty kopii dociągnął ktoś inny (re-sync pisarza po
    zapisie nagłówka idzie przez `ingest_record`, który zapisuje fakty i NOWY odcisk). Ponowienie
    po konflikcie generacji porównywało odcisk z MIGAWKI kandydatów, więc kopia z nowym nagłówkiem
    lądowała w „zmienione na dysku od skanu" - a nic nie czeka. Teraz wiersz jest czytany od nowa:
    fakty już są → `elsewhere`, zero zapisu, zero ścieżki w `stale`.

    Falsyfikator: wróć do `header_hash == row["header_hash"]` → `stale == 1`."""
    root, a, b = _dwie_kopie(tmp_path)
    con = _baza_sprzed_0021(tmp_path, [a, b])
    prawdziwa = scan._read_meta
    stan = {"raz": True}

    def _przeplot(sciezka, *aa, **kw):
        if str(sciezka) == str(a) and stan["raz"]:
            stan["raz"] = False
            # pisarz zmienia nagłówek a, operacja w dzienniku (generacja odrzuci ten odczyt),
            # a jego re-sync zapisuje fakty i nowy odcisk
            _xisf(a, _FLAT + (("FILTER", "'CLX'"),), images=({"imageType": "MasterFlat"},))
            _operacja(con, _loc(con, a)["id"], "synced")
            vol = _loc(con, a)["volume"]
            scan.ingest_record(con, scan.scan_file(str(a)), volume=vol, now=NOW,
                               summary=scan.ScanSummary())
        return prawdziwa(sciezka, *aa, **kw)
    monkeypatch.setattr(scan, "_read_meta", _przeplot)
    s = scan.backfill_copy_facts(con, now=NOW)
    monkeypatch.undo()
    assert (s.written, s.elsewhere, s.stale, s.stale_paths, s.remaining) == (1, 1, 0, [], 0), s
    assert _loc(con, a)["hdr_filter"] == "CLX"
    con.close()


def test_uzupelnienie_drugi_konflikt_generacji_to_zapis_w_toku_nie_stale(tmp_path, monkeypatch):
    """Dwa konflikty generacji z rzędu (zapis nagłówka w miejscu w toku) to nie jest fakt o pliku:
    plik jest zdrowy, a „zmienione na dysku od skanu" wysyłało człowieka do skanu, który niczego
    nie zmieni. Osobny licznik `raced` (wzór `AdoptSummary.raced`), bez ścieżek; kopia czeka.

    Falsyfikator: licz drugi `StaleScanRecord` jako `stale` → asercja pada."""
    root, a, b = _dwie_kopie(tmp_path)
    con = _baza_sprzed_0021(tmp_path, [a])

    def _odmowa(*_a, **_kw):
        raise repo.StaleScanRecord("zapis w miejscu w toku")
    monkeypatch.setattr(repo, "record_copy_facts", _odmowa)
    s = scan.backfill_copy_facts(con, now=NOW)
    monkeypatch.undo()
    assert (s.read, s.written, s.raced, s.stale, s.stale_paths, s.remaining) == (
        1, 0, 1, 0, [], 1), s
    con.close()


@pytest.mark.parametrize("cale_drzewo", [False, True])
def test_uzupelnienie_kotwica_jest_swiadkiem_skasowania(tmp_path, monkeypatch, cale_drzewo):
    """Bez korzenia świadkiem skasowania jest istniejący przodek pliku PONIŻEJ kotwicy (litera dysku
    / korzeń udziału). Plik leżący BEZPOŚREDNIO w kotwicy (albo całe drzewo pod nią skasowane) nie
    ma takiego przodka, a sama kotwica, która istnieje, też jest żywym świadkiem: udział stoi,
    pliku nie ma → `missing`, nie `failed`. Kotwicę udaje katalog `tmp_path` (podmiana
    `os.path.splitdrive`), bo prawdziwej litery dysku test nie rusza.

    Falsyfikator: zdejmij sprawdzenie kotwicy ze `swiadek_zyje` → `failed == 1`."""
    kotwica = str(tmp_path / "UDZIAL")
    os.makedirs(kotwica)
    plik = (os.path.join(kotwica, "NOC", "m.xisf") if cale_drzewo
            else os.path.join(kotwica, "m.xisf"))
    os.makedirs(os.path.dirname(plik), exist_ok=True)
    _xisf(Path(plik), _FLAT)
    con = _baza_sprzed_0021(tmp_path, [plik])
    if cale_drzewo:
        shutil.rmtree(os.path.dirname(plik))
    else:
        os.remove(plik)
    prawdziwy = os.path.splitdrive
    monkeypatch.setattr(scan.os.path, "splitdrive",
                        lambda p: (kotwica, p[len(kotwica):]) if str(p).startswith(kotwica)
                        else prawdziwy(p))
    s = scan.backfill_copy_facts(con, now=NOW)
    monkeypatch.undo()
    assert (s.missing, s.failed, s.failed_paths) == (1, 0, []), s
    con.close()


def test_uzupelnienie_odmawia_kopii_zmienionej_i_zgubionej(tmp_path):
    """Nagłówek zmieniony od skanu → `stale` (fakty należą do skanu, który odświeży też `header`
    i `cards`); plik, którego nie ma w ISTNIEJĄCYM katalogu → `missing` (skasowany z dysku - robota
    passa obecności, nie „nieczytelny"). Oba ZERO zapisu i oba zostają w `remaining`."""
    root, a, b = _dwie_kopie(tmp_path)
    con = _baza_sprzed_0021(tmp_path, [a, b])
    _xisf(a, _FLAT + (("FILTER", "'CLX'"),), images=({"imageType": "MasterFlat"},))
    os.remove(b)
    s = scan.backfill_copy_facts(con, now=NOW)
    assert (s.written, s.stale, s.missing, s.failed, s.remaining) == (0, 1, 1, 0, 2)
    assert s.stale_paths == [str(a)] and s.missing_paths == [str(b)] and s.failed_paths == []
    assert _loc(con, a)["hdr_hash"] is None
    con.close()


@pytest.mark.parametrize("z_korzeniem", [True, False])
def test_uzupelnienie_skasowany_caly_folder_nocy_to_brak_pliku(tmp_path, z_korzeniem):
    """Skasowany CAŁY folder nocy zabiera katalog-rodzica razem z plikiem - to nadal skasowanie,
    nie „nieczytelne". Świadkiem jest korzeń przebiegu (albo, bez korzenia, istniejący przodek
    poniżej litery dysku), nie rodzic. Falsyfikator: świadek = `isdir(dirname(path))` → `failed`."""
    import shutil
    root, a, b = _dwie_kopie(tmp_path)
    con = _baza_sprzed_0021(tmp_path, [a, b])
    shutil.rmtree(b.parent)
    s = scan.backfill_copy_facts(con, now=NOW, root=root if z_korzeniem else None)
    assert (s.written, s.missing, s.failed, s.remaining) == (1, 1, 0, 1)
    assert s.missing_paths == [str(b)] and s.failed_paths == []
    con.close()


def test_uzupelnienie_zerwany_korzen_w_trakcie_to_nieczytelne(tmp_path):
    """Korzeń przebiegu znika w trakcie (zerwany udział) - brak pliku niczego wtedy nie dowodzi,
    więc `failed`, nie `missing`. Przebieg kończy się raportem: `remaining` liczy się po korzeniu
    skanonizowanym na starcie, bo ponowne `canonize_root` na zerwanym udziale rzuciłoby już po
    zapisanych faktach."""
    import shutil
    root, a, b = _dwie_kopie(tmp_path)
    con = _baza_sprzed_0021(tmp_path, [a, b])

    def zerwij(done, _total, _path, _s):
        if done == 1:
            shutil.rmtree(root)
    s = scan.backfill_copy_facts(con, now=NOW, root=root, progress=zerwij)
    assert (s.written, s.missing, s.failed, s.remaining) == (1, 0, 1, 1)
    assert s.failed_paths[0].startswith(str(b)) and s.missing_paths == []
    con.close()


def test_uzupelnienie_bez_korzenia_nieosiagalny_nosnik_to_nieczytelne(tmp_path):
    """Bez korzenia świadkiem jest istniejący przodek PONIŻEJ litery dysku: kopia na nośniku, którego
    nie ma (litera bez udziału), nie ma żadnego - więc `failed`, a nie `missing`."""
    if os.name != "nt":
        pytest.skip("litery dysków istnieją tylko na Windows")
    litera = next((c for c in "QJKLMNOPWXYZ" if not os.path.exists(f"{c}:\\")), None)
    if litera is None:
        pytest.skip("brak wolnej litery dysku")
    root, a, b = _dwie_kopie(tmp_path)
    con = _baza_sprzed_0021(tmp_path, [a, b])
    obca = f"{litera}:\\ASTRO_\\LIGHTS\\NOC\\m.xisf"
    repo.add_location(con, frame_id=_loc(con, a)["frame_id"], volume="V", path=obca,
                      header_hash=_loc(con, a)["header_hash"], now=NOW)
    s = scan.backfill_copy_facts(con, now=NOW)
    assert (s.written, s.missing, s.failed, s.remaining) == (2, 0, 1, 1)
    assert s.failed_paths[0].startswith(obca)
    con.close()


# ═════════════════════════ kandydaci, których uzupełnienie nie dogoni


def _operacja(con, lid, phase):
    """Wiersz dziennika zapisu w miejscu (0022) w zadanej fazie - stan izolacji wprost w tabeli."""
    con.execute(
        "INSERT INTO inplace_op(location_id, kind, fmt, region_offset, region_length, old_region_z, "
        "new_region_z, write_start, write_end, file_size, file_ino, pre_hash, post_hash, phase, "
        "started_at) VALUES (?, 'commit', 'xisf', 0, 2, x'00', x'00', 0, 1, 10, 1, 'a', 'b', ?, ?)",
        (lid, phase, NOW))
    con.commit()


def test_kopia_nieczytelna_nie_jest_kandydatem_a_fakty_przynosi_jej_skan(tmp_path):
    """Kopia, która była czytelna i przestała, zachowuje `header_hash` z ostatniego udanego odczytu -
    warunek na odcisk jej NIE odcina. Odcina ją marker `unreadable_since`: uzupełnienie i tak by
    jej nie przeczytało, a w Porządkach świeciłaby „?" bez końca. Fakty przynosi skan - brama
    przyrostowa nie pomija kopii z markerem, a udany odczyt zapisuje fakty i gasi marker."""
    root, a, b = _dwie_kopie(tmp_path)
    con = _baza_sprzed_0021(tmp_path, [a, b])
    lb = _loc(con, b)
    sha1 = con.execute("SELECT sha1_data FROM frame WHERE id = ?", (lb["frame_id"],)).fetchone()[0]
    assert repo.refresh_location_unreadable(
        con, location_id=lb["id"], sha1_data=sha1, path=str(b), mtime=lb["mtime"],
        reason="OSError: test", kind="io", now=NOW)
    assert _loc(con, b)["header_hash"] is not None
    assert [r["path"] for r in scan.copy_facts_candidates(con)] == [str(a)]
    s = scan.backfill_copy_facts(con, now=NOW)
    assert (s.rows, s.written, s.failed, s.remaining) == (1, 1, 0, 0)
    assert not scan._already_scanned(con, "V", str(b), lb["mtime"])
    scan.ingest_record(con, scan.scan_file(str(b)), volume="V", now=NOW,
                       summary=scan.ScanSummary())
    lb = _loc(con, b)
    assert lb["unreadable_since"] is None and lb["hdr_hash"] == lb["header_hash"]
    assert lb["hdr_filter"] == "L-Pro"
    con.close()


@pytest.mark.parametrize("faza", repo.INPLACE_ISOLATING_PHASES)
def test_kopia_izolowana_nie_jest_kandydatem_do_zamkniecia_operacji(tmp_path, faza):
    """Kopia izolowana po zapisie w miejscu (każda faza izolująca, także `written`) wypada
    z kandydatów - żadna droga czytająca jej nie dotyka, więc „?" świeciłoby bez końca. Operacja
    zamknięta (tu: zwolniona) nie izoluje: kopia bez faktów wraca do kandydatów sama."""
    root, a, b = _dwie_kopie(tmp_path)
    con = _baza_sprzed_0021(tmp_path, [a, b])
    _operacja(con, _loc(con, b)["id"], faza)
    assert [r["path"] for r in scan.copy_facts_candidates(con)] == [str(a)]
    s = scan.backfill_copy_facts(con, now=NOW)
    assert (s.rows, s.written, s.failed, s.remaining) == (1, 1, 0, 0)
    assert _loc(con, b)["hdr_hash"] is None
    con.execute("UPDATE inplace_op SET phase = 'released'")
    con.commit()
    assert [r["path"] for r in scan.copy_facts_candidates(con)] == [str(b)]
    con.close()


def test_izolacja_kopii_na_innym_woluminie_nie_blokuje_tej_samej_sciezki(tmp_path):
    """Izolacja dotyczy kopii (wolumin + ścieżka), nie samej ścieżki: operacja w toku na kopii
    woluminu `W` nie blokuje odczytu kopii woluminu `V` pod tą samą ścieżką. Falsyfikator: bramka
    `_isolated(con, path)` bez woluminu → kopia `V` ląduje w `failed` jako „izolowana"."""
    root, a, b = _dwie_kopie(tmp_path)
    con = _baza_sprzed_0021(tmp_path, [a, b])
    la = _loc(con, a)
    lid_w, _ = repo.add_location(con, frame_id=la["frame_id"], volume="W", path=str(a),
                                 header_hash=la["header_hash"], now=NOW)
    _operacja(con, lid_w, "writing")
    assert scan._isolated(con, str(a)) and not scan._isolated(con, str(a), "V")
    s = scan.backfill_copy_facts(con, now=NOW)
    assert (s.rows, s.written, s.failed, s.failed_paths, s.remaining) == (2, 2, 0, [], 0)
    wiersze = dict(con.execute("SELECT volume, hdr_hash FROM location WHERE path = ?",
                               (str(a),)).fetchall())
    assert wiersze["V"] == la["header_hash"] and wiersze["W"] is None
    con.close()


def test_uzupelnienie_xisf_izolacja_na_innym_woluminie_nie_blokuje_tej_samej_sciezki(tmp_path):
    """Lustro testu wyżej dla sterownika `backfill_xisf_headers`: kopia XISF sprzed P6a (bez
    odcisku) na woluminie `V` jest czytana i dostaje odcisk, choć kopia pod TĄ SAMĄ ścieżką na
    woluminie `W` ma operację zapisu w miejscu w toku; ta druga zostaje w `failed` jako izolowana.
    Falsyfikator: bramka `_isolated(con, path)` bez woluminu → kopia `V` też ląduje w `failed`."""
    a = _xisf(tmp_path / "ARCH" / "A" / "m.xisf", _FLAT + (("FILTER", "'CLS'"),))
    con = db.open_db(str(tmp_path / "h.db"))
    rec = scan.scan_file(str(a))
    fid, _ = repo.upsert_frame(con, sha1_data=rec.sha1_data, kind="master_flat",
                               filetype="xisf", camera_id=None, now=NOW)
    lid_v, _ = repo.add_location(con, frame_id=fid, volume="V", path=str(a), mtime=rec.mtime,
                                 now=NOW)
    lid_w, _ = repo.add_location(con, frame_id=fid, volume="W", path=str(a), now=NOW)
    _operacja(con, lid_w, "writing")
    s = scan.backfill_xisf_headers(con, now=NOW)
    assert (s.rows, s.read, s.failed) == (2, 1, 1), s
    assert "izolowana" in s.failed_paths[0]
    wiersze = dict(con.execute("SELECT volume, header_hash FROM location WHERE path = ?",
                               (str(a),)).fetchall())
    assert wiersze["V"] == rec.header_hash and wiersze["W"] is None
    con.close()


def test_uzupelnienie_zawezone_do_korzenia(tmp_path):
    """Korzeń dostawy zawęża kandydatów - „Przetwórz wszystko" na wskazanym katalogu nie czyta
    plików spoza niego (jak pass obecności)."""
    root, a, b = _dwie_kopie(tmp_path)
    con = _baza_sprzed_0021(tmp_path, [a, b])
    assert [r["path"] for r in scan.copy_facts_candidates(con, root / "A_CLS")] == [str(a)]
    s = scan.backfill_copy_facts(con, now=NOW, root=root / "A_CLS")
    assert (s.written, s.remaining) == (1, 0)
    assert _loc(con, b)["hdr_hash"] is None
    con.close()


# ═════════════════════════ predykat z samego stanu


def _kopia(lid, **pola):
    row = {"location_id": lid, "frame_id": 1, "path": f"/{lid}", "image_count": 1,
           "image_roles": '["integration"]', "hdr_filter": "Ha", "hdr_imagetyp": "Master Flat",
           "hdr_object": None, "hdr_telescop": "RC8", "hdr_instrume": "ZWO", "hdr_exptime": 1.34,
           "hdr_xbinning": 1, "hdr_date_obs": "2024-08-25T16:49:18", "hdr_hash": f"h{lid}",
           "hdr_rule": COPY_TESTIMONY_RULE}
    row.update(pola)
    return row


def test_rozjazd_kopii_z_samego_stanu():
    """`copy_divergence`: zgodne kopie → {}; rozbieżne pole przypięte do KAŻDEJ kopii (każda pokaże
    własną wartość); wartość obok braku JEST rozjazdem; liczba i role obrazów to jedna etykieta;
    kopia bez zebranego zeznania nie mówi „inaczej" - mówi „nie wiem" i wypada z porównania."""
    assert queries.copy_divergence([_kopia(1), _kopia(2)]) == {}
    r = queries.copy_divergence([_kopia(1, hdr_filter="CLS"), _kopia(2, hdr_filter="L-Pro")])
    assert r == {1: ("FILTER",), 2: ("FILTER",)}
    r = queries.copy_divergence([_kopia(1, hdr_object="M31"), _kopia(2)])
    assert r == {1: ("OBJECT",), 2: ("OBJECT",)}
    r = queries.copy_divergence([_kopia(1, image_count=3, image_roles='["a", "b", "c"]'),
                                 _kopia(2)])
    assert r == {1: (queries.COPY_IMAGES,), 2: (queries.COPY_IMAGES,)}
    nieznana = _kopia(2, hdr_filter=None, hdr_hash=None)
    assert queries.copy_divergence([_kopia(1), nieznana]) == {}
    trzy = [_kopia(1), _kopia(2), _kopia(3, hdr_exptime=0.2)]
    assert set(queries.copy_divergence(trzy)) == {1, 2, 3}


def test_predykat_porzadkow_podzbior_duplikatow(tmp_path):
    """`copy_conflict_frame_ids` bierze kandydatów z `dup_frame_ids`, więc guardy żywotności są te
    same: klatka wycofana (plik wrócił, dwie niezgodne kopie) do listy niezgodnych NIE trafia, bo
    nie ma jej na liście „Duplikaty" - jej robotą jest werdykt ręki."""
    root, a, b = _dwie_kopie(tmp_path)
    zgodna_a = _xisf(root / "Z1" / "z.xisf", _FLAT, payload=b"\x06" * 32)
    zgodna_b = _xisf(root / "Z2" / "z.xisf", _FLAT, payload=b"\x06" * 32)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    niezgodna = _loc(con, a)["frame_id"]
    zgodna = _loc(con, zgodna_a)["frame_id"]
    assert _loc(con, zgodna_b)["frame_id"] == zgodna
    assert queries.dup_frame_ids(con) == {niezgodna, zgodna}
    assert queries.copy_conflict_frame_ids(con) == {niezgodna}
    assert queries.tasks_state(con)["copy_conflict_frames"] == 1
    # Stan „wycofana, a plik wrócił" wprost w tabeli (klinga wycofania wymaga braku obecnej kopii,
    # a do tego stanu prowadzi dopiero powrót plików) - pytamy predykat, nie drogę do stanu.
    con.execute("UPDATE frame SET retired_at = ? WHERE id = ?", (NOW, niezgodna))
    assert queries.copy_conflict_frame_ids(con) == set()
    con.close()


# ═════════════════════════ wersja reguły koercji (0025, AR-33)


def test_regula_koercji_przypieta_do_numeru():
    """TRIPWIRE AR-33: rzut `copy_testimony` na próbkach, które rozróżniają warianty koercji
    (XISF-owy tekst liczby, `''`, biała spacja, zero i liczba w polu tekstowym, śmieć w polu
    liczbowym), jest przypięty do `COPY_TESTIMONY_RULE`. Zmiana `_to_text`/`_to_float`/`_to_int` albo
    doboru pól, która zmienia którąkolwiek wartość lub typ, czerwieni ten test - naprawą jest
    PODNIESIENIE numeru reguły (sterownik dociągnie stare kopie) razem z nowymi oczekiwaniami, nie
    samo przepisanie oczekiwań. Typ sprawdzany osobno, bo `300 == 300.0`.

    Falsyfikator: każ `_to_text` zdejmować białe znaki → pierwsza próbka pada."""
    assert COPY_TESTIMONY_RULE == 1
    pusto = dict.fromkeys(("hdr_filter", "hdr_imagetyp", "hdr_object", "hdr_telescop",
                           "hdr_instrume", "hdr_exptime", "hdr_xbinning", "hdr_date_obs"))
    probki = [
        ({"FILTER": "CLS ", "IMAGETYP": "Master Flat", "OBJECT": "M 31", "TELESCOP": "RC8",
          "INSTRUME": "ZWO", "EXPTIME": "1.34", "XBINNING": "1.0",
          "DATE-OBS": "2024-08-25T16:49:18"},
         {"hdr_filter": "CLS ", "hdr_imagetyp": "Master Flat", "hdr_object": "M 31",
          "hdr_telescop": "RC8", "hdr_instrume": "ZWO", "hdr_exptime": 1.34, "hdr_xbinning": 1,
          "hdr_date_obs": "2024-08-25T16:49:18"}),
        ({"FILTER": "", "IMAGETYP": 0, "INSTRUME": 100, "EXPTIME": 300, "XBINNING": 2},
         dict(pusto, hdr_imagetyp="0", hdr_instrume="100", hdr_exptime=300.0, hdr_xbinning=2)),
        ({"EXPTIME": "abc", "XBINNING": "x", "OBJECT": None}, pusto),
    ]
    for naglowek, oczekiwane in probki:
        wynik = copy_testimony(naglowek)
        assert wynik == oczekiwane, naglowek
        assert {k: type(v) for k, v in wynik.items()} == {
            k: type(v) for k, v in oczekiwane.items()}, naglowek


def test_kazdy_zapis_faktow_stempluje_biezaca_regule(tmp_path):
    """Trzech pisarzy faktów kopii - dodanie (skan nowej kopii), odświeżenie (skan po zmianie
    nagłówka) i uzupełnienie (sterownik) - stempluje `hdr_rule` bieżącą regułą tym samym zapisem
    co fakty. Falsyfikator: zdejmij `facts["hdr_rule"]` z `copy_header_facts` → klinga odbija
    kotwicę bez reguły (ValueError), a bez strażnika - pierwsza asercja widzi NULL."""
    root, a, b = _dwie_kopie(tmp_path)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    assert (_loc(con, a)["hdr_rule"], _loc(con, b)["hdr_rule"]) == (COPY_TESTIMONY_RULE,) * 2
    _xisf(a, _FLAT + (("FILTER", "'CLX'"),), images=({"imageType": "MasterFlat"},))
    scan.scan_tree(con, root, volume="?", now="2026-09-26T13:00:00+00:00")
    assert (_loc(con, a)["hdr_filter"], _loc(con, a)["hdr_rule"]) == ("CLX", COPY_TESTIMONY_RULE)
    con.close()
    (tmp_path / "u").mkdir()
    con = _baza_sprzed_0021(tmp_path / "u", [a, b])
    assert _loc(con, a)["hdr_rule"] is None
    assert scan.backfill_copy_facts(con, now=NOW).written == 2
    assert (_loc(con, a)["hdr_rule"], _loc(con, b)["hdr_rule"]) == (COPY_TESTIMONY_RULE,) * 2
    con.close()


def test_regula_nieznana_jest_kandydatem_i_dociaga_sam_stempel(tmp_path):
    """Kopia z faktami, ale bez numeru reguły (stan „reguła nieznana") jest kandydatem uzupełnienia
    i wypada z porównania kopii; dociągnięcie tą samą regułą zmienia WYŁĄCZNIE stempel - payload
    `location.refreshed` niesie samo przejście `hdr_rule`. Falsyfikator: wróć w kandydatach do
    `hdr_hash IS NULL` → kopia nie jest kandydatem."""
    root, a, b = _dwie_kopie(tmp_path)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    fid = _loc(con, a)["frame_id"]
    assert queries.copy_conflict_frame_ids(con) == {fid}         # CLS vs L-Pro, obie reguły 1
    con.execute("UPDATE location SET hdr_rule = NULL WHERE path = ?", (str(a),))
    con.commit()
    assert [r["path"] for r in scan.copy_facts_candidates(con)] == [str(a)]
    assert queries.copy_conflict_frame_ids(con) == set()         # „nie wiem", nie „inaczej"
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    s = scan.backfill_copy_facts(con, now=NOW)
    assert (s.rows, s.written, s.remaining) == (1, 1, 0)
    payload = json.loads(con.execute(
        "SELECT payload FROM event WHERE id > ? AND verb = 'location.refreshed'", (ev,)).fetchone()[0])
    assert payload == {"hdr_rule": {"before": None, "after": COPY_TESTIMONY_RULE}}
    assert queries.copy_conflict_frame_ids(con) == {fid}
    con.close()


def test_zmiana_reguly_dociaga_stare_kopie_bez_falszywego_rozjazdu(tmp_path, monkeypatch):
    """Symulacja zmiany koercji (AR-33): binarka podnosi regułę do 2 i rzuca FILTER inaczej (tu:
    małymi literami). Dwie ZGODNE kopie zebrane regułą 1 stają się kandydatami; po dociągnięciu
    jednej z nich (korzeń zawężony) druga zostaje przy starym rzucie - bez stempla porównanie
    widziałoby FILTER `cls` obok `CLS`, czyli rozjazd, którego w plikach nie ma. Po pełnym
    przebiegu obie mówią nową regułą i są zgodne. Fakty nowszej reguły nie dają się cofnąć zapisem
    starszej (binarka starsza od bazy).

    Falsyfikator: zdejmij warunek `hdr_rule` z `copy_divergence` → pierwsze `copy_conflict_frame_ids`
    po częściowym przebiegu zwraca klatkę."""
    root = tmp_path / "ARCH"
    a = _xisf(root / "A" / "z.xisf", _FLAT + (("FILTER", "'CLS'"),))
    b = _xisf(root / "B" / "z.xisf", _FLAT + (("FILTER", "'CLS'"),))
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    assert scan.copy_facts_candidates(con) == [] and queries.copy_conflict_frame_ids(con) == set()
    stary = dict(_loc(con, a))

    stara_koercja = scan.copy_testimony
    monkeypatch.setattr(scan, "copy_testimony",
                        lambda h: dict(stara_koercja(h), hdr_filter=stara_koercja(h)["hdr_filter"].lower()))
    monkeypatch.setattr(scan, "COPY_TESTIMONY_RULE", 2)
    monkeypatch.setattr(queries, "COPY_TESTIMONY_RULE", 2)
    monkeypatch.setattr(headers, "COPY_TESTIMONY_RULE", 2)     # `copy_facts_state` (AR-33)
    assert {r["path"] for r in scan.copy_facts_candidates(con)} == {str(a), str(b)}
    s = scan.backfill_copy_facts(con, now=NOW, root=root / "A")
    assert (s.written, s.remaining) == (1, 0)
    assert (_loc(con, a)["hdr_filter"], _loc(con, a)["hdr_rule"]) == ("cls", 2)
    assert (_loc(con, b)["hdr_filter"], _loc(con, b)["hdr_rule"]) == ("CLS", 1)
    assert queries.copy_conflict_frame_ids(con) == set()
    s = scan.backfill_copy_facts(con, now=NOW)
    assert (s.rows, s.written, s.remaining) == (1, 1, 0)
    assert queries.copy_conflict_frame_ids(con) == set()
    assert scan.backfill_copy_facts(con, now=NOW).rows == 0
    monkeypatch.undo()

    stare_fakty = {k: stary[k] for k in repo.COPY_FACTS}
    assert repo.record_copy_facts(con, location_id=stary["id"], copy_facts=stare_fakty,
                                  now=NOW) is False
    assert _loc(con, a)["hdr_rule"] == 2
    con.close()


def test_przebieg_uzupelnienia_jedno_zdarzenie_zbiorcze(tmp_path):
    """AR-32: jeden przebieg `backfill_copy_facts` = JEDEN `location.copy_facts_summary` z polami
    równymi zwróconemu `CopyFactsSummary` (z odmowami i ich ścieżkami), OBOK per-lokacyjnych
    `location.refreshed` (te zostają - tylko one niosą `{before, after}` jednej kopii). Przebieg bez
    kandydatów nie zostawia zdarzenia. Falsyfikator: usuń wołanie `flag_copy_facts_summary` →
    licznik zdarzeń zbiorczych 0."""
    from dataclasses import asdict
    root, a, b = _dwie_kopie(tmp_path)
    con = _baza_sprzed_0021(tmp_path, [a, b])
    _xisf(b, _FLAT + (("FILTER", "'CLX'"),), images=({"id": "integration"},))   # b → stale
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    s = scan.backfill_copy_facts(con, now=NOW)
    assert (s.rows, s.written, s.stale, s.stale_paths, s.remaining) == (2, 1, 1, [str(b)], 1)
    zdarzenia = con.execute("SELECT verb, actor, target, payload FROM event WHERE id > ? "
                            "ORDER BY id", (ev,)).fetchall()
    assert [z["verb"] for z in zdarzenia] == ["location.refreshed", "location.copy_facts_summary"]
    zbiorcze = zdarzenia[-1]
    assert (zbiorcze["actor"], zbiorcze["target"]) == ("backfill:copies", "location:*")
    assert json.loads(zbiorcze["payload"]) == asdict(s)
    scan.scan_tree(con, root, volume="V", now="2026-09-26T13:00:00+00:00")   # skan dogania b
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    assert scan.backfill_copy_facts(con, now=NOW).rows == 0
    assert con.execute("SELECT count(*) FROM event WHERE id > ? "
                       "AND verb = 'location.copy_facts_summary'", (ev,)).fetchone()[0] == 0
    con.close()


# ═════════════════════════ stan faktów wobec reguły: jedno miejsce prawdy (AR-33)

_R = COPY_TESTIMONY_RULE
# Fragmenty SQL reguły - ZNAK W ZNAK te z literałów modułów (sprawdza `test_fragmenty_sql_...`):
# fragment, parametry dla reguły `r`, oczekiwanie wobec stanu z `copy_facts_state`.
_FRAGMENTY = {
    "queries.py": ("(l.hdr_hash IS NULL OR l.hdr_rule IS NOT ?)", lambda r: (r,),
                   lambda st: st != headers.FAKTY_BIEZACE),
    "scan.py:sterownik": ("(l.hdr_hash IS NULL OR l.hdr_rule IS NULL OR l.hdr_rule < ? "
                          "OR l.hdr_rule > ?)", lambda r: (r, None),
                          lambda st: st == headers.FAKTY_DO_DOCIAGNIECIA),
    "scan.py:licznik": ("(l.hdr_hash IS NULL OR l.hdr_rule IS NULL OR l.hdr_rule < ? "
                        "OR l.hdr_rule > ?)", lambda r: (r, r),
                        lambda st: st != headers.FAKTY_BIEZACE),
    "repo.py": ("(hdr_hash IS NULL OR hdr_rule IS NULL OR hdr_rule < ?)", lambda r: (r,),
                lambda st: st == headers.FAKTY_DO_DOCIAGNIECIA),
}


def test_fragmenty_sql_zgodne_z_copy_facts_state():
    """Z10: trzy komparatory jednej reguły (`==`, `<`, `>=`) rozjeżdżały się na regule NOWSZEJ niż
    kod. Każdy fragment SQL siedzi w swoim module znak w znak i na pełnej tabeli prawdy (brak
    faktów, reguła nieznana, starsza, bieżąca, nowsza) mówi to samo co `copy_facts_state`.
    Falsyfikator: zmień w module fragment (np. `>=` w miejsce `IS NOT`) → pierwsza albo druga
    asercja pada."""
    import re
    pkg = Path(headers.__file__).resolve().parents[1]
    zrodla = {"queries.py": pkg / "gui" / "queries.py", "scan.py": pkg / "scan.py",
              "repo.py": pkg / "repo.py"}
    mem = sqlite3.connect(":memory:")
    regula = 2                                   # reguła > 1, żeby istniała też „starsza”
    przypadki = [(None, None), ("h", None), ("h", 1), ("h", 2), ("h", 3)]
    for klucz, (fragment, parametry, oczekiwane) in _FRAGMENTY.items():
        tekst = re.sub(r'"\s*"', "", zrodla[klucz.split(":")[0]].read_text(encoding="utf-8"))
        assert re.sub(r"\s+", " ", fragment) in re.sub(r"\s+", " ", tekst), klucz
        sql = fragment.replace("l.", "")
        for hh, rr in przypadki:
            wynik = mem.execute(
                f"WITH t(hdr_hash, hdr_rule) AS (SELECT ?, ?) SELECT {sql} FROM t",
                (hh, rr, *parametry(regula))).fetchone()[0]
            stan = headers.copy_facts_state(hh, rr, rule=regula)
            assert bool(wynik) == oczekiwane(stan), (klucz, hh, rr, stan)
    mem.close()


def test_regula_nowsza_niz_kod_jest_w_liczniku_nie_wiem_ale_nie_w_sterowniku(tmp_path):
    """Z10: kopia z faktami reguły nowszej niż kod (baza pisana nowszą binarką) jest w read-modelu
    „nie wiem” - więc licznik „?” Porządków (`porownywalne=True`) ją widzi; sterownik jej NIE
    dociąga i nie nadpisuje (starsza binarka niczego nie cofa).
    Falsyfikator: wróć w kandydatach do samego `hdr_rule < ?` → licznik pusty."""
    root, a, b = _dwie_kopie(tmp_path)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    con.execute("UPDATE location SET hdr_rule = ?, hdr_filter = 'NOWY' WHERE path = ?",
                (_R + 1, str(a)))
    con.commit()
    assert [r["path"] for r in scan.copy_facts_candidates(con, porownywalne=True)] == [str(a)]
    assert scan.copy_facts_candidates(con) == []
    assert scan.backfill_copy_facts(con, now=NOW).rows == 0
    assert (_loc(con, a)["hdr_rule"], _loc(con, a)["hdr_filter"]) == (_R + 1, "NOWY")
    con.close()


def _podmien_wiersz_przy_odczycie(monkeypatch, con, sciezka, *, odcisk_wiersza, odcisk_odczytu=None):
    """Przy odczycie `sciezka` ktoś inny (skan) wpisuje do wiersza fakty bieżącej reguły
    z odciskiem `odcisk_wiersza` (None = odcisk pliku); `odcisk_odczytu` podmienia odcisk NASZEGO
    pierwszego odczytu (odczyt starszy niż wiersz)."""
    prawdziwa = scan._read_meta
    stan = {"n": 0}

    def _przeplot(p, *aa, **kw):
        wynik = list(prawdziwa(p, *aa, **kw))
        if str(p) == str(sciezka):
            stan["n"] += 1
            odcisk = odcisk_wiersza or wynik[2]
            con.execute("UPDATE location SET header_hash = ?, hdr_hash = ?, hdr_rule = ? "
                        "WHERE path = ?", (odcisk, odcisk, _R, str(sciezka)))
            con.commit()
            if odcisk_odczytu is not None and stan["n"] == 1:
                wynik[2] = odcisk_odczytu
        return tuple(wynik)
    monkeypatch.setattr(scan, "_read_meta", _przeplot)
    return stan


def test_fakty_sa_ale_naglowek_inny_niz_wiersz_to_stale_nie_elsewhere(tmp_path, monkeypatch):
    """Z11: fakty bieżącej reguły zebrane dla nagłówka, którego na dysku już nie ma (plik zmieniony
    poza programem) - prawdą jest „zmieniona od skanu”, nie „zebrane gdzie indziej”.
    Falsyfikator: wróć do `_fakty_kopii_sa` przed porównaniem odcisku → `elsewhere == 1`."""
    root, a, b = _dwie_kopie(tmp_path)
    con = _baza_sprzed_0021(tmp_path, [a])
    stan = _podmien_wiersz_przy_odczycie(monkeypatch, con, a, odcisk_wiersza="INNY")
    s = scan.backfill_copy_facts(con, now=NOW)
    monkeypatch.undo()
    assert (s.read, s.written, s.elsewhere, s.stale, s.stale_paths) == (1, 0, 0, 1, [str(a)]), s
    assert stan["n"] == 2                                  # jedno ponowienie odczytu, nie więcej
    con.close()


def test_odczyt_starszy_od_wiersza_z_faktami_to_elsewhere(tmp_path, monkeypatch):
    """Wyścig, który ponowienie odsiewa: NASZ pierwszy odczyt jest starszy od wiersza (skan wpisał
    nowszy nagłówek razem z faktami). Drugi odczyt zgadza się z wierszem → `elsewhere`, nie `stale`."""
    root, a, b = _dwie_kopie(tmp_path)
    con = _baza_sprzed_0021(tmp_path, [a])
    _podmien_wiersz_przy_odczycie(monkeypatch, con, a, odcisk_wiersza=None, odcisk_odczytu="STARY")
    s = scan.backfill_copy_facts(con, now=NOW)
    monkeypatch.undo()
    assert (s.read, s.written, s.elsewhere, s.stale) == (1, 0, 1, 0), s
    con.close()


def test_odswiezenie_lokacji_nie_cofa_faktow_nowszej_reguly(tmp_path):
    """Z12: re-odczyt kopii starszą binarką (fakty reguły R) przy wierszu z faktami reguły R+1
    i TYM SAMYM nagłówku zostawia fakty wiersza - reszta odświeżenia (mtime) idzie normalnie.
    Po zmianie nagłówka fakty wiersza opisują plik, którego nie ma: wtedy wchodzą fakty
    wołającego (jedyna prawda o nowym nagłówku).
    Falsyfikator: zdejmij `zachowaj` w `refresh_location` → `hdr_rule == R` po pierwszym skanie."""
    root, a, b = _dwie_kopie(tmp_path)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    con.execute("UPDATE location SET hdr_rule = ?, hdr_filter = 'NOWY' WHERE path = ?",
                (_R + 1, str(a)))
    con.commit()
    przed = dict(_loc(con, a))
    t = os.stat(a).st_mtime + 100
    os.utime(a, (t, t))
    scan.scan_tree(con, root, volume="?", now="2026-09-26T13:00:00+00:00")
    po = _loc(con, a)
    assert po["mtime"] != przed["mtime"]                                  # odświeżenie poszło
    assert (po["hdr_rule"], po["hdr_filter"], po["hdr_hash"]) == (_R + 1, "NOWY", przed["hdr_hash"])

    _xisf(a, _FLAT + (("FILTER", "'CLX'"),), images=({"imageType": "MasterFlat"},))
    scan.scan_tree(con, root, volume="?", now="2026-09-26T14:00:00+00:00")
    po = _loc(con, a)
    assert po["header_hash"] != przed["header_hash"] and po["hdr_hash"] == po["header_hash"]
    assert (po["hdr_rule"], po["hdr_filter"]) == (_R, "CLX")
    con.close()
