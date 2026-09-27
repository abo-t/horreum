"""Fakty KOPII z jej nagłówka (migracja 0021): liczba i role obrazów, zeznanie pól osi, kotwica
`hdr_hash` - od czytnika XISF, przez klingę kopii i skan, po uzupełnienie wierszy sprzed migracji
i predykat „kopie jednej klatki mówią różnie" liczony z samego stanu.

Pliki syntetyczne w `tmp_path` (zero archiwum, zero żywej bazy). Pomiar na kopii żywej bazy nie
mieszka w teście - bazy prywatnej w repo publicznym nie ma i mieć nie może."""
import json
import os
import sqlite3
import struct

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, repo, scan
from horreum.gui import queries

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
    assert (f["image_count"], json.loads(f["image_roles"]), f["hdr_hash"]) == (
        2, ["integration", None], rec.header_hash)
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
    obce.update(hdr_filter="Ha", hdr_hash="INNY")
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
           "hdr_xbinning": 1, "hdr_date_obs": "2024-08-25T16:49:18", "hdr_hash": f"h{lid}"}
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
