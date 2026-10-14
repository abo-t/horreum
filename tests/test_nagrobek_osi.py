"""NAGROBEK OSI (AR-133, AR-137, decyzja `Q8`, migracja 0040): „Cofnij” gestu, który ZAŁOŻYŁ obiekt
(„Zmień obiekt…”) albo teleskop („Dopisz nowy…”), zdejmuje go nagrobkiem, gdy nie ma klatek ani
faktów ręki spoza gestu; założenie pod tą samą nazwą przywraca wiersz.

Testy pilnują: cyklu zmień → cofnij → ponów (wskrzeszenie) → cofnij na plikach; odmów nagrobka
obiektu (klatka, pamięć nagrobka klatki, obcy alias, inny żywy przebieg) i teleskopu (ręka po
geście, park, scalenie, profil, fakt przepisu); powrotu klatek do stanu sprzed „Dopisz nowy…” (CAS);
filtrów list; publicznych kling odmawiających na nagrobku; liczników wskrzeszenia w Dostawie;
strażnika pary katalogowej; inwariantów audytu i ręki nietykalnej (spis sprzed gestu wobec stanu
po cofnięciu, także `telescope_hand`). Każdy test nazywa mutanta, który go czerwieni."""
import json

import pytest

from horreum import audit, db, grouper, projection, repo, resolver, sky, writeback
from horreum import object_change as oc
from horreum.gui import i18n, queries
from horreum.gui.i18n_catalog import CATALOG
from test_object_change_write import _Scena, _oid

NOW = "2026-10-14T10:00:00+00:00"
LATER = "2026-10-14T11:00:00+00:00"
LATER2 = "2026-10-14T12:00:00+00:00"
LATER3 = "2026-10-14T13:00:00+00:00"


def _ev(con, verb=None):
    if verb is None:
        return con.execute("SELECT count(*) FROM event").fetchone()[0]
    return con.execute("SELECT count(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


def _nagrobek(con, tabela, eid):
    if tabela == "object":
        return con.execute("SELECT retired_at FROM object WHERE id = ?", (eid,)).fetchone()[0]
    return con.execute("SELECT retired_at FROM telescope WHERE id = ?", (eid,)).fetchone()[0]


def _czysto(con):
    """Inwarianty nagrobka zerowe i parytet encja == zdarzenie osi obiektu i aliasów."""
    assert set(audit.tombstone_invariants(con).values()) == {0}
    for p in audit.entity_event_parity(con):
        if p.name in ("object", "object_alias", "telescope", "frame.object_id"):
            assert p.ok, p


# ============================================================ oś OBIEKTU („Zmień obiekt…”)


def _plan(s, run_id, pozycje=None, alias="plomien"):
    target = oc.ObjectTarget(canon="IC405", catalog="IC", kind="deep_sky", alias_norm=alias,
                             card_form="IC 405")
    items = tuple(pozycje if pozycje is not None else (s.pozycja(i) for i in range(3)))
    return oc.ObjectChangePlan(run_id=run_id, target=target, items=items, skipped=())


def _przebieg(con, run_id):
    return con.execute("SELECT * FROM object_change_run WHERE run_id = ?", (run_id,)).fetchone()


def test_cykl_zmien_cofnij_ponow_cofnij_nagrobek_wskrzeszenie_reka_nietknieta(tmp_path):
    """Gest zakłada IC405 i alias wpisanej nazwy - ślad przebiegu (`made_object_id`, `made_alias_id`)
    w tej samej transakcji. Cofnięcie: nagrobek IC405, alias gestu zdjęty (`object.alias_retired`),
    obiekt znika ze skrótu „ostatnio użyte” i z mapy szukajki, wiersz i dziennik zostają. Ponowienie
    wskrzesza TEN SAM wiersz (`object.unretired`, bez drugiego `upserted`), drugie cofnięcie znów go
    zdejmuje. Spis ręki sprzed gestu wobec stanu po cofnięciu - bez ubytku.
    Mutanty: domknięcie samym statusem (`set_object_change_run_status`) - IC405 zostaje na liście;
    nagrobek bez zdjęcia aliasu - inwariant `alias_na_nagrobku_obiektu`; wskrzeszenie INSERT-em -
    UNIQUE kanonu wybucha."""
    s = _Scena(tmp_path)
    con = s.con
    przed = audit.human_facts_census(con)
    run = s.stage(_plan(s, "R1"))
    writeback.commit_object_change(con, run, now=NOW)
    ic = _oid(con, "IC405")
    alias = con.execute("SELECT id, source FROM object_alias WHERE alias_norm = 'plomien'").fetchone()
    assert alias["source"] == "user"
    r = _przebieg(con, "R1")
    assert (r["made_object_id"], r["made_alias_id"]) == (ic, alias["id"])
    assert "IC405" in {x["canon"] for x in queries.recent_hand_objects(con)}

    wynik = writeback.undo_object_change(con, run, now=LATER)
    assert len(wynik.applied) == 3
    assert _nagrobek(con, "object", ic) == LATER
    assert _przebieg(con, "R1")["status"] == "undone"
    assert con.execute("SELECT count(*) FROM object_alias WHERE object_id = ?", (ic,)).fetchone()[0] == 0
    [zdjety] = [json.loads(p[0]) for p in con.execute(
        "SELECT payload FROM event WHERE verb = 'object.alias_retired'")]
    assert zdjety == {"alias_norm": "plomien", "source": "user", "run_id": "R1"}
    assert (_ev(con, "object.retired"), _ev(con, "object.upserted")) == (1, 2)   # Sh2-229 + IC405
    assert "IC405" not in {x["canon"] for x in queries.recent_hand_objects(con)}
    assert "IC405" not in queries.object_alias_index(con)
    _czysto(con)
    spadki = audit.human_facts_census(con).spadki(
        przed, audit.path_to_header_since(con, przed.event_watermark))
    assert spadki == {}

    # drugie domknięcie domkniętego przebiegu nie sięga po obiekt (bez zdarzeń)
    n = _ev(con)
    writeback.undo_object_change(con, run, now=LATER)
    assert _ev(con) == n

    writeback.commit_object_change(con, s.stage(_plan(s, "R2")), now=LATER2)
    assert _oid(con, "IC405") == ic and _nagrobek(con, "object", ic) is None
    assert (_ev(con, "object.unretired"), _ev(con, "object.upserted")) == (1, 2)
    assert _przebieg(con, "R2")["made_object_id"] == ic
    writeback.undo_object_change(con, "R2", now=LATER3)
    assert _nagrobek(con, "object", ic) == LATER3 and _ev(con, "object.retired") == 2
    _czysto(con)


def _obca_klatka(con, sha="obca", source="header", oid=None):
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="light", filetype="fits", camera_id=None,
                               now=NOW)
    if oid is not None:
        repo.assign_object(con, frame_id=fid, object_id=oid, object_source=source, now=NOW)
    return fid


def test_odmowa_obiekt_z_klatka_spoza_gestu_zostaje(tmp_path):
    """Obiekt założony gestem dostał po drodze klatkę spoza gestu (przebieg, ręka) - cofnięcie
    zdejmuje swoje klatki, a obiekt zostaje na osi z aliasem; klinga mówi `frames`.
    Mutant: warunek klatek zdjęty - obiekt z klatką ląduje w nagrobku (inwariant czerwony)."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(_plan(s, "R1"))
    writeback.commit_object_change(con, run, now=NOW)
    ic = _oid(con, "IC405")
    _obca_klatka(con, oid=ic)
    writeback.undo_object_change(con, run, now=LATER)
    assert _nagrobek(con, "object", ic) is None
    assert con.execute("SELECT count(*) FROM object_alias WHERE object_id = ?", (ic,)).fetchone()[0] == 1
    assert repo.retire_orphan(con, axis="object", entity_id=ic, run_id="R1", now=LATER) == "frames"
    _czysto(con)


def test_odmowa_obiekt_pamietany_przez_nagrobek_klatki(tmp_path):
    """Nagrobek klatki (`object_cleared_id`) pamięta obiekt gestu - „Przywróć” przypiąłby ją do
    obiektu spoza osi, więc klinga odmawia (`cleared_memory`).
    Mutant: warunek pamięci zdjęty - inwariant `pamiec_na_nagrobku_obiektu` = 1."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(_plan(s, "R1"))
    writeback.commit_object_change(con, run, now=NOW)
    ic = _oid(con, "IC405")
    fid = _obca_klatka(con, oid=ic, source="user")
    repo.clear_object_assignment(con, frame_ids=[fid], now=NOW)
    writeback.undo_object_change(con, run, now=LATER)
    assert _nagrobek(con, "object", ic) is None
    assert repo.retire_orphan(con, axis="object", entity_id=ic, run_id="R1",
                              now=LATER) == "cleared_memory"
    _czysto(con)


def test_odmowa_obiekt_z_obcym_aliasem(tmp_path):
    """Alias spoza gestu (słownik, inny przebieg, ręka sprzed gestu) - własności nie wyprowadzamy
    z `source`, więc obiekt zostaje razem z aliasem gestu (`foreign_alias`).
    Mutant: zdejmowanie WSZYSTKICH aliasów obiektu - obcy alias ginie z bazy."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(_plan(s, "R1"))
    writeback.commit_object_change(con, run, now=NOW)
    ic = _oid(con, "IC405")
    repo.add_object_alias(con, alias_norm="obcanazwa", object_id=ic, source="curated", now=NOW)
    writeback.undo_object_change(con, run, now=LATER)
    assert _nagrobek(con, "object", ic) is None
    klucze = {r[0] for r in con.execute("SELECT alias_norm FROM object_alias WHERE object_id = ?",
                                        (ic,))}
    assert klucze == {"plomien", "obcanazwa"}
    assert repo.retire_orphan(con, axis="object", entity_id=ic, run_id="R1",
                              now=LATER) == "foreign_alias"


def _klatka_z_kopia(con, sha, path):
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="light", filetype="fits", camera_id=None,
                               now=NOW)
    lid, _ = repo.add_location(con, frame_id=fid, volume="V", path=path, now=NOW)
    return fid, lid


def _przebieg_bazy(con, run_id, fid, lid, path, canon, expected, now=NOW):
    """Przebieg „Zmień obiekt…” bez plików (pozycja bez przeniesienia i karty) - krok bazy klingi."""
    cel = oc.ObjectTarget(canon=canon, catalog=None, kind="deep_sky", alias_norm=None,
                          card_form=canon)
    poz = oc.ObjectChangeItem(frame_id=fid, location_id=lid, old_path=path, new_path=None, mkdirs=(),
                              card_op=None, card_old=None, card_new=None,
                              expected_header_hash=None, expected_mtime=None,
                              expected_object=expected, object_change=True)
    repo.stage_object_change(con, plan=oc.ObjectChangePlan(run_id=run_id, target=cel, items=(poz,),
                                                           skipped=()), now=now)
    item = con.execute("SELECT id FROM pending_object_change WHERE run_id = ?",
                       (run_id,)).fetchone()[0]
    assert repo.apply_object_change_item(con, item_id=item, now=now) == "assigned"
    repo.set_object_change_run_status(con, run_id=run_id, status="applied")
    return item


def _cofnij_baze(con, item, run_id, now=LATER):
    repo.set_object_change_undo_phase(con, item_id=item, phase="card")
    repo.set_object_change_undo_phase(con, item_id=item, phase="file")
    repo.undo_object_change_db(con, item_id=item, now=now)
    return repo.close_object_change_undo(con, run_id=run_id, now=now)


def test_odmowa_obiekt_w_innym_zywym_przebiegu(tmp_path):
    """Drugi przebieg przeniósł klatkę z obiektu gestu dalej (stan sprzed = ten obiekt) i nie jest
    cofnięty: jego cofnięcie przywróciłoby klatkę do obiektu, więc nagrobek czeka (`live_run`).
    Po cofnięciu drugiego przebiegu domknięcie pierwszego już nic nie robi (przebieg `undone`).
    Mutant: warunek żywych przebiegów zdjęty - nagrobek, a cofnięcie drugiego wraca na nagrobek."""
    con = db.open_db(str(tmp_path / "h.db"))
    fid, lid = _klatka_z_kopia(con, "a", "X:\\L\\a.fits")
    i1 = _przebieg_bazy(con, "R1", fid, lid, "X:\\L\\a.fits", "ZZ1", (None, None, None))
    zz1 = _oid(con, "ZZ1")
    assert _przebieg(con, "R1")["made_object_id"] == zz1
    i3 = _przebieg_bazy(con, "R3", fid, lid, "X:\\L\\a.fits", "ZZ3", (zz1, "user", None))
    assert _cofnij_baze(con, i1, "R1") == "live_run"
    assert _nagrobek(con, "object", zz1) is None
    _cofnij_baze(con, i3, "R3")                    # R3 cofnięty: klatka wraca na ZZ1 (żywy)
    assert con.execute("SELECT object_id FROM frame WHERE id = ?", (fid,)).fetchone()[0] == zz1
    _czysto(con)
    con.close()


def test_wskrzeszenie_strzezone_para_katalogowa(tmp_path, monkeypatch):
    """Nagrobek obiektu, którego kanon jest dziś KLUCZEM pary `catalog_xref`, nie wraca: kanon
    nazywa cel pary. Przekierowanie robi drabina; wołający z gołym kanonem dostaje `ValueError`
    i zero zapisu. Kanon nadal kanoniczny - wraca (`unretired`), nowym obiektem nie jest.
    Mutant: wskrzeszenie bez strażnika `xref` - stara tożsamość obok celu pary."""
    con = db.open_db(str(tmp_path / "h.db"))
    fid, lid = _klatka_z_kopia(con, "a", "X:\\L\\a.fits")
    item = _przebieg_bazy(con, "R1", fid, lid, "X:\\L\\a.fits", "ZZ1", (None, None, None))
    assert _cofnij_baze(con, item, "R1") is None
    zz1 = _oid(con, "ZZ1")
    assert _nagrobek(con, "object", zz1) == LATER
    monkeypatch.setattr(repo, "xref", lambda c: "NGC598" if c == "ZZ1" else c)
    n = _ev(con)
    with pytest.raises(ValueError, match="NGC598"):
        repo.upsert_object(con, canon="ZZ1", catalog=None, kind="deep_sky", now=LATER2)
    assert _ev(con) == n and _nagrobek(con, "object", zz1) == LATER
    monkeypatch.undo()
    assert repo.upsert_object(con, canon="ZZ1", catalog=None, kind="deep_sky",
                              now=LATER2) == (zz1, "unretired")
    assert repo.upsert_object(con, canon="ZZ1", catalog=None, kind="deep_sky",
                              now=LATER2) == (zz1, "existing")
    con.close()


def test_resolver_wskrzesza_nazwa_z_pliku_i_liczy_osobno(tmp_path):
    """Klatka zeznaje nazwę nagrobka - przebieg resolvera przywraca TEN SAM obiekt; raport mówi
    „przywrócone”, nie „nowe”. Mutant: `objects_new += made` (str) albo liczenie wskrzeszenia jako
    nowego obiektu."""
    con = db.open_db(str(tmp_path / "h.db"))
    fid, lid = _klatka_z_kopia(con, "a", "X:\\L\\a.fits")
    item = _przebieg_bazy(con, "R1", fid, lid, "X:\\L\\a.fits", "NGC7000", (None, None, None))
    _cofnij_baze(con, item, "R1")
    ngc = _oid(con, "NGC7000")
    assert _nagrobek(con, "object", ngc) == LATER
    b, _ = repo.upsert_frame(con, sha1_data="b", kind="light", filetype="fits", camera_id=None,
                             now=NOW)
    repo.record_header(con, frame_id=b, raw_json=json.dumps({"OBJECT": "NGC 7000"}), now=NOW,
                       object_raw="NGC 7000")
    s = resolver.run_resolver(con, LATER2)
    assert (s.objects_new, s.objects_unretired) == (0, 1)
    assert _nagrobek(con, "object", ngc) is None
    assert con.execute("SELECT object_id FROM frame WHERE id = ?", (b,)).fetchone()[0] == ngc
    widok = pytest.importorskip("horreum.gui.pipeline").PipelineView
    assert i18n.t_plural("pipeline.fmt.resolve_unretired", 1) in widok._format_resolve(None, s)
    con.close()


# ============================================================ oś TELESKOPU („Dopisz nowy…”)


def _kamera(con):
    cid, _ = repo.upsert_camera(con, model_canon="ASI2600MM", pixel_um=3.76, is_mono=1,
                                is_mono_source="header", raw_instrume="ASI2600MM", now=NOW)
    return cid


def _klatka(con, sha, *, telescop, focal, f_ratio=None, camera_id):
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="light", filetype="fits",
                               camera_id=camera_id, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json=json.dumps({"NAXIS1": 6248, "NAXIS2": 4176}),
                       now=NOW, telescop=telescop, focallen=focal, focratio_raw=f_ratio,
                       xpixsz=3.76)
    return fid


def _baza_teleskopow(tmp_path):
    """RC8 1600/f8 (park) z trzema klatkami, dwie klatki RC8 z 800 mm (kubełek ogniskowej, zestaw
    automatu) i klatka bez TELESCOP z 700 mm (zestawu brak, powód przeglądu w dzienniku)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    con = db.open_db(str(tmp_path / "t.db"))
    cam = _kamera(con)
    for i in range(3):
        _klatka(con, f"rc{i}", telescop="RC8", focal=1600, f_ratio=8.0, camera_id=cam)
    obce = [_klatka(con, f"o{i}", telescop="RC8", focal=800, f_ratio=8.0, camera_id=cam)
            for i in range(2)]
    obce.append(_klatka(con, "bez", telescop=None, focal=700, camera_id=cam))
    grouper.run_grouper(con, NOW)
    rc8 = con.execute("SELECT id FROM telescope WHERE telescop_canon = 'RC8'").fetchone()[0]
    repo.set_telescope_park(con, telescope_id=rc8, in_park=1, now=NOW)
    return con, cam, obce, rc8


def _zestawy(con, fids):
    return {f: tuple(con.execute("SELECT config_id, config_source FROM frame WHERE id = ?",
                                 (f,)).fetchone()) for f in fids}


def _dopisz(con, obce, rc8, now=NOW, focal=800.0, f_ratio=None):
    tid, g = repo.user_assign_config_new_telescope(
        con, frame_ids=obce, name="RC8 0.5x", focal_mm=focal, f_ratio=f_ratio, in_park=1,
        source_telescope_id=rc8, now=now)
    assert g.assigned == len(obce)
    return tid


def test_dopisz_cofnij_klatki_wracaja_teleskop_w_nagrobku_listy_i_reka(tmp_path):
    """„Dopisz nowy…” → „Cofnij dopisanie”: każda klatka wraca do zestawu sprzed gestu (automat
    i pustka - ta z powodem przeglądu z bieżącego epizodu), teleskop dostaje nagrobek z polami ręki
    nietkniętymi, wartość z plików RC8 liczy się na nowo. Listy (Oś, park, facety, Znajdź, planer)
    nie widzą nagrobka; nazwy folderów zestawów liczą pełną tabelę (stałe). Dziennik tylko rośnie.
    Spis ręki sprzed gestu wobec stanu po cofnięciu - bez ubytku, także `telescope_hand`; drugie
    cofnięcie - odmowa `undone` bez zdarzeń.
    Mutanty: powrót do pustki zamiast zestawu z `config.unassigned`; nagrobek zerujący pola ręki
    (spis: ubytek `telescope_hand`); lista Osi bez filtra (nagrobek z 0 klatek na liście)."""
    con, _cam, obce, rc8 = _baza_teleskopow(tmp_path)
    przed = audit.human_facts_census(con)
    zestawy = _zestawy(con, obce)
    luka = audit.config_review_reason_gap(con)
    zdarzenia = _ev(con)
    tid = _dopisz(con, obce, rc8)
    cfg_nowy = {c for c, _ in _zestawy(con, obce).values()}
    reka = con.execute("SELECT label, status, focal_user, in_park FROM telescope WHERE id = ?",
                       (tid,)).fetchone()
    assert "RC8 0.5x" in sky.park(con)

    w = repo.undo_new_telescope(con, telescope_id=tid, now=LATER)
    assert w == repo.NewTelescopeUndo(tid, restored=3, kept=0, retired=True, refusal=None)
    assert _zestawy(con, obce) == zestawy
    assert audit.config_review_reason_gap(con) == luka
    assert _nagrobek(con, "telescope", tid) == LATER
    assert tuple(con.execute("SELECT label, status, focal_user, in_park FROM telescope WHERE id = ?",
                             (tid,)).fetchone()) == tuple(reka)
    assert _ev(con) > zdarzenia and _ev(con, "telescope.retired") == 1
    assert tid not in {r["id"] for r in queries.active_telescopes(con)}
    assert tid not in {r["id"] for r in queries.park_overview(con)}
    assert tid not in {r["id"] for r in queries.telescope_facets(con)}
    assert tid not in {r["telescope_id"] for r in queries.find_rigs(con)}
    assert sky.park(con) == ("RC8",)
    assert cfg_nowy <= set(projection.zestawy_configow(con))
    _czysto(con)
    po = audit.human_facts_census(con)
    assert po.spadki(przed, gesty_teleskopu=audit.telescope_hand_gestures_since(
        con, przed.event_watermark)) == {}

    n = _ev(con)
    assert repo.undo_new_telescope(con, telescope_id=tid, now=LATER2).refusal == "undone"
    assert _ev(con) == n
    con.close()


@pytest.mark.parametrize("po_gescie,powod", [
    ("etykieta", "hand_after"), ("park", "hand_after"), ("optyka", "hand_after"),
    ("scalenie", "members"), ("w_scaleniu", "merged"), ("profil", "profile"),
    ("fakt", "calibration_fact")])
def test_odmowa_cofniecia_dopisania_bez_zapisu(tmp_path, po_gescie, powod):
    """Teleskop żyje już poza gestem (ręka po geście, scalenie, profil kalibracji, fakt przepisu) -
    „Cofnij dopisanie” odmawia ZANIM ruszy klatki: zero zapisu, klatki dalej przy teleskopie.
    Zdarzenia samego gestu (etykieta, zatwierdzenie, optyka, park) odmową nie są (test cyklu).
    Mutant: warunek ręki liczony od początku teleskopu - każde cofnięcie odmawia; albo warunki
    sprawdzane PO rozpięciu klatek - pół-cofnięcie."""
    con, cam, obce, rc8 = _baza_teleskopow(tmp_path)
    tid = _dopisz(con, obce, rc8)
    if po_gescie == "etykieta":
        repo.label_telescope(con, telescope_id=tid, label="RC8 z reduktorem", now=LATER)
    elif po_gescie == "park":
        repo.set_telescope_park(con, telescope_id=tid, in_park=0, now=LATER)
    elif po_gescie == "optyka":
        repo.set_telescope_focal(con, telescope_id=tid, focal_mm=810, now=LATER)
    elif po_gescie == "scalenie":
        inny, _ = repo.propose_telescope(con, telescop_canon="Inny", now=LATER)
        repo.merge_telescope(con, source_id=inny, target_id=tid, now=LATER)
    elif po_gescie == "w_scaleniu":
        repo.merge_telescope(con, source_id=tid, target_id=rc8, now=LATER)
    elif po_gescie == "profil":
        repo.upsert_calibration_profile(con, profile_key="flat|t", recipe_class="flat",
                                        camera_id=cam, xbinning=1, telescope_id=tid, now=LATER)
    else:
        repo.record_calibration_fact(con, frame_id=obce[0], key="telescope_id", value=tid,
                                     source="user", now=LATER, actor="user:local")
    stan, n = _zestawy(con, obce), _ev(con)
    w = repo.undo_new_telescope(con, telescope_id=tid, now=LATER2)
    assert (w.restored, w.kept, w.retired, w.refusal) == (0, 0, False, powod)
    assert _zestawy(con, obce) == stan and _ev(con) == n
    assert _nagrobek(con, "telescope", tid) is None
    assert con.execute("SELECT undone_at FROM telescope_add").fetchone()[0] is None
    con.close()


def test_cas_klatka_zmieniona_po_gescie_zostaje(tmp_path):
    """Klatki przepięte ręką na inny teleskop po geście zostają tam (raport `kept`), reszta wraca;
    przepięcie przeliczyło wartość z plików nowego teleskopu z aktorem ręki (800 → 700 mm) - to
    pochodna, nie fakt ręki, więc nagrobek idzie. Klatka dopięta do nowego teleskopu spoza gestu
    trzyma go na osi (`frames`), choć klatki gestu wróciły.
    Mutanty: CAS zdjęty (przepięta klatka wraca do RC8 automatu); `telescope.optics_derived`
    liczone jako ręka (odmowa `hand_after`)."""
    con, cam, obce, rc8 = _baza_teleskopow(tmp_path)
    przed = _zestawy(con, obce)
    tid = _dopisz(con, obce, rc8)
    granica = con.execute("SELECT last_event_id FROM telescope_add").fetchone()[0]
    a140, _ = repo.propose_telescope(con, telescop_canon="A140R", now=LATER)
    repo.user_assign_config(con, frame_ids=obce[:2], telescope_id=a140, now=LATER, overwrite=True)
    assert con.execute(
        "SELECT count(*) FROM event WHERE verb = 'telescope.optics_derived' AND target = ? "
        "AND actor LIKE 'user:%' AND id > ?", (f"telescope:{tid}", granica)).fetchone()[0] == 1
    w = repo.undo_new_telescope(con, telescope_id=tid, now=LATER2)
    assert (w.restored, w.kept, w.retired) == (1, 2, True)
    po = _zestawy(con, obce)
    assert po[obce[2]] == przed[obce[2]]
    assert all(po[f][1] == "user" and po[f] != przed[f] for f in obce[:2])

    con2, _cam, obce2, rc8b = _baza_teleskopow(tmp_path / "b")
    tid2 = _dopisz(con2, obce2, rc8b)
    extra = _klatka(con2, "x", telescop="RC8", focal=800, f_ratio=8.0, camera_id=_cam)
    repo.user_assign_config(con2, frame_ids=[extra], telescope_id=tid2, now=LATER, overwrite=True)
    w2 = repo.undo_new_telescope(con2, telescope_id=tid2, now=LATER2)
    assert (w2.restored, w2.kept, w2.retired, w2.refusal) == (3, 0, False, "frames")
    assert _nagrobek(con2, "telescope", tid2) is None
    assert tid2 in {r["id"] for r in queries.active_telescopes(con2)}
    con.close()
    con2.close()


def test_cofniecie_nie_wraca_klatek_do_nagrobka_innego_dopisania(tmp_path):
    """Gest A dopisuje teleskop A, gest B przepina TE SAME klatki na teleskop B, „Cofnij dopisanie”
    A zdejmuje A (klatki są już przy B - zostają), a „Cofnij dopisanie” B przypiąłby je z powrotem do
    zestawu nagrobka A. Odmowa `source_retired` CAŁEGO cofnięcia, zero zapisu, inwarianty zerowe.
    Mutant: powrót bez sprawdzenia teleskopu zestawu sprzed gestu (klatki na nagrobku)."""
    con, _cam, obce, rc8 = _baza_teleskopow(tmp_path)
    ta = _dopisz(con, obce, rc8)
    tb, g = repo.user_assign_config_new_telescope(con, frame_ids=obce, name="RC8 B", focal_mm=790.0,
                                                  now=LATER)
    assert g.assigned == 3
    wa = repo.undo_new_telescope(con, telescope_id=ta, now=LATER2)
    assert (wa.restored, wa.kept, wa.retired) == (0, 3, True)
    stan, n = _zestawy(con, obce), _ev(con)
    wb = repo.undo_new_telescope(con, telescope_id=tb, now=LATER3)
    assert (wb.restored, wb.kept, wb.retired, wb.refusal) == (0, 0, False, "source_retired")
    assert _zestawy(con, obce) == stan and _ev(con) == n
    assert con.execute("SELECT undone_at FROM telescope_add WHERE telescope_id = ?",
                       (tb,)).fetchone()[0] is None
    _czysto(con)
    con.close()


def test_cas_aba_przepiecie_i_powrot_reka_po_gescie_zostaje(tmp_path):
    """Klatka przepięta ręką po geście i przypięta ręką Z POWROTEM do zestawu gestu ma tę samą parę
    (zestaw, `user`), ale niesie decyzję późniejszą niż gest - cofnięcie jej nie rusza (`kept`),
    a teleskop zostaje na osi z tą klatką (`frames`).
    Mutant: CAS na samej wartości (klatka wraca do RC8 automatu mimo decyzji ręki)."""
    con, _cam, obce, rc8 = _baza_teleskopow(tmp_path)
    przed = _zestawy(con, obce)
    tid = _dopisz(con, obce, rc8)
    w_gescie = _zestawy(con, obce)[obce[0]]
    repo.user_assign_config(con, frame_ids=[obce[0]], telescope_id=rc8, now=LATER, overwrite=True)
    repo.user_assign_config(con, frame_ids=[obce[0]], telescope_id=tid, now=LATER, overwrite=True)
    assert _zestawy(con, obce)[obce[0]] == w_gescie
    w = repo.undo_new_telescope(con, telescope_id=tid, now=LATER2)
    assert (w.restored, w.kept, w.retired, w.refusal) == (2, 1, False, "frames")
    po = _zestawy(con, obce)
    assert po[obce[0]] == w_gescie and po[obce[1]] == przed[obce[1]] and po[obce[2]] == przed[obce[2]]
    con.close()


def test_powod_przegladu_wraca_tylko_aktywny_sprzed_gestu(tmp_path):
    """Klatka bez zestawu, której powód przeglądu pochodzi z WCZEŚNIEJSZEGO epizodu (po nim był zestaw
    ręką i odpięcie bez nowego przeglądu): cofnięcie wraca ją do pustki BEZ `config.review` - luka
    powodu taka sama jak przed gestem, nie „naprawiona” starym powodem.
    Mutant: ostatni `config.review` sprzed gestu bez granicy epizodu."""
    con, _cam, obce, rc8 = _baza_teleskopow(tmp_path)
    bez = obce[2]
    repo.user_assign_config(con, frame_ids=[bez], telescope_id=rc8, now=NOW, overwrite=True)
    repo.unassign_config(con, frame_id=bez, now=NOW)
    luka = audit.config_review_reason_gap(con)
    assert luka == 1
    tid = _dopisz(con, obce, rc8)
    przeglady = _ev(con, "config.review")
    w = repo.undo_new_telescope(con, telescope_id=tid, now=LATER)
    assert (w.restored, w.retired) == (3, True)
    assert _ev(con, "config.review") == przeglady
    assert audit.config_review_reason_gap(con) == luka
    con.close()


def _wyscig(monkeypatch, con, klinga, rywal):
    """Rdzeń wskrzeszenia (`klinga`) na `con` najpierw oddaje pierwszeństwo rywalowi (druga sesja
    wskrzesza nagrobek i zatwierdza) - szybka ścieżka `con` widziała jeszcze nagrobek."""
    oryginal = getattr(repo, klinga)
    stan = {"raz": True}

    def _z_rywalem(c, **kw):
        if c is con and stan["raz"]:
            stan["raz"] = False
            rywal()
        return oryginal(c, **kw)
    monkeypatch.setattr(repo, klinga, _z_rywalem)


def test_wskrzeszenie_rownolegle_raz(tmp_path, monkeypatch):
    """Dwie sesje widzą ten sam nagrobek: druga wskrzesza i zatwierdza między szybką ścieżką pierwszej
    a jej zapisem - warunkowy `UPDATE` pierwszej nic nie zmienia, wynik `EXISTING` z `rowcount`;
    jedno `*.unretired`. Teleskop (`propose_telescope`) i obiekt (`upsert_object`).
    Mutant: decyzja z odczytu sprzed zapisu albo bezwarunkowy `UPDATE` (dwa `unretired`)."""
    con, _cam, obce, rc8 = _baza_teleskopow(tmp_path)
    tid = _dopisz(con, obce, rc8)
    repo.undo_new_telescope(con, telescope_id=tid, now=LATER)
    fid, lid = _klatka_z_kopia(con, "z", "X:\\L\\z.fits")
    item = _przebieg_bazy(con, "R1", fid, lid, "X:\\L\\z.fits", "ZZ1", (None, None, None))
    _cofnij_baze(con, item, "R1")
    zz1 = _oid(con, "ZZ1")
    rywal = db.connect(str(tmp_path / "t.db"))
    _wyscig(monkeypatch, con, "_unretire_telescope_tx",
            lambda: repo.propose_telescope(rywal, telescop_canon="RC8 0.5x", now=LATER2))
    assert repo.propose_telescope(con, telescop_canon="RC8 0.5x", now=LATER2) \
        == (tid, repo.Made.EXISTING)
    assert _ev(con, "telescope.unretired") == 1
    _wyscig(monkeypatch, con, "_unretire_object_tx",
            lambda: repo.upsert_object(rywal, canon="ZZ1", catalog=None, kind="deep_sky",
                                       now=LATER2))
    assert repo.upsert_object(con, canon="ZZ1", catalog=None, kind="deep_sky",
                              now=LATER2) == (zz1, repo.Made.EXISTING)
    assert _ev(con, "object.unretired") == 1
    rywal.close()
    con.close()


def test_wynik_zalozenia_nie_jest_prawda_logiczna(tmp_path):
    """Dawny kontrakt był boolem „nowy wiersz” - `if made:` policzyłby `EXISTING` jako nowy po cichu.
    `bool()` wyniku rzuca `TypeError` (EXPECT), porównanie z napisem działa.
    Mutant: wynik jako goły `str`."""
    con = db.open_db(str(tmp_path / "h.db"))
    _, made = repo.upsert_object(con, canon="NGC7000", catalog="NGC", kind="deep_sky", now=NOW)
    _, jest = repo.propose_telescope(con, telescop_canon="RC8", now=NOW)
    assert made == "created" and made is repo.Made.CREATED and jest == "created"
    for wynik in (made, jest, repo.propose_telescope(con, telescop_canon="RC8", now=NOW)[1]):
        with pytest.raises(TypeError):
            bool(wynik)
    con.close()


def test_cli_park_nie_zna_nagrobka(tmp_path, capsys):
    """`horreum park`: nagrobek nie stoi w przeglądzie, a `--add <nagrobek>` odmawia kodem 2 z listą
    kanonicznych bez niego (klinga parku i tak by mu odmówiła).
    Mutant: słownik CLI bez filtra nagrobka (`--add` wybucha `ValueError` klingi)."""
    from horreum import cli
    con, _cam, obce, rc8 = _baza_teleskopow(tmp_path)
    tid = _dopisz(con, obce, rc8)
    repo.undo_new_telescope(con, telescope_id=tid, now=LATER)
    con.close()
    path = str(tmp_path / "t.db")
    assert cli.main(["park", path]) == 0
    assert "RC8 0.5x" not in capsys.readouterr().out
    assert cli.main(["park", path, "--add", "RC8 0.5x"]) == 2
    out = capsys.readouterr().out
    assert "nieznany" in out and "RC8 0.5x" not in out.split("Kanoniczne:")[1]


def test_klingi_osi_odmawiaja_nagrobkowi(tmp_path):
    """Publiczne klingi zapisu teleskopu odmawiają na nagrobku (`ValueError`, zero zapisu): etykieta,
    zatwierdzenie, optyka, park, scalenie w obie strony, przypięcie klatek.
    Mutant: guard nagrobka zdjęty z `_telescope_row` - etykieta na nagrobku przechodzi."""
    con, _cam, obce, rc8 = _baza_teleskopow(tmp_path)
    tid = _dopisz(con, obce, rc8)
    repo.undo_new_telescope(con, telescope_id=tid, now=LATER)
    n = _ev(con)
    for gest in (lambda: repo.label_telescope(con, telescope_id=tid, label="X", now=LATER2),
                 lambda: repo.approve_telescope(con, telescope_id=tid, now=LATER2),
                 lambda: repo.set_telescope_focal(con, telescope_id=tid, focal_mm=700, now=LATER2),
                 lambda: repo.clear_telescope_f_ratio(con, telescope_id=tid, now=LATER2),
                 lambda: repo.set_telescope_park(con, telescope_id=tid, in_park=0, now=LATER2),
                 lambda: repo.merge_telescope(con, source_id=tid, target_id=rc8, now=LATER2),
                 lambda: repo.merge_telescope(con, source_id=rc8, target_id=tid, now=LATER2),
                 lambda: repo.user_assign_config(con, frame_ids=obce, telescope_id=tid,
                                                 now=LATER2, overwrite=True)):
        with pytest.raises(ValueError, match="nagrobek"):
            gest()
    assert _ev(con) == n
    con.close()


def test_wskrzeszenie_teleskopu_dopisz_i_przebieg(tmp_path):
    """Nazwa nagrobka nie jest zajęta: „Dopisz nowy…” pod nią przywraca TEN SAM wiersz
    (`telescope.unretired`, bez drugiego `proposed` - parytet osi) z polami z okna; drugie cofnięcie
    działa na nowym śladzie gestu. Grouper z tą nazwą w nagłówku też przywraca wiersz i liczy go
    osobno od nowych teleskopów.
    Mutanty: `valid_telescope_name` liczy nagrobek jako zajęty; wskrzeszenie `proposed`-em
    (parytet `telescope` czerwony); `telescopes_proposed += made`."""
    con, cam, obce, rc8 = _baza_teleskopow(tmp_path)
    tid = _dopisz(con, obce, rc8, f_ratio=4.0)
    repo.undo_new_telescope(con, telescope_id=tid, now=LATER)
    assert repo.valid_telescope_name(con, "rc8 0.5x") == "rc8 0.5x"
    proposed = _ev(con, "telescope.proposed")
    assert _dopisz(con, obce, rc8, now=LATER2, focal=790.0) == tid
    t = con.execute("SELECT retired_at, focal_user, f_ratio_user FROM telescope WHERE id = ?",
                    (tid,)).fetchone()
    assert tuple(t) == (None, 790.0, None)               # f/ z okna (puste), nie sprzed nagrobka
    assert (_ev(con, "telescope.proposed"), _ev(con, "telescope.unretired")) == (proposed, 1)
    assert con.execute("SELECT count(*) FROM telescope_add").fetchone()[0] == 2
    _czysto(con)
    w = repo.undo_new_telescope(con, telescope_id=tid, now=LATER3)
    assert w.retired and _ev(con, "telescope.retired") == 2

    _klatka(con, "n0", telescop="RC8 0.5x", focal=800, camera_id=cam)
    s = grouper.run_grouper(con, LATER3)
    assert (s.telescopes_proposed, s.telescopes_unretired) == (0, 1)
    assert _nagrobek(con, "telescope", tid) is None
    assert repo.propose_telescope(con, telescop_canon="RC8 0.5X", now=LATER3) == (tid, "existing")
    widok = pytest.importorskip("horreum.gui.pipeline").PipelineView
    assert i18n.t_plural("pipeline.fmt.group_unretired", 1) in widok._format_group(None, s)
    _czysto(con)
    con.close()


def test_klinga_nagrobka_zdejmuje_wylacznie_zalozone_przez_gest(tmp_path):
    """Ślad, który nie nazywa encji, to błąd wołającego (EXPECT): przebieg bez `made_object_id`
    i ślad dopisania innego teleskopu → `ValueError`, zero zapisu.
    Mutant: klinga bez sprawdzenia śladu - zdejmuje dowolny obiekt bez klatek."""
    con, _cam, obce, rc8 = _baza_teleskopow(tmp_path)
    tid = _dopisz(con, obce, rc8)
    add = con.execute("SELECT id FROM telescope_add").fetchone()[0]
    with pytest.raises(ValueError, match="nie założył"):
        repo.retire_orphan(con, axis="telescope", entity_id=rc8, add_id=add, now=LATER)
    fid, lid = _klatka_z_kopia(con, "z", "X:\\L\\z.fits")
    oid, _ = repo.upsert_object(con, canon="ZZ9", catalog=None, kind="deep_sky", now=NOW)
    _przebieg_bazy(con, "R9", fid, lid, "X:\\L\\z.fits", "ZZ9", (None, None, None))
    assert _przebieg(con, "R9")["made_object_id"] is None      # obiekt był przed gestem
    with pytest.raises(ValueError, match="nie założył"):
        repo.retire_orphan(con, axis="object", entity_id=oid, run_id="R9", now=LATER)
    assert _nagrobek(con, "telescope", rc8) is None and _nagrobek(con, "object", oid) is None
    con.close()


def test_inwarianty_nagrobka_lapia_wstrzykniecie(tmp_path):
    """Gołe SQL obchodzi klingę: klatka, pamięć nagrobka klatki i alias na nagrobku obiektu, klatka,
    profil i fakt przepisu `telescope_id` na nagrobku teleskopu - każdy licznik widzi swoje naruszenie.
    Mutant: inwariant liczony bez `retired_at` (zawsze zero)."""
    con, cam, obce, rc8 = _baza_teleskopow(tmp_path)
    oid, _ = repo.upsert_object(con, canon="ZZ1", catalog=None, kind="deep_sky", now=NOW)
    repo.assign_object(con, frame_id=obce[0], object_id=oid, object_source="header", now=NOW)
    repo.add_object_alias(con, alias_norm="zz", object_id=oid, source="curated", now=NOW)
    repo.upsert_calibration_profile(con, profile_key="flat|r", recipe_class="flat", camera_id=cam,
                                    xbinning=1, telescope_id=rc8, now=NOW)
    repo.record_calibration_fact(con, frame_id=obce[2], key="telescope_id", value=rc8,
                                 source="user", now=NOW, actor="user:local")
    with con:
        con.execute("UPDATE object SET retired_at = 't' WHERE id = ?", (oid,))
        con.execute("UPDATE telescope SET retired_at = 't' WHERE id = ?", (rc8,))
        con.execute("UPDATE frame SET object_id = NULL, object_source = 'user_cleared', "
                    "object_cleared_id = ? WHERE id = ?", (oid, obce[1]))
    assert audit.tombstone_invariants(con) == {
        "klatka_na_nagrobku_obiektu": 1, "pamiec_na_nagrobku_obiektu": 1,
        "alias_na_nagrobku_obiektu": 1, "klatka_na_nagrobku_teleskopu": 5,
        "profil_na_nagrobku_teleskopu": 1, "fakt_na_nagrobku_teleskopu": 1}
    con.close()


# ============================================================ katalog zdań (PL + EN)


def test_kazdy_powod_odmowy_ma_zdanie_PL_i_EN():
    """Powierzchnia składa zdanie odmowy z tokenu klingi (`RETIRE_REFUSALS`) - klucz dynamiczny,
    którego bramka literałów nie widzi. Mutant: nowy token bez zdania (pasek pokazałby klucz)."""
    for token in repo.RETIRE_REFUSALS:
        wpis = CATALOG[f"object.config_undo_add.refused.{token}"]
        assert isinstance(wpis["pl"], str) and isinstance(wpis["en"], str) and wpis["en"]


@pytest.mark.parametrize("n,pl,en", [
    (1, "1 klatka wróciła", "1 frame is back"), (2, "2 klatki wróciły", "2 frames are back"),
    (4, "4 klatki wróciły", "4 frames are back"), (5, "5 klatek wróciło", "5 frames are back"),
    (12, "12 klatek wróciło", "12 frames are back"), (14, "14 klatek wróciło", "14 frames are back"),
    (22, "22 klatki wróciły", "22 frames are back")])
def test_odmiana_zdania_cofniecia_dopisania(n, pl, en):
    """Liczba klatek odmienia całe zdanie w obu językach (1, 2-4, 5, -naście, 22).
    Mutant: wpis prosty z „{n} klatek” dla każdej liczby."""
    try:
        i18n.set_lang("pl")
        assert pl in i18n.t_plural("object.config_undo_add.done", n, telescope="T")
        assert ("zostaje" if n in (1, 5, 12, 14) else "zostają") in i18n.t_plural(
            "object.config_undo_add.kept", n)
        i18n.set_lang("en")
        assert en in i18n.t_plural("object.config_undo_add.done", n, telescope="T")
    finally:
        i18n.set_lang("pl")


@pytest.mark.parametrize("n,tel,obj,en_tel", [
    (1, "1 teleskop przywrócony", "1 obiekt przywrócony", "1 telescope back"),
    (2, "2 teleskopy przywrócone", "2 obiekty przywrócone", "2 telescopes back"),
    (4, "4 teleskopy przywrócone", "4 obiekty przywrócone", "4 telescopes back"),
    (5, "5 teleskopów przywróconych", "5 obiektów przywróconych", "5 telescopes back"),
    (12, "12 teleskopów przywróconych", "12 obiektów przywróconych", "12 telescopes back"),
    (14, "14 teleskopów przywróconych", "14 obiektów przywróconych", "14 telescopes back"),
    (22, "22 teleskopy przywrócone", "22 obiekty przywrócone", "22 telescopes back")])
def test_odmiana_czlonu_przywroconych_w_raporcie_dostawy(n, tel, obj, en_tel):
    """Człon „przywrócone na oś” raportu Dostawy odmienia liczbę (1, 2-4, 5, -naście, 22).
    Mutant: wpis prosty „teleskopy przywrócone na oś {n}” (przy 1 czyta się jak liczba mnoga)."""
    try:
        i18n.set_lang("pl")
        assert tel in i18n.t_plural("pipeline.fmt.group_unretired", n)
        assert obj in i18n.t_plural("pipeline.fmt.resolve_unretired", n)
        i18n.set_lang("en")
        assert en_tel in i18n.t_plural("pipeline.fmt.group_unretired", n)
    finally:
        i18n.set_lang("pl")
