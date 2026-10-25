"""Cofnięcie commitu kart przywraca STAN OBIEKTU klatki sprzed zapisu (AR-311, decyzja Zdzinia: wariant A).

„Napraw nagłówek…” pisze kartę `OBJECT` klatkom bez obiektu, „Zatwierdź ze ścieżki…” - klatkom nazwanym
z folderu; „Rozwiąż” zamienia kartę w przypisanie (`header`, przy ścieżce para E5-1). Cofnięcie commitu
zdejmuje kartę z pliku i - w tej samej transakcji co nagrobek ręki (AR-38) - odtwarza obiekt sprzed
zapisu, ale wyłącznie klatkom, których oś od przypisania z karty się nie zmieniła (CAS z dziennika).

Co pilnujemy: obie drogi zapisu (atomowo, w miejscu); każda gałąź źródła resolvera (nagłówek, alias,
zmiana samego źródła przy tym samym obiekcie, region po nierozpoznanej karcie, zdjęcie obiektu
bliźniaka); klatka zmieniona po „Rozwiąż” zostaje i jest policzona; commit bez karty `OBJECT` obiektu nie
rusza; „już cofnięte” odtwarza obiekt raz; nowszy zapis tą samą kartą i karta żywa na innej kopii
blokują odtworzenie; spis ręki bez ubytku. Pliki prawdziwe (astropy) w `tmp_path`."""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest
from astropy.io import fits

from horreum import cli, db, repo, resolver, scan, writeback
from horreum.resolve._text import norm_alnum

NOW = "2026-10-22T12:00:00+00:00"
INPLACE = pytest.mark.parametrize("inplace", [False, True], ids=["atomowo", "w_miejscu"])


def _plik(katalog, nazwa="NGC7635_a.fits", *, seed=1, ra=None, dec=None):
    d = katalog / "LIGHTS" / "NGC7635" / "RC8_2600MC" / "L-eXtreme"
    d.mkdir(parents=True, exist_ok=True)
    p = d / nazwa
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16) + seed)
    hdu.header["TELESCOP"] = "RC8"
    hdu.header["IMAGETYP"] = "Light"
    if ra is not None:
        hdu.header["RA"] = ra
        hdu.header["DEC"] = dec
    hdu.writeto(str(p), overwrite=True)
    return p


def _skan(con, p):
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
    return con.execute("SELECT id, frame_id FROM location WHERE path = ?", (str(p),)).fetchone()


def _karta(con, run_id, lid, wartosc, keyword="OBJECT"):
    hh = con.execute("SELECT header_hash FROM location WHERE id = ?", (lid,)).fetchone()[0]
    repo.stage_pending(con, run_id=run_id, location_id=lid, keyword=keyword, idx=None, op="add",
                       old_value=None, new_value=wartosc, new_type="str", new_comment=None,
                       expected_header_hash=hh)


def _scena(tmp_path, *, inplace, przygotuj=None, karta="NGC 7635", ra=None, dec=None):
    """Klatka bez karty `OBJECT` → `przygotuj(con, fid)` (stan sprzed zapisu) → commit karty."""
    con = db.open_db(str(tmp_path / "h.db"))
    p = _plik(tmp_path, ra=ra, dec=dec)
    loc = _skan(con, p)
    if przygotuj is not None:
        przygotuj(con, loc["frame_id"])
    _karta(con, "R", loc["id"], karta)
    c = writeback.commit(con, "R", now=NOW, inplace=inplace)
    assert len(c.applied) == 1 and bool(c.in_place) == inplace, c
    return SimpleNamespace(con=con, p=p, lid=loc["id"], fid=loc["frame_id"], commit=c.commit_id)


def _stan(con, fid):
    """`(kanon obiektu, źródło, pamięć nagrobka)` klatki."""
    r = con.execute("SELECT o.canon, f.object_source, f.object_cleared_id FROM frame f "
                    "LEFT JOIN object o ON o.id = f.object_id WHERE f.id = ?", (fid,)).fetchone()
    return (r[0], r[1], r[2])


def _odtworzenia(con, fid):
    return con.execute("SELECT count(*) FROM event WHERE target = ? AND reason = 'card_undone'",
                       (f"frame:{fid}",)).fetchone()[0]


def _parytet(con):
    """§5.9: `assigned − unassigned` = klatki z obiektem."""
    zd = dict(con.execute("SELECT verb, count(*) FROM event WHERE verb IN "
                          "('object.assigned', 'object.unassigned') GROUP BY verb").fetchall())
    z_obiektem = con.execute("SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0]
    return zd.get("object.assigned", 0) - zd.get("object.unassigned", 0) == z_obiektem


def _sciezka(con, fid):
    repo.user_assign_object(con, alias_norm=None, canon="NGC7635", catalog="NGC", kind="deep_sky",
                            frame_ids=[fid], now=NOW, object_source="path")


# ============================================================ odtworzenie - obie drogi zapisu


@INPLACE
def test_cofniecie_karty_po_rozwiaz_odpina_obiekt_z_karty(tmp_path, inplace):
    """„Napraw nagłówek…”: klatka bez obiektu → karta → „Rozwiąż” (`NGC7635`, `header`) → cofnięcie →
    klatka znów bez obiektu, zdarzenie `card_undone` z parą (commit, plik), parytet §5.9 domknięty,
    `objects_restored` = ta klatka; kolejne „Rozwiąż” nic nie zmienia. Falsyfikatory: odtworzenie
    zdjęte z re-syncu drogi atomowej (`atomowo`) albo z dokończenia operacji w miejscu (`w_miejscu`)."""
    s = _scena(tmp_path, inplace=inplace)
    resolver.run_resolver(s.con, NOW)
    assert _stan(s.con, s.fid) == ("NGC7635", "header", None)
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert u.complete and u.objects_restored == (s.fid,) and u.objects_kept == (), u
    assert _stan(s.con, s.fid) == (None, None, None)
    payload = json.loads(s.con.execute(
        "SELECT payload FROM event WHERE target = ? AND reason = 'card_undone'",
        (f"frame:{s.fid}",)).fetchone()[0])
    assert (payload["commit_id"], payload["location_id"]) == (s.commit, s.lid)
    assert _parytet(s.con)
    resolver.run_resolver(s.con, NOW)
    assert _stan(s.con, s.fid) == (None, None, None)
    s.con.close()


@INPLACE
def test_cofniecie_karty_po_rozwiaz_wraca_do_potwierdzenia_ze_sciezki(tmp_path, inplace):
    """„Zatwierdź ze ścieżki…”: `(NGC7635, path)` → karta → „Rozwiąż” przestawia źródło na `header`
    (para E5-1) → cofnięcie → `(NGC7635, path)`; spis ręki względem spisu sprzed karty bez ubytku
    (`human-facts --baseline`, kod 0), parytet domknięty. Falsyfikatory: stan sprzed brany zawsze jako
    pustka (ubytek ręki, kod 1); odtworzenie bez `object.assigned` (parytet)."""
    con = db.open_db(str(tmp_path / "h.db"))
    p = _plik(tmp_path)
    loc = _skan(con, p)
    _sciezka(con, loc["frame_id"])
    con.close()
    baza = str(tmp_path / "h.db")
    odniesienie = tmp_path / "przed.json"
    import contextlib
    import io
    bufor = io.StringIO()
    with contextlib.redirect_stdout(bufor):
        assert cli.main(["human-facts", baza, "--json"]) == 0
    odniesienie.write_text(bufor.getvalue(), encoding="utf-8")
    con = db.open_db(baza)
    _karta(con, "R", loc["id"], "NGC 7635")
    c = writeback.commit(con, "R", now=NOW, inplace=inplace)
    resolver.run_resolver(con, NOW)
    assert _stan(con, loc["frame_id"]) == ("NGC7635", "header", None)
    u = writeback.undo(con, c.commit_id, now=NOW)
    assert u.objects_restored == (loc["frame_id"],), u
    assert _stan(con, loc["frame_id"]) == ("NGC7635", "path", None)
    assert _parytet(con)
    con.close()
    with contextlib.redirect_stdout(io.StringIO()):
        assert cli.main(["human-facts", baza, "--baseline", str(odniesienie)]) == 0


# ============================================================ gałęzie źródła resolvera


def test_karta_z_aliasem_wraca_do_pustki(tmp_path):
    """Karta z nazwą aliasu - „Rozwiąż” przypisuje źródłem `alias`; cofnięcie oddaje pustkę."""
    def _alias(con, fid):
        oid, _ = repo.upsert_object(con, canon="NGC7635", catalog="NGC", kind="deep_sky", now=NOW)
        repo.add_object_alias(con, alias_norm=norm_alnum("Babelek"), object_id=oid, source="user",
                              now=NOW)
    s = _scena(tmp_path, inplace=False, przygotuj=_alias, karta="Babelek")
    resolver.run_resolver(s.con, NOW)
    assert _stan(s.con, s.fid) == ("NGC7635", "alias", None)
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert u.objects_restored == (s.fid,) and _stan(s.con, s.fid) == (None, None, None), u
    s.con.close()


def test_zmiana_samego_zrodla_wraca_do_zrodla_sprzed(tmp_path):
    """Ten sam obiekt, inne źródło: `(NGC7635, region)` → karta `NGC 7635` → para `region` → `header`
    przy tym samym obiekcie → cofnięcie → `(NGC7635, region)`. Falsyfikator: stan sprzed z obiektu bez
    źródła albo pustka."""
    def _region(con, fid):
        oid, _ = repo.upsert_object(con, canon="NGC7635", catalog="NGC", kind="deep_sky", now=NOW)
        repo.assign_object(con, frame_id=fid, object_id=oid, object_source="region", now=NOW)
    s = _scena(tmp_path, inplace=True, przygotuj=_region)
    resolver.run_resolver(s.con, NOW)
    assert _stan(s.con, s.fid) == ("NGC7635", "header", None)
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert u.objects_restored == (s.fid,) and _stan(s.con, s.fid) == ("NGC7635", "region", None), u
    s.con.close()


def test_region_po_nierozpoznanej_karcie_wraca_do_pustki_a_przebieg_liczy_go_od_nowa(tmp_path):
    """Karta z nazwą nierozpoznaną na klatce ze współrzędnymi w kompleksie Veil: „Rozwiąż” przypisuje
    `region` - cofnięcie oddaje pustkę sprzed zapisu, a kolejny przebieg nazywa klatkę regionem tak samo,
    jak bez karty (idempotencja: karta nie zostawiła śladu w osi)."""
    s = _scena(tmp_path, inplace=False, karta="Moja mgielka", ra=312.75, dec=30.67)
    resolver.run_resolver(s.con, NOW)
    assert _stan(s.con, s.fid) == ("Veil", "region", None)
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert u.objects_restored == (s.fid,) and _stan(s.con, s.fid) == (None, None, None), u
    resolver.run_resolver(s.con, NOW)
    assert _stan(s.con, s.fid) == ("Veil", "region", None)
    s.con.close()


def test_zdjecie_obiektu_blizniaka_po_kotwicy_nie_jest_przypisaniem_z_karty(tmp_path):
    """Klatka z obiektem bliźniaka (`twin`); po zapisie karty pierwszym zdarzeniem osi jest zdjęcie
    obiektu bliźniaka (oryginał go stracił, `repo.clear_twin_object`) - to nie przypisanie z karty, więc
    cofnięcie obiektu nie rusza i niczego nie liczy."""
    def _blizniak(con, fid):
        oid, _ = repo.upsert_object(con, canon="NGC7635", catalog="NGC", kind="deep_sky", now=NOW)
        repo.assign_object(con, frame_id=fid, object_id=oid, object_source="twin", now=NOW)
    s = _scena(tmp_path, inplace=False, przygotuj=_blizniak, karta="Moja mgielka")
    assert repo.clear_twin_object(s.con, frame_id=s.fid, now=NOW)
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert u.objects_restored == () and u.objects_kept == (), u
    assert _stan(s.con, s.fid) == (None, None, None) and _odtworzenia(s.con, s.fid) == 0
    s.con.close()


# ============================================================ klatki, które zostają


@pytest.mark.parametrize("zmiana", ["reka", "drugi_przebieg", "drugi_przebieg_z_powrotem"])
def test_klatka_zmieniona_po_rozwiaz_zostaje_i_jest_policzona(tmp_path, zmiana):
    """Oś klatki zmieniła się po przypisaniu z karty - ręka przypisała inny obiekt, kolejny przebieg
    przepiął go innym źródłem albo przepiął i wrócił do stanu z karty (A → B → A osi): cofnięcie obiektu
    nie rusza, `objects_kept` = ta klatka, a ponowne „Rozwiąż” jej nie zmienia. Falsyfikatory: CAS bez
    stanu klatki (ręka ginie); CAS bez warunku „przypisanie z karty jest ostatnim zdarzeniem osi”
    (wariant z powrotem - stan równy, oś nie)."""
    s = _scena(tmp_path, inplace=True)
    resolver.run_resolver(s.con, NOW)
    oid = s.con.execute("SELECT object_id FROM frame WHERE id = ?", (s.fid,)).fetchone()[0]
    if zmiana == "reka":
        assert repo.user_override_object(s.con, frame_id=s.fid, canon="M31", catalog="M",
                                         kind="deep_sky", expected=(oid, "header", None), now=NOW,
                                         reason="object_change") == "assigned"
        assert _stan(s.con, s.fid)[:2] == ("M31", "user")
    else:
        repo.assign_object(s.con, frame_id=s.fid, object_id=oid, object_source="region", now=NOW)
        if zmiana == "drugi_przebieg_z_powrotem":
            repo.assign_object(s.con, frame_id=s.fid, object_id=oid, object_source="header", now=NOW)
    przed = _stan(s.con, s.fid)
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert u.objects_kept == (s.fid,) and u.objects_restored == (), u
    assert _stan(s.con, s.fid) == przed and _odtworzenia(s.con, s.fid) == 0
    resolver.run_resolver(s.con, NOW)
    assert _stan(s.con, s.fid) == przed
    s.con.close()


def test_commit_bez_karty_OBJECT_nie_odtwarza_obiektu(tmp_path):
    """Karta `OBSERVER` na klatce bez obiektu, potem przypisanie automatu: cofnięcie commitu nie rusza
    obiektu i nic nie liczy. Falsyfikator: plan bez warunku „commit wpisał kartę `OBJECT` w ten plik”."""
    con = db.open_db(str(tmp_path / "h.db"))
    p = _plik(tmp_path)
    loc = _skan(con, p)
    _karta(con, "R", loc["id"], "Ktos", keyword="OBSERVER")
    c = writeback.commit(con, "R", now=NOW, inplace=False)
    assert len(c.applied) == 1, c
    oid, _ = repo.upsert_object(con, canon="NGC7635", catalog="NGC", kind="deep_sky", now=NOW)
    repo.assign_object(con, frame_id=loc["frame_id"], object_id=oid, object_source="region", now=NOW)
    u = writeback.undo(con, c.commit_id, now=NOW)
    assert u.complete and u.objects_restored == () and u.objects_kept == (), u
    assert _stan(con, loc["frame_id"]) == ("NGC7635", "region", None)
    con.close()


def test_nagrobek_zostaje_domena_AR38_i_liczy_sie_jako_powrot(tmp_path):
    """Nagrobek ręki → karta (gasi go) → „Rozwiąż” → cofnięcie: nagrobek wraca z pamięcią (AR-38), klatka
    jest policzona jako powrót do stanu sprzed zapisu, zdarzeń `card_undone` nie ma. Falsyfikator: plan
    bez wyłączenia pary zgaszenia nagrobka - klatka w `objects_kept`."""
    def _nagrobek(con, fid):
        repo.user_assign_object(con, alias_norm=None, canon="COS", catalog=None, kind="own",
                                frame_ids=[fid], now=NOW)
        repo.clear_object_assignment(con, frame_ids=[fid], now=NOW)
    s = _scena(tmp_path, inplace=True, przygotuj=_nagrobek)
    resolver.run_resolver(s.con, NOW)
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert u.objects_restored == (s.fid,) and u.objects_kept == (), u
    assert _stan(s.con, s.fid)[:2] == (None, "user_cleared") and _odtworzenia(s.con, s.fid) == 0
    s.con.close()


# ============================================================ „już cofnięte”, pad, CLI


@INPLACE
def test_juz_cofniete_odtwarza_obiekt_raz(tmp_path, inplace):
    """Plik wrócił spoza Horreum (bajty sprzed zapisu) i skan to wciągnął - cofnięcie mówi „już
    cofnięte” i rozlicza bazę: obiekt z karty wraca do stanu sprzed zapisu; drugie cofnięcie nie dokłada
    zdarzeń, a liczy klatkę tak samo. Falsyfikator: rozliczenie „już cofnięte” bez odtworzenia obiektu."""
    con = db.open_db(str(tmp_path / "h.db"))
    p = _plik(tmp_path)
    loc = _skan(con, p)
    przed = p.read_bytes()
    _karta(con, "R", loc["id"], "NGC 7635")
    c = writeback.commit(con, "R", now=NOW, inplace=inplace)
    resolver.run_resolver(con, NOW)
    p.write_bytes(przed)
    _skan(con, p)
    u = writeback.undo(con, c.commit_id, now=NOW)
    assert u.complete and u.already and u.objects_restored == (loc["frame_id"],), u
    assert _stan(con, loc["frame_id"]) == (None, None, None)
    zdarzenia = con.execute("SELECT count(*) FROM event").fetchone()[0]
    u2 = writeback.undo(con, c.commit_id, now=NOW)
    assert u2.objects_restored == (loc["frame_id"],), u2
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == zdarzenia
    con.close()


def test_pad_odtworzenia_obiektu_wycofuje_re_sync(tmp_path, monkeypatch):
    """Wyjątek odtworzenia stanu obiektu w transakcji re-syncu wycofuje też wciągnięcie rekordu: baza
    dalej opisuje plik po commicie, klatka z obiektem z karty; ponowienie robi oba zapisy naraz."""
    s = _scena(tmp_path, inplace=False)
    resolver.run_resolver(s.con, NOW)
    hh = s.con.execute("SELECT header_hash FROM location WHERE id = ?", (s.lid,)).fetchone()[0]
    prawdziwy = repo._plan_obiektu_z_karty

    def _pad(*a, **kw):
        raise RuntimeError("awaria w połowie")
    monkeypatch.setattr(repo, "_plan_obiektu_z_karty", _pad)
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert len(u.failed) == 1, u
    assert s.con.execute("SELECT header_hash FROM location WHERE id = ?", (s.lid,)).fetchone()[0] == hh
    assert _stan(s.con, s.fid) == ("NGC7635", "header", None)
    monkeypatch.setattr(repo, "_plan_obiektu_z_karty", prawdziwy)
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert u.complete and _stan(s.con, s.fid) == (None, None, None), u
    s.con.close()


def test_header_fix_undo_cli_daje_ten_sam_stan(tmp_path, capsys):
    """`header-fix --undo N` - ten sam rdzeń: klatka bez obiektu i wiersz ASCII z liczbami."""
    s = _scena(tmp_path, inplace=False)
    resolver.run_resolver(s.con, NOW)
    s.con.close()
    assert cli.main(["header-fix", str(tmp_path / "h.db"), "--undo", str(s.commit)]) == 0
    out = capsys.readouterr().out
    assert ("  obiekt z cofnietej karty: klatki ze stanem sprzed zapisu 1, zostaja (zmienione po "
            "Rozwiaz) 0") in out, out
    out.encode("ascii")
    con = db.open_db(str(tmp_path / "h.db"))
    assert _stan(con, s.fid) == (None, None, None)
    con.close()


# ============================================================ granice odtworzenia


@INPLACE
def test_nowszy_zapis_ta_sama_karta_blokuje_odtworzenie(tmp_path, inplace):
    """C pisze kartę, „Rozwiąż”, cofnięcie C domknięte (pustka); C2 pisze TĘ SAMĄ kartę, „Rozwiąż” znów
    przypisuje. Ponowne cofnięcie C nie rusza obiektu z karty C2 i NIE liczy klatki jako powrotu - ten
    commit nie jest ostatnim pisarzem pliku. Falsyfikator: plan bez kroku nowszego żywego zapisu
    (klatka w `objects_restored`)."""
    s = _scena(tmp_path, inplace=inplace)
    resolver.run_resolver(s.con, NOW)
    assert writeback.undo(s.con, s.commit, now=NOW).objects_restored == (s.fid,)
    _karta(s.con, "R2", s.lid, "NGC 7635")
    assert writeback.commit(s.con, "R2", now=NOW, inplace=inplace).applied
    resolver.run_resolver(s.con, NOW)
    assert _stan(s.con, s.fid) == ("NGC7635", "header", None)
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert u.objects_restored == () and _stan(s.con, s.fid) == ("NGC7635", "header", None), u
    s.con.close()


def test_karta_zywa_na_innej_kopii_blokuje_odtworzenie(tmp_path):
    """Karta zapisana w plik, potem kopia tego pliku (z kartą) obok - ta sama klatka, dwie obecne kopie;
    ręka wskazuje pierwszą jako wiodącą, „Rozwiąż” przypisuje. Cofnięcie zdejmuje kartę z kopii wiodącej
    (zeznanie milknie), ale karta dalej żyje na drugiej kopii - obiekt klatki zostaje i nic nie jest
    liczone. Falsyfikator: plan bez kroku „inna obecna kopia ma niepusty `hdr_object`” (klatka wraca
    do pustki obok kopii, która ją nazywa)."""
    import shutil
    from horreum import lead_copy
    s = _scena(tmp_path, inplace=False)
    kopia = tmp_path / "b" / "NGC7635_kopia.fits"
    kopia.parent.mkdir(parents=True)
    shutil.copy2(s.p, kopia)
    assert _skan(s.con, kopia)["frame_id"] == s.fid
    assert lead_copy.adopt_lead_copy(s.con, location_id=s.lid, now=NOW).verdict in ("adopted",
                                                                                   "confirmed")
    resolver.run_resolver(s.con, NOW)
    przed = _stan(s.con, s.fid)
    assert przed == ("NGC7635", "header", None), przed
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert u.complete and u.objects_restored == () and u.objects_kept == (), u
    assert s.con.execute("SELECT object_raw FROM header WHERE frame_id = ?",
                         (s.fid,)).fetchone()[0] is None
    assert _stan(s.con, s.fid) == przed and _odtworzenia(s.con, s.fid) == 0
    s.con.close()


# ============================================================ stos commitów C2 → C1 (kotwica pochodzenia)


def _spis_reki(baza, odniesienie=None):
    """`horreum human-facts` przez `cli.main`: bez odniesienia - JSON do pliku obok bazy (ścieżka);
    z odniesieniem - kod wyjścia porównania."""
    import contextlib
    import io
    bufor = io.StringIO()
    with contextlib.redirect_stdout(bufor):
        if odniesienie is None:
            assert cli.main(["human-facts", baza, "--json"]) == 0
        else:
            return cli.main(["human-facts", baza, "--baseline", str(odniesienie)])
    plik = baza + ".przed.json"
    with open(plik, "w", encoding="utf-8") as fh:
        fh.write(bufor.getvalue())
    return plik


@INPLACE
@pytest.mark.parametrize("c0_kiedy", ["wczesniej", "ta_sama_sekunda"])
def test_kotwica_nie_starsza_niz_zapis_commitu(tmp_path, inplace, c0_kiedy):
    """Ta sama karta zapisana dwa razy: C0 → „Rozwiąż” → cofnięcie C0 (stan sprzed wraca) → C1 (ten sam
    odcisk nagłówka co C0, wcześniej albo W TEJ SAMEJ SEKUNDZIE - wstrzyknięty zegar) → „Rozwiąż” →
    cofnięcie C1 oddaje `(NGC7635, path)`. Kotwicą jest zdarzenie z parą (C1, plik) w ładunku, nie odcisk
    ani czas. Falsyfikator: kotwica po odcisku i czasie - pada na re-sync C0, po niej oś drgała, klatka
    „zostaje” z `header`."""
    con = db.open_db(str(tmp_path / "h.db"))
    loc = _skan(con, _plik(tmp_path))
    fid = loc["frame_id"]
    _sciezka(con, fid)
    wczesniej = "2026-10-20T12:00:00+00:00" if c0_kiedy == "wczesniej" else NOW
    _karta(con, "R0", loc["id"], "NGC 7635")
    c0 = writeback.commit(con, "R0", now=wczesniej, inplace=inplace)
    resolver.run_resolver(con, wczesniej)
    assert writeback.undo(con, c0.commit_id, now=wczesniej).objects_restored == (fid,)
    _karta(con, "R1", loc["id"], "NGC 7635")
    c1 = writeback.commit(con, "R1", now=NOW, inplace=inplace)
    assert [b[0] for b in con.execute("SELECT post_hash FROM header_backups ORDER BY id")] \
        == [con.execute("SELECT post_hash FROM header_backups WHERE commit_id = ?",
                        (c0.commit_id,)).fetchone()[0]] * 2
    resolver.run_resolver(con, NOW)
    u = writeback.undo(con, c1.commit_id, now=NOW)
    assert u.objects_restored == (fid,), u
    assert _stan(con, fid) == ("NGC7635", "path", None)
    con.close()


@INPLACE
def test_commit_wieloplikowy_kotwica_per_plik(tmp_path, inplace):
    """Jeden commit pisze kartę w dwa pliki dwóch klatek (jedno `applied_at` na oba): każda klatka dostaje
    kotwicę z parą (commit, SWÓJ plik) - po „Rozwiąż” cofnięcie oddaje obie do stanu sprzed zapisu,
    każdą ze swoim stanem (`path` i pustka)."""
    con = db.open_db(str(tmp_path / "h.db"))
    a = _skan(con, _plik(tmp_path, "NGC7635_a.fits", seed=1))
    b = _skan(con, _plik(tmp_path, "NGC7635_b.fits", seed=2))
    assert a["frame_id"] != b["frame_id"]
    _sciezka(con, a["frame_id"])
    _karta(con, "R", a["id"], "NGC 7635")
    _karta(con, "R", b["id"], "NGC 7635")
    c = writeback.commit(con, "R", now=NOW, inplace=inplace)
    assert len(c.applied) == 2, c
    resolver.run_resolver(con, NOW)
    pary = sorted((json.loads(p)["commit_id"], json.loads(p)["location_id"]) for (p,) in con.execute(
        "SELECT payload FROM event WHERE verb = ?", (repo.ZNACZNIK_ZAPISU_KARTY,)))
    assert pary == sorted([(c.commit_id, a["id"]), (c.commit_id, b["id"])]), pary
    u = writeback.undo(con, c.commit_id, now=NOW)
    assert sorted(u.objects_restored) == sorted([a["frame_id"], b["frame_id"]]), u
    assert _stan(con, a["frame_id"]) == ("NGC7635", "path", None)
    assert _stan(con, b["frame_id"]) == (None, None, None)
    con.close()


def test_zapis_bez_dowodu_pochodzenia_nie_odtwarza(tmp_path):
    """Commit bez dowodu pochodzenia (para commit/plik ani w znaczniku zapisu karty, ani w zdarzeniu
    zeznania) - tak wyglądają zapisy sprzed tego dowodu (emulacja: znacznik usunięty z dziennika bazy testu):
    cofnięcie nie zgaduje kotwicy po odcisku ani czasie, klatka zostaje przy obiekcie z karty i nie jest
    liczona."""
    s = _scena(tmp_path, inplace=False)
    s.con.execute("DELETE FROM event WHERE verb = ?", (repo.ZNACZNIK_ZAPISU_KARTY,))
    s.con.commit()
    resolver.run_resolver(s.con, NOW)
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert u.complete and u.objects_restored == () and u.objects_kept == (), u
    assert _stan(s.con, s.fid) == ("NGC7635", "header", None) and _odtworzenia(s.con, s.fid) == 0
    s.con.close()


def _karta_set(con, run_id, lid, wartosc):
    hh = con.execute("SELECT header_hash FROM location WHERE id = ?", (lid,)).fetchone()[0]
    repo.stage_pending(con, run_id=run_id, location_id=lid, keyword="OBJECT", idx=0, op="set",
                       old_value=None, new_value=wartosc, new_type="str", new_comment=None,
                       expected_header_hash=hh)


@INPLACE
@pytest.mark.parametrize("c2", ["observer", "object_i_rozwiaz"])
def test_stos_c2_c1_kotwica_to_zapis_c1(tmp_path, inplace, c2):
    """„Zatwierdź ze ścieżki…” `(NGC7635, path)` → C1 dopisuje kartę `OBJECT`, „Rozwiąż” przestawia na
    `header` → C2 pisze w ten sam plik → cofnięcie C2 (odcisk nagłówka wraca do wyniku C1 i niesie własne
    `header.refreshed`) → cofnięcie C1. Kotwica to znacznik zapisu karty C1 z parą (C1, plik):
      * C2 zmienia `OBSERVER` - cofnięcie C1 oddaje `(NGC7635, path)`, klatka policzona jako powrót;
      * C2 zmienia `OBJECT` na `NGC 7000` + „Rozwiąż” + cofnięcie C2 + ponowne „Rozwiąż” (oś wraca do
        `NGC7635`) - po przypisaniu z karty C1 oś drgnęła, więc klatka ZOSTAJE (policzona), nigdy nie bierze
        obiektu z C2.
    Spis ręki względem spisu sprzed C1 - kod 0. Falsyfikator: kotwica = najnowsze zdarzenie z odciskiem
    (pada na cofnięcie C2): wariant `observer` zostawia `header`, wariant `object_i_rozwiaz` odtwarza
    `NGC7000` - obiekt z karty C2 - jako „stan sprzed C1”."""
    con = db.open_db(str(tmp_path / "h.db"))
    p = _plik(tmp_path)
    loc = _skan(con, p)
    fid = loc["frame_id"]
    _sciezka(con, fid)
    con.close()
    baza = str(tmp_path / "h.db")
    odniesienie = _spis_reki(baza)
    con = db.open_db(baza)
    _karta(con, "R1", loc["id"], "NGC 7635")
    c1 = writeback.commit(con, "R1", now=NOW, inplace=inplace)
    resolver.run_resolver(con, NOW)
    assert _stan(con, fid) == ("NGC7635", "header", None)
    if c2 == "observer":
        _karta(con, "R2", loc["id"], "Ktos", keyword="OBSERVER")
    else:
        _karta_set(con, "R2", loc["id"], "NGC 7000")
    k2 = writeback.commit(con, "R2", now=NOW, inplace=inplace)
    assert len(k2.applied) == 1, k2
    if c2 != "observer":
        resolver.run_resolver(con, NOW)
        assert _stan(con, fid)[:2] == ("NGC7000", "header")
    assert writeback.undo(con, k2.commit_id, now=NOW).complete
    if c2 != "observer":
        # Nagłówek po cofnięciu C2 mówi kartą C1, więc cofnięcie C2 obiektu nie rusza (krok 4); ponowne
        # „Rozwiąż” przepina oś z NGC7000 na NGC7635 - para resolvera PO zdarzeniu cofnięcia C2.
        resolver.run_resolver(con, NOW)
        assert _stan(con, fid) == ("NGC7635", "header", None)
    u = writeback.undo(con, c1.commit_id, now=NOW)
    assert u.complete, u
    if c2 == "observer":
        assert u.objects_restored == (fid,) and u.objects_kept == (), u
        assert _stan(con, fid) == ("NGC7635", "path", None)
    else:
        assert u.objects_kept == (fid,) and u.objects_restored == (), u
        assert _stan(con, fid) == ("NGC7635", "header", None)
    assert _parytet(con)
    con.close()
    assert _spis_reki(baza, odniesienie) == 0
