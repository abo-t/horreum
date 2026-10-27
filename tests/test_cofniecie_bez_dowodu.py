"""AR-364: cofnięcie karty `OBJECT` bez dowodu pochodzenia (zapis sprzed pary commit/plik w znaczniku zapisu karty)
nie milczy o klatce, która zostaje przy obiekcie z nagłówka - `UndoResult.objects_unproven`, człon zdania wyniku
każdej powierzchni (`wb_worker.zdanie_undo_kart`) i wiersz CLI. Zapisu brak (nic nie zgadujemy), a „nie dotyczy”
zostaje „nie dotyczy”: krok 0 (nowszy żywy zapis lokacji), krok 4 (nagłówek po cofnięciu dalej mówi nazwę), krok 4b
(nazwę niesie inna obecna kopia) i źródło spoza nagłówka (region, ręka, ścieżka, brak obiektu) - bez członu.

Emulacja zapisu sprzed dowodu: znacznik `header.card_applied` usunięty z dziennika bazy testu (jak
`test_undo_obiekt_karty.test_zapis_bez_dowodu_pochodzenia_nie_odtwarza`). Pliki prawdziwe (astropy) w `tmp_path`."""
from __future__ import annotations

import shutil

import pytest
from astropy.io import fits

from horreum import cli, db, lead_copy, repo, resolver, writeback

from test_undo_obiekt_karty import NOW, _karta_set, _odtworzenia, _plik, _scena, _sciezka, _skan, _stan


def _bez_dowodu(con):
    """Zapis sprzed pary (commit, plik): znacznik zapisu karty usunięty z dziennika."""
    con.execute("DELETE FROM event WHERE verb = ?", (repo.ZNACZNIK_ZAPISU_KARTY,))
    con.commit()


@pytest.mark.parametrize("inplace", [False, True], ids=["atomowo", "w_miejscu"])
def test_dopisanie_bez_pary_po_cofnieciu_liczone_bez_dowodu(tmp_path, inplace):
    """Dopisanie karty do milczącego nagłówka, „Rozwiąż” (`header`), dowodu brak: cofnięcie zdejmuje kartę, klatka
    zostaje przy obiekcie, a wynik liczy ją jako bez dowodu - zero odtworzeń i zero zmian osi. Falsyfikator: brak
    dowodu zlany z „nie dotyczy” (`objects_unproven` puste, zdanie milczy)."""
    s = _scena(tmp_path, inplace=inplace)
    _bez_dowodu(s.con)
    resolver.run_resolver(s.con, NOW)
    osi = s.con.execute("SELECT count(*) FROM event WHERE target = ? AND verb LIKE 'object.%'",
                        (f"frame:{s.fid}",)).fetchone()[0]
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert u.complete and u.objects_unproven == (s.fid,), u
    assert u.objects_restored == () and u.objects_kept == (), u
    assert fits.getheader(str(s.p)).get("OBJECT") is None
    assert _stan(s.con, s.fid) == ("NGC7635", "header", None) and _odtworzenia(s.con, s.fid) == 0
    assert s.con.execute("SELECT count(*) FROM event WHERE target = ? AND verb LIKE 'object.%'",
                         (f"frame:{s.fid}",)).fetchone()[0] == osi
    s.con.close()


def test_ponowione_cofniecie_mowi_te_sama_liczbe(tmp_path):
    """Drugie cofnięcie („już cofnięte”) liczy tę samą klatkę - werdykt ze STANU bazy, jak powrót obiektu."""
    s = _scena(tmp_path, inplace=False)
    _bez_dowodu(s.con)
    resolver.run_resolver(s.con, NOW)
    assert writeback.undo(s.con, s.commit, now=NOW).objects_unproven == (s.fid,)
    u2 = writeback.undo(s.con, s.commit, now=NOW)
    assert u2.complete and u2.already and u2.objects_unproven == (s.fid,), u2
    s.con.close()


def _region(con, fid):
    oid, _ = repo.upsert_object(con, canon="NGC7635", catalog="NGC", kind="deep_sky", now=NOW)
    repo.assign_object(con, frame_id=fid, object_id=oid, object_source="region", now=NOW)


def _reka(con, fid):
    resolver.run_resolver(con, NOW)
    oid = con.execute("SELECT object_id FROM frame WHERE id = ?", (fid,)).fetchone()[0]
    assert repo.user_override_object(con, frame_id=fid, canon="M31", catalog="M", kind="deep_sky",
                                     expected=(oid, "header", None), now=NOW, reason="object_change") == "assigned"


@pytest.mark.parametrize("zrodlo", ["region", "reka", "sciezka", "brak_obiektu"])
def test_bez_pary_klatka_nie_z_naglowka_bez_czlonu(tmp_path, zrodlo):
    """Brak dowodu przy klatce, której obiektu nie nadał nagłówek (region, ręka, potwierdzenie ze ścieżki bez
    „Rozwiąż”, klatka bez obiektu): wariant nie dotyczy - bez członu i bez zapisu osi. Falsyfikator: `bez_dowodu`
    bezwarunkowo przy braku kotwicy."""
    s = _scena(tmp_path, inplace=False, przygotuj=_sciezka if zrodlo == "sciezka" else None)
    _bez_dowodu(s.con)
    if zrodlo == "region":
        _region(s.con, s.fid)
    elif zrodlo == "reka":
        _reka(s.con, s.fid)
    przed = _stan(s.con, s.fid)
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert u.complete and u.objects_unproven == () and u.objects_restored == () and u.objects_kept == (), u
    assert _stan(s.con, s.fid) == przed
    s.con.close()


# ============================================================ macierz kroków „nie dotyczy” przy źródle `header`


def test_krok0_nowszy_zywy_zapis_przy_naglowku_bez_czlonu(tmp_path):
    """Krok 0: po dopisaniu bez dowodu nowszy żywy zapis tej lokacji (C2 czyści `OBJECT` do pustego - nagłówek
    milczy, więc kroki 4 i 4b przepuszczają) - commit C1 nie jest ostatnim pisarzem pliku. Cofnięcie C1 odmawia
    `undo_newer_write`, werdykt obiektu C1 = „nie dotyczy”, choć klatka jest przy obiekcie z nagłówka. Falsyfikatory:
    gałąź braku dowodu przed krokiem 0; plan bez kroku 0 (`bez_dowodu` o pliku, który zapisał już inny commit)."""
    s = _scena(tmp_path, inplace=False)
    resolver.run_resolver(s.con, NOW)
    _karta_set(s.con, "R2", s.lid, "")
    assert writeback.commit(s.con, "R2", now=NOW, inplace=False).applied
    _bez_dowodu(s.con)
    resolver.run_resolver(s.con, NOW)
    assert _stan(s.con, s.fid)[:2] == ("NGC7635", "header")
    assert s.con.execute("SELECT object_raw FROM header WHERE frame_id = ?", (s.fid,)).fetchone()[0] is None
    assert repo.object_undo_verdict(s.con, commit_id=s.commit, location_id=s.lid) == (s.fid, None)
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert [fr.reason.code for fr in u.blocked] == ["undo_newer_write"] and u.objects_unproven == (), u
    s.con.close()


def test_krok4_naglowek_po_cofnieciu_mowi_nazwe_bez_czlonu(tmp_path):
    """Krok 4: karta ZMIENIA istniejący `OBJECT` ('NGC 7000' → 'NGC 7635', `set`) - po cofnięciu nagłówek dalej mówi
    nazwę sprzed zapisu, a przebieg przeliczy obiekt z zeznania. Bez dowodu, klatka przy obiekcie z nagłówka - mimo to
    bez członu. Falsyfikator: gałąź braku dowodu przed krokiem 4."""
    con = db.open_db(str(tmp_path / "h.db"))
    p = _plik(tmp_path)
    fits.setval(str(p), "OBJECT", value="NGC 7000")
    loc = _skan(con, p)
    resolver.run_resolver(con, NOW)
    _karta_set(con, "R", loc["id"], "NGC 7635")
    c = writeback.commit(con, "R", now=NOW, inplace=False)
    assert len(c.applied) == 1, c
    _bez_dowodu(con)
    resolver.run_resolver(con, NOW)
    assert _stan(con, loc["frame_id"])[:2] == ("NGC7635", "header")
    u = writeback.undo(con, c.commit_id, now=NOW)
    assert u.complete and u.objects_unproven == (), u
    assert con.execute("SELECT object_raw FROM header WHERE frame_id = ?",
                       (loc["frame_id"],)).fetchone()[0] == "NGC 7000"
    con.close()


def test_krok4b_inna_obecna_kopia_niesie_nazwe_bez_czlonu(tmp_path):
    """Krok 4b: karta zapisana, potem kopia pliku (z kartą) obok - kopia wiodąca po cofnięciu milknie (zeznanie
    NULL), ale nazwę niesie druga obecna kopia. Bez dowodu, klatka przy obiekcie z nagłówka - bez członu.
    Falsyfikator: gałąź braku dowodu przed krokiem 4b (klatka „bez dowodu” obok kopii, która ją nazywa)."""
    s = _scena(tmp_path, inplace=False)
    kopia = tmp_path / "b" / "NGC7635_kopia.fits"
    kopia.parent.mkdir(parents=True)
    shutil.copy2(s.p, kopia)
    assert _skan(s.con, kopia)["frame_id"] == s.fid
    assert lead_copy.adopt_lead_copy(s.con, location_id=s.lid, now=NOW).verdict in ("adopted", "confirmed")
    _bez_dowodu(s.con)
    resolver.run_resolver(s.con, NOW)
    assert _stan(s.con, s.fid) == ("NGC7635", "header", None)
    u = writeback.undo(s.con, s.commit, now=NOW)
    assert u.complete and u.objects_unproven == () and u.objects_restored == () and u.objects_kept == (), u
    assert s.con.execute("SELECT object_raw FROM header WHERE frame_id = ?", (s.fid,)).fetchone()[0] is None
    s.con.close()


def test_lancuch_nowszy_zapis_potem_dopisanie(tmp_path):
    """Droga milczenia z bazy `pf4` (commity dopisania nadpisane normalizacją): C1 dopisuje kartę do milczącego
    nagłówka, C2 ją normalizuje (`set`
    'NGC 7635' → 'NGC7635'), oba bez dowodu, „Rozwiąż”. Cofnięcie C2: nagłówek wraca do karty C1 (krok 4 - bez
    członu); cofnięcie C1: nagłówek milknie, klatka zostaje przy obiekcie - człon `bez_dowodu`. Falsyfikator: zdanie
    milczy po drugim cofnięciu."""
    s = _scena(tmp_path, inplace=True)
    _karta_set(s.con, "R2", s.lid, "NGC7635")
    c2 = writeback.commit(s.con, "R2", now=NOW, inplace=True)
    assert len(c2.applied) == 1, c2
    _bez_dowodu(s.con)
    resolver.run_resolver(s.con, NOW)
    assert writeback.undo(s.con, s.commit, now=NOW).blocked          # C1: nowszy żywy zapis (C2)
    u2 = writeback.undo(s.con, c2.commit_id, now=NOW)
    assert u2.complete and u2.objects_unproven == () and fits.getheader(str(s.p))["OBJECT"] == "NGC 7635", u2
    u1 = writeback.undo(s.con, s.commit, now=NOW)
    assert u1.complete and u1.objects_unproven == (s.fid,), u1
    assert fits.getheader(str(s.p)).get("OBJECT") is None
    assert _stan(s.con, s.fid) == ("NGC7635", "header", None)
    s.con.close()


# ============================================================ zdanie powierzchni i CLI


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_zdanie_undo_kart_mowi_bez_dowodu_z_odmiana(lang):
    """Człon zdania wyniku cofnięcia (wspólny dla szuflady, okien kart i paska) z odmianą 1, 2, 5, 12, 22 i bez
    słowa, że obiekt nadała karta. Falsyfikator: człon pominięty albo forma „1 klatek”."""
    pytest.importorskip("PySide6")
    from horreum.gui import i18n
    from horreum.gui.wb_worker import zdanie_undo_kart
    oczek = {"pl": {1: "1 klatka zostaje", 2: "2 klatki zostają", 5: "5 klatek zostaje", 12: "12 klatek zostaje",
                    22: "22 klatki zostają"},
             "en": {1: "1 frame keeps", 2: "2 frames keep", 5: "5 frames keep", 12: "12 frames keep",
                    22: "22 frames keep"}}[lang]
    try:
        i18n.set_lang(lang)
        assert zdanie_undo_kart(writeback.UndoResult(1, [], [], [])).count("·") == 0
        for n, poczatek in oczek.items():
            zdanie = zdanie_undo_kart(writeback.UndoResult(1, [], [], [], objects_unproven=tuple(range(n))))
            czlon = zdanie.split(" · ")[-1]
            assert czlon.startswith(poczatek) and czlon == i18n.t_plural("wb.undo_objects_unproven", n), zdanie
    finally:
        i18n.set_lang("pl")


def test_cli_undo_mowi_bez_dowodu_pochodzenia(tmp_path, capsys):
    """`header-fix --undo N` po dopisaniu bez dowodu: wiersz obiektu z liczbą „bez dowodu pochodzenia 1”, druk
    ASCII. Falsyfikator: wiersz tylko przy przywróconych/zostających."""
    s = _scena(tmp_path, inplace=False)
    _bez_dowodu(s.con)
    resolver.run_resolver(s.con, NOW)
    s.con.close()
    assert cli.main(["header-fix", str(tmp_path / "h.db"), "--undo", str(s.commit)]) == 0
    out = capsys.readouterr().out
    assert ("  obiekt z cofnietej karty: klatki ze stanem sprzed zapisu 0, zostaja (zmienione po Rozwiaz) 0, "
            "bez dowodu pochodzenia 1") in out, out
    out.encode("ascii")
