"""ZEZNANIE Z NIEOBECNEJ KOPII (AR-5): predykat stanu `queries.orphan_testimony_copies`, etap
przejęcia zeznania ocalałej kopii `scan.adopt_orphan_testimony` z klingą `repo.adopt_testimony`,
wpięcie w łańcuch „Przyjmij nowe" i wiersz Porządków z perspektywą w Zbiorach.

Scenariusz jest kopią realnego przypadku z archiwum (masterflat RC8_2600MC): jedna klatka, dwie
kopie o tych samych pikselach - pierwsza wjechała kopia L-Pro (więc to jej głos niesie `header`),
druga mówi CLS. Użytkownik kasuje kopię L-Pro, pass obecności zdejmuje jej obecność, a `header`
dalej mówi L-Pro. Pliki syntetyczne w `tmp_path` - zero archiwum, zero żywej bazy."""
import json
import os

import pytest

from horreum import db, repo, scan
from horreum.gui import queries
from horreum.resolve.filters import normalize_filter
from horreum.resolver import run_resolver

from test_copy_facts import NOW, _xisf

LATER = "2026-09-26T13:00:00+00:00"
_MASTER = (("IMAGETYP", "'Master Flat'"), ("INSTRUME", "'ZWO ASI2600MC Pro'"),
           ("XBINNING", "1"), ("TELESCOP", "'RC8'"), ("DATE-OBS", "'2022-09-01T04:17:19'"))


def _lpro(root, payload=b"\x05" * 32):
    return _xisf(root / "A_LPRO" / "m.xisf",
                 _MASTER + (("FILTER", "'L-Pro'"), ("OBJECT", "'FlatWizard'"), ("EXPTIME", "0.2")),
                 payload=payload)


def _cls(root, payload=b"\x05" * 32, sub="B_CLS"):
    return _xisf(root / sub / "m.xisf",
                 _MASTER + (("FILTER", "'CLS'"), ("OBJECT", "'NGC 6888'"), ("EXPTIME", "0.205")),
                 payload=payload)


def _loc(con, path):
    return con.execute("SELECT * FROM location WHERE path = ?", (str(path),)).fetchone()


def _header(con, fid):
    return con.execute("SELECT * FROM header WHERE frame_id = ?", (fid,)).fetchone()


def _zniknij(con, path):
    """Stan po skasowaniu pliku i passie obecności: plik fizycznie znika, kopia `present = 0`
    przez JEDYNĄ klingę zdejmowania obecności (dowód nieobecności zbiera tu test, nie `presence`)."""
    lid = _loc(con, path)["id"]
    os.remove(path)
    assert repo.mark_location_vanished(con, location_id=lid, expected_path=str(path),
                                       root=str(path.parent), run_id="t", now=NOW)


@pytest.fixture
def po_skasowaniu(tmp_path):
    """Klatka o dwóch kopiach, `header` z kopii L-Pro, kopia L-Pro skasowana i nieobecna."""
    root = tmp_path / "ARCH"
    a, b = _lpro(root), _cls(root)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    fid = _loc(con, a)["frame_id"]
    assert _loc(con, b)["frame_id"] == fid and _header(con, fid)["filter_raw"] == "L-Pro"
    _zniknij(con, a)
    yield con, root, fid, a, b
    con.close()


# ═════════════════════════ predykat stanu


def test_predykat_zeznanie_z_nieobecnej_kopii(po_skasowaniu):
    """Po zniknięciu kopii-źródła `header` nie zgadza się z JEDYNĄ obecną kopią → predykat ją
    zwraca, a „Kopie niezgodne ze sobą" (porównują wyłącznie obecne) jej nie widzą - dokładnie
    ta niewidoczność była długiem AR-5. Jedna obecna kopia to robota etapu, ale etap chodzi tylko
    pod swoim korzeniem - wiersz Porządków liczy ją też, żeby nie czekała niewidoczna."""
    con, _root, fid, _a, b = po_skasowaniu
    kopie = queries.orphan_testimony_copies(con)
    assert list(kopie) == [fid] and [k["location_id"] for k in kopie[fid]] == [_loc(con, b)["id"]]
    assert queries.copy_conflict_frame_ids(con) == set()
    assert queries.orphan_testimony_frame_ids(con) == {fid}
    assert [f for f, _k in scan.adopt_candidates(con)] == [fid]


def test_predykat_milczy_przy_zgodzie_braku_faktow_i_braku_obecnych(tmp_path):
    """Trzy „nie": zeznanie zgodne z obecną kopią (nic nie zniknęło); kopia obecna bez zebranych
    faktów (`hdr_hash` NULL - „nie wiem", a mogła być źródłem `header`); klatka bez żadnej obecnej
    kopii (to robota „Zniknięte", nie przejęcia)."""
    root = tmp_path / "ARCH"
    a, b = _lpro(root), _cls(root)
    solo = _xisf(root / "S" / "s.xisf", _MASTER + (("FILTER", "'Ha'"),), payload=b"\x07" * 32)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    assert queries.orphan_testimony_copies(con) == {}          # obie obecne, header = kopia L-Pro
    _zniknij(con, solo)
    assert queries.orphan_testimony_copies(con) == {}          # brak obecnej kopii
    _zniknij(con, a)
    con.execute("UPDATE location SET hdr_filter = NULL, hdr_imagetyp = NULL, hdr_object = NULL, "
                "hdr_telescop = NULL, hdr_instrume = NULL, hdr_exptime = NULL, "
                "hdr_xbinning = NULL, hdr_date_obs = NULL, image_count = NULL, "
                "image_roles = NULL, hdr_hash = NULL WHERE path = ?", (str(b),))
    con.commit()
    assert queries.orphan_testimony_copies(con) == {}          # ocalała bez faktów - „nie wiem"
    con.close()


def test_wiersz_porzadkow_liczy_klatki_z_dwiema_obecnymi_kopiami(tmp_path):
    """Trzy kopie: źródło `header` (L-Pro) znika, dwie ocalałe mówią CLS i OSC. Kopię wiodącą
    wskazuje człowiek (AR-4), więc etap jej NIE dotyka (brak kandydata), a wiersz Porządków ją
    liczy - razem z guardem żywotności (wycofana wypada, jak z „Duplikatów")."""
    root = tmp_path / "ARCH"
    a, b = _lpro(root), _cls(root)
    c = _xisf(root / "C_OSC" / "m.xisf", _MASTER + (("FILTER", "'OSC'"),), payload=b"\x05" * 32)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    fid = _loc(con, a)["frame_id"]
    _zniknij(con, a)
    assert set(queries.orphan_testimony_copies(con)) == {fid}
    assert queries.orphan_testimony_frame_ids(con) == {fid}
    assert queries.tasks_state(con)["orphan_testimony_frames"] == 1
    assert scan.adopt_candidates(con) == []
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    s = scan.adopt_orphan_testimony(con, now=LATER)
    assert (s.rows, s.read, s.adopted) == (0, 0, 0)
    assert _header(con, fid)["filter_raw"] == "L-Pro"
    assert con.execute("SELECT count(*) FROM event WHERE id > ?", (ev,)).fetchone()[0] == 0
    con.execute("UPDATE frame SET retired_at = ? WHERE id = ?", (NOW, fid))
    assert queries.orphan_testimony_frame_ids(con) == set()
    assert _loc(con, b)["present"] == 1 and _loc(con, c)["present"] == 1
    con.close()


# ═════════════════════════ ocalała kopia bez faktów (wiersze sprzed 0021)


def _bez_faktow(con, *paths):
    """Stan kopii sprzed 0021: odcisk nagłówka znany, fakty kopii niezebrane."""
    for p in paths:
        con.execute("UPDATE location SET hdr_filter = NULL, hdr_imagetyp = NULL, hdr_object = NULL, "
                    "hdr_telescop = NULL, hdr_instrume = NULL, hdr_exptime = NULL, "
                    "hdr_xbinning = NULL, hdr_date_obs = NULL, image_count = NULL, "
                    "image_roles = NULL, hdr_hash = NULL WHERE path = ?", (str(p),))
    con.commit()


def test_ocalala_FITS_bez_faktow_dostaje_je_a_potem_przejecie_dziala(tmp_path):
    """Ocalała kopia FITS klatki, której siostra zniknęła, jest kandydatem uzupełnienia faktów, choć
    obecna jest już tylko ona: klatka ma więcej niż jedną lokację OGÓŁEM. Bez tego predykat zeznania
    z nieobecnej kopii milczałby na zawsze („nie wiem" przy jedynej obecnej), a przejęcie nie
    miałoby kandydata. Pojedynczy FITS bez siostry dalej kandydatem NIE jest."""
    from test_copy_facts import _fits
    root = tmp_path / "ARCH"
    a = _fits(root / "A" / "m.fits", "L-Pro", n=3)
    b = _fits(root / "B" / "m.fits", "CLS", n=3)
    solo = _fits(root / "S" / "solo.fits", "Ha", n=4)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    fid = _loc(con, a)["frame_id"]
    assert _loc(con, b)["frame_id"] == fid and _header(con, fid)["filter_raw"] == "L-Pro"
    _bez_faktow(con, a, b, solo)
    _zniknij(con, a)
    assert queries.orphan_testimony_copies(con) == {}          # „nie wiem" - jeszcze bez faktów
    assert [r["path"] for r in scan.copy_facts_candidates(con)] == [str(b)]
    s = scan.backfill_copy_facts(con, now=LATER)
    assert (s.rows, s.written, s.remaining) == (1, 1, 0)
    assert _loc(con, b)["hdr_filter"] == "CLS" and _loc(con, solo)["hdr_hash"] is None
    assert list(queries.orphan_testimony_copies(con)) == [fid]
    a_s = scan.adopt_orphan_testimony(con, now=LATER)
    assert (a_s.rows, a_s.adopted) == (1, 1)
    assert _header(con, fid)["filter_raw"] == "CLS"
    con.close()


def test_plan_karty_OBJECT_pomija_ocalala_kopie_bez_faktow(tmp_path):
    """Plan ujednolicenia karty `OBJECT` nie pisze do ocalałej kopii bez zebranych faktów, gdy
    klatka ma kopię nieobecną: karty klatki mogły przyjść ze skasowanego pliku, a strażnik „kopia
    zeznaje inną kartę" bez faktów jest ślepy. Powód pominięcia mówi, co zrobić. Po uzupełnieniu
    faktów (tu: kopie zgodne) klatka wraca do planu."""
    from horreum import resolver
    from test_writeback_inplace import _fits as _light
    (tmp_path / "A").mkdir()
    (tmp_path / "B").mkdir()
    a = _light(tmp_path / "A" / "veil.fits", obj="NGC6992", seed=1)
    b = _light(tmp_path / "B" / "veil.fits", obj="NGC6992", seed=1)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, tmp_path, volume="?", now=NOW)
    resolver.run_resolver(con, NOW)
    fid = _loc(con, a)["frame_id"]
    _bez_faktow(con, a, b)
    _zniknij(con, a)
    rows = [r for r in queries.object_card_form_rows(con) if r["frame_id"] == fid]
    assert len(rows) == 1 and rows[0]["path"] == str(b)
    assert rows[0]["skip"] == queries.SKIP_COPY_WITHOUT_FACTS
    assert fid not in queries.object_card_form_frame_ids(con)
    scan.backfill_copy_facts(con, now=LATER)
    assert fid in queries.object_card_form_frame_ids(con)
    con.close()


def test_plan_karty_OBJECT_pomija_nieczytelna_kopie_bez_faktow_ktorej_dostawa_nie_czeka(tmp_path):
    """Ocalała kopia bez faktów, która do tego jest oznaczona jako nieczytelna, NIE jest kandydatem
    uzupełnienia (fakty przyniesie jej skan po wyzdrowieniu), a plan ujednolicenia karty `OBJECT`
    dalej ją pomija - z powodem „nieczytelna", nie „najpierw Przyjmij nowe", bo dostawa jej nie
    naprawi. Po udanym odczycie skanem fakty są, marker zgasł i klatka wraca do planu."""
    from horreum import resolver
    from test_writeback_inplace import _fits as _light
    (tmp_path / "A").mkdir()
    (tmp_path / "B").mkdir()
    a = _light(tmp_path / "A" / "veil.fits", obj="NGC6992", seed=1)
    b = _light(tmp_path / "B" / "veil.fits", obj="NGC6992", seed=1)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, tmp_path, volume="?", now=NOW)
    resolver.run_resolver(con, NOW)
    fid = _loc(con, a)["frame_id"]
    _bez_faktow(con, a, b)
    _zniknij(con, a)
    lb = _loc(con, b)
    sha1 = con.execute("SELECT sha1_data FROM frame WHERE id = ?", (fid,)).fetchone()[0]
    assert repo.refresh_location_unreadable(
        con, location_id=lb["id"], sha1_data=sha1, path=str(b), mtime=lb["mtime"],
        reason="OSError: test", kind="io", now=NOW)
    assert scan.copy_facts_candidates(con) == []
    rows = [r for r in queries.object_card_form_rows(con) if r["frame_id"] == fid]
    assert len(rows) == 1 and rows[0]["skip"] == "kopia oznaczona jako nieczytelna"
    scan.ingest_record(con, scan.scan_file(str(b)), volume="?", now=LATER,
                       summary=scan.ScanSummary())
    lb = _loc(con, b)
    assert lb["unreadable_since"] is None and lb["hdr_hash"] == lb["header_hash"]
    assert fid in queries.object_card_form_frame_ids(con)
    con.close()


# ═════════════════════════ etap przejęcia


def test_etap_przejmuje_zeznanie_jedynej_ocalalej_kopii(po_skasowaniu):
    """Jedna ocalała kopia → `header` (pola gorące + raw_json), `cards` i pochodne przechodzą na jej
    głos; ślad `header.adopted` mówi skąd → dokąd. Następny resolve przelicza `filter_canon` z nowego
    zeznania - pochodne liczone po przejęciu, nie z głosu nieobecnego pliku."""
    con, _root, fid, _a, b = po_skasowaniu
    run_resolver(con, NOW)
    assert con.execute("SELECT filter_canon FROM frame WHERE id = ?",
                       (fid,)).fetchone()[0] == normalize_filter("L-Pro")
    s = scan.adopt_orphan_testimony(con, now=LATER)
    assert (s.rows, s.read, s.adopted, s.identity, s.stale, s.failed, s.remaining) == (
        1, 1, 1, 0, 0, 0, 0)
    h = _header(con, fid)
    assert (h["filter_raw"], h["object_raw"], h["exptime"]) == ("CLS", "NGC 6888", 0.205)
    assert json.loads(h["raw_json"])["FILTER"] == "CLS"
    karty = dict(con.execute("SELECT keyword, value_raw FROM cards WHERE frame_id = ? "
                             "AND keyword IN ('FILTER', 'OBJECT')", (fid,)).fetchall())
    assert karty == {"FILTER": "CLS", "OBJECT": "NGC 6888"}
    ev = con.execute("SELECT actor, payload FROM event WHERE verb = 'header.adopted'").fetchall()
    assert len(ev) == 1 and ev[0]["actor"] == "adopt:testimony"
    payload = json.loads(ev[0]["payload"])
    lb = _loc(con, b)
    assert (payload["location_id"], payload["path"], payload["header_hash"]) == (
        lb["id"], str(b), lb["header_hash"])
    assert payload["changed"]["filter_raw"] == {"before": "L-Pro", "after": "CLS"}
    assert payload["changed"]["exptime"] == {"before": 0.2, "after": 0.205}
    assert queries.orphan_testimony_copies(con) == {}
    run_resolver(con, LATER)
    assert con.execute("SELECT filter_canon FROM frame WHERE id = ?",
                       (fid,)).fetchone()[0] == normalize_filter("CLS")


def test_etap_idempotentny_drugi_przebieg_bez_odczytu_dysku(po_skasowaniu, monkeypatch):
    """Po przejęciu predykat jest pusty: drugi przebieg nie ma kandydatów, nie czyta ANI JEDNEGO
    pliku i nie dopisuje ani jednego zdarzenia. Klinga na identycznym zeznaniu też milczy."""
    con, _root, fid, _a, b = po_skasowaniu
    scan.adopt_orphan_testimony(con, now=LATER)
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]

    def _zakaz(_path):
        raise AssertionError("drugi przebieg nie ma prawa czytać dysku")
    monkeypatch.setattr(scan, "scan_file", _zakaz)
    s = scan.adopt_orphan_testimony(con, now=LATER)
    assert (s.rows, s.read, s.adopted, s.remaining) == (0, 0, 0, 0)
    monkeypatch.undo()
    rec = scan.scan_file(str(b))
    assert repo.adopt_testimony(
        con, location_id=_loc(con, b)["id"], sha1_data=rec.sha1_data,
        header_hash=rec.header_hash, raw_json=json.dumps(rec.header, ensure_ascii=False),
        cards=rec.cards, hot_fields=scan.extract_header(rec.header),
        camera_id=con.execute("SELECT camera_id FROM frame WHERE id = ?", (fid,)).fetchone()[0],
        kind=con.execute("SELECT kind FROM frame WHERE id = ?", (fid,)).fetchone()[0],
        now=LATER, actor="test") == "unchanged"
    assert con.execute("SELECT count(*) FROM event WHERE id > ?", (ev,)).fetchone()[0] == 0


def test_etap_odmawia_gdy_plik_niesie_inna_tozsamosc(po_skasowaniu):
    """Pod ścieżką ocalałej kopii leży INNA treść (ten sam nagłówek, inne piksele) → `identity`,
    ZERO zapisu: to robota skanu (przepięcie lokacji), nie przejęcia. Klinga sama też odbija
    rekord cudzej klatki (EXPECT - błąd wołania)."""
    con, root, fid, _a, b = po_skasowaniu
    _cls(root, payload=b"\x06" * 32)
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    s = scan.adopt_orphan_testimony(con, now=LATER)
    assert (s.read, s.adopted, s.identity, s.remaining) == (1, 0, 1, 1)
    assert s.identity_paths == [str(b)]
    assert _header(con, fid)["filter_raw"] == "L-Pro"
    assert con.execute("SELECT count(*) FROM event WHERE id > ?", (ev,)).fetchone()[0] == 0
    rec = scan.scan_file(str(b))
    with pytest.raises(ValueError):
        repo.adopt_testimony(con, location_id=_loc(con, b)["id"], sha1_data=rec.sha1_data,
                             header_hash=rec.header_hash, raw_json="{}", cards=None,
                             hot_fields={}, camera_id=None, kind="flat", now=LATER, actor="t")


def test_etap_odmawia_kopii_zmienionej_od_skanu_i_nieczytelnej(po_skasowaniu):
    """Nagłówek ocalałej kopii zmieniony na dysku (odcisk ≠ znany) → `stale`: zeznanie odświeży
    skan, bo zmienił się odcisk TEJ kopii. Plik, którego nie ma → `failed`. Oba ZERO zapisu."""
    con, root, fid, _a, b = po_skasowaniu
    _xisf(b, _MASTER + (("FILTER", "'CLX'"),), payload=b"\x05" * 32)
    s = scan.adopt_orphan_testimony(con, now=LATER)
    assert (s.adopted, s.stale, s.stale_paths) == (0, 1, [str(b)])
    os.remove(b)
    s = scan.adopt_orphan_testimony(con, now=LATER)
    assert (s.adopted, s.failed, s.remaining) == (0, 1, 1) and s.failed_paths[0].startswith(str(b))
    assert _header(con, fid)["filter_raw"] == "L-Pro"


def test_izolacja_kopii_na_innym_woluminie_nie_blokuje_przejecia(po_skasowaniu):
    """Izolacja dotyczy kopii (wolumin + ścieżka): operacja zapisu w toku na lokacji innego
    woluminu pod tą samą ścieżką nie blokuje przejęcia zeznania ocalałej kopii. Falsyfikator:
    bramka `_isolated(con, path)` bez woluminu → `failed` „kopia izolowana"."""
    from test_copy_facts import _operacja
    con, _root, fid, _a, b = po_skasowaniu
    inna, _ = repo.upsert_frame(con, sha1_data="inna", kind="master_flat", filetype="xisf",
                                camera_id=None, now=NOW)
    lid_w, _ = repo.add_location(con, frame_id=inna, volume="W", path=str(b), header_hash="hW",
                                 now=NOW)
    _operacja(con, lid_w, "writing")
    assert scan._isolated(con, str(b)) and not scan._isolated(con, str(b), "?")
    s = scan.adopt_orphan_testimony(con, now=LATER)
    assert (s.rows, s.adopted, s.failed, s.failed_paths) == (1, 1, 0, [])
    assert _header(con, fid)["filter_raw"] == "CLS"


def test_etap_zawezony_do_korzenia(po_skasowaniu):
    """Korzeń dostawy zawęża kandydatów - etap nie czyta plików spoza wskazanego katalogu."""
    con, root, fid, _a, _b = po_skasowaniu
    (root / "INNY").mkdir()                    # `canonize_root` odmawia korzenia, którego nie ma
    assert scan.adopt_candidates(con, root / "INNY") == []
    s = scan.adopt_orphan_testimony(con, now=LATER, root=root / "INNY")
    assert (s.rows, s.read) == (0, 0)
    assert [f for f, _k in scan.adopt_candidates(con, root / "B_CLS")] == [fid]


# ═════════════════════════ zeznanie z ręki, anulowanie, tożsamość zdegenerowana


def test_zeznanie_z_recznej_poprawki_idzie_do_czlowieka_nie_do_etapu(tmp_path):
    """„Napraw nagłówek…" poprawia plik kopii A i `header` (RE-SYNC writebacku, aktor `user:local`);
    potem dochodzi kopia B ze starym głosem (reguła N-lokacji - zeznanie zostaje przy poprawce),
    a na końcu A znika. Etap przepisałby zeznanie głosem B i poprawka ręki przepadłaby bez śladu -
    więc klatka NIE jest kandydatem etapu, tylko pytaniem w Porządkach (AR-4), mimo jednej kopii."""
    from horreum import writeback
    root = tmp_path / "ARCH"
    a = _lpro(root)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    fid = _loc(con, a)["frame_id"]
    _xisf(a, _MASTER + (("FILTER", "'Ha'"), ("OBJECT", "'FlatWizard'"), ("EXPTIME", "0.2")))
    writeback._resync(con, str(a), "?", now=LATER)              # droga zapisu „Napraw nagłówek…"
    assert _header(con, fid)["filter_raw"] == "Ha"
    b = _cls(root)
    scan.scan_tree(con, root, volume="?", now=LATER)
    assert _loc(con, b)["frame_id"] == fid and _header(con, fid)["filter_raw"] == "Ha"
    _zniknij(con, a)
    assert set(queries.orphan_testimony_copies(con)) == {fid}
    assert queries.hand_testimony_frame_ids(con, [fid]) == {fid}
    assert scan.adopt_candidates(con) == []
    assert queries.orphan_testimony_frame_ids(con) == {fid}
    assert queries.tasks_state(con)["orphan_testimony_frames"] == 1
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    s = scan.adopt_orphan_testimony(con, now=LATER)
    assert (s.rows, s.read, s.adopted) == (0, 0, 0)
    assert _header(con, fid)["filter_raw"] == "Ha"
    assert con.execute("SELECT count(*) FROM event WHERE id > ?", (ev,)).fetchone()[0] == 0
    con.close()


def test_zeznanie_ze_skanu_nie_jest_z_reki(po_skasowaniu):
    """Najnowszy zapis zeznania z aktorem skanu - klatka nie jest „z ręki" i idzie do etapu."""
    con, _root, fid, _a, _b = po_skasowaniu
    assert queries.hand_testimony_frame_ids(con, [fid]) == set()
    assert queries.hand_testimony_frame_ids(con, []) == set()


def test_anulowanie_w_trakcie_petli_zostawia_baze_spojna(tmp_path):
    """Dwie klatki do przejęcia, anulowanie po pierwszej: `cancelled`, pierwsza przejęta w całości
    (własna transakcja), druga nietknięta i czeka w `remaining` na następną dostawę."""
    root = tmp_path / "ARCH"
    pary = [(_lpro(root / f"K{i}", payload=bytes([i]) * 32),
             _cls(root / f"K{i}", payload=bytes([i]) * 32)) for i in (1, 2)]
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    fids = [_loc(con, a)["frame_id"] for a, _b in pary]
    for a, _b in pary:
        _zniknij(con, a)
    stop = []
    s = scan.adopt_orphan_testimony(con, now=LATER, should_cancel=lambda: bool(stop),
                                    progress=lambda *_: stop.append(1))
    assert (s.cancelled, s.rows, s.adopted, s.remaining) == (True, 2, 1, 1)
    glosy = sorted(_header(con, f)["filter_raw"] for f in fids)
    assert glosy == ["CLS", "L-Pro"]
    assert [f for f, _k in scan.adopt_candidates(con)] == [f for f in fids
                                                            if _header(con, f)["filter_raw"] == "L-Pro"]
    con.close()


def test_przejecie_przy_tozsamosci_zdegenerowanej(tmp_path, monkeypatch):
    """Klatka o tożsamości nieobliczalnej (`sha1_data_uncomputable=1`: `sha1_data` = sha1 CAŁEGO
    pliku) - etap liczy tożsamość pliku tą samą regułą co wjazd (`_record_identity`), więc rekord
    bez `sha1_data` rozpoznaje jako tę klatkę i przejmuje zeznanie. Stan budowany klingą (skan nie
    wyprodukuje dwóch kopii-degeneratów o różnych nagłówkach - identyczne bajty to identyczny nagłówek)."""
    import dataclasses
    root = tmp_path / "ARCH"
    b = _cls(root)
    rec_b = scan.scan_file(str(b))
    con = db.open_db(str(tmp_path / "h.db"))
    fid, _ = repo.upsert_frame(con, sha1_data=rec_b.file_sha1, sha1_data_uncomputable=1,
                               kind="master_flat", filetype="xisf", camera_id=None, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json=json.dumps({"FILTER": "L-Pro"}), now=NOW,
                       filter_raw="L-Pro")
    repo.add_location(con, frame_id=fid, volume="V", path=str(root / "A" / "stara.xisf"),
                      header_hash="hA", now=NOW)
    lid_a = con.execute("SELECT id FROM location WHERE path = ?",
                        (str(root / "A" / "stara.xisf"),)).fetchone()[0]
    con.execute("UPDATE location SET present = 0 WHERE id = ?", (lid_a,))
    con.commit()
    repo.add_location(con, frame_id=fid, volume="V", path=rec_b.path, mtime=rec_b.mtime,
                      file_sha1=rec_b.file_sha1, header_hash=rec_b.header_hash,
                      copy_facts=scan.copy_header_facts(rec_b.header, rec_b.header_hash,
                                                        rec_b.image_roles), now=NOW)
    prawdziwy = scan.scan_file
    monkeypatch.setattr(scan, "scan_file",
                        lambda p: dataclasses.replace(prawdziwy(p), sha1_data=None))
    s = scan.adopt_orphan_testimony(con, now=LATER)
    assert (s.rows, s.adopted, s.identity) == (1, 1, 0)
    assert _header(con, fid)["filter_raw"] == "CLS"
    con.close()


@pytest.mark.parametrize("werdykt", ["drift", "unchanged"])
def test_werdykt_klingi_bez_zapisu_to_wyscig_nie_zmiana_na_dysku(po_skasowaniu, monkeypatch,
                                                                  werdykt):
    """`'drift'`/`'unchanged'` klingi mówią o stanie BAZY między odczytem a zapisem - liczą się
    jako `raced`, bez ścieżki, a nie jako `stale` („zmienione na dysku od skanu")."""
    con, _root, _fid, _a, _b = po_skasowaniu
    monkeypatch.setattr(repo, "adopt_testimony", lambda *a, **k: werdykt)
    s = scan.adopt_orphan_testimony(con, now=LATER)
    assert (s.adopted, s.stale, s.stale_paths, s.raced) == (0, 0, [], 1)
