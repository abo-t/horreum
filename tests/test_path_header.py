r"""NAGŁÓWEK KONTRA ZATWIERDZONY FOLDER (E5-1, E5-2) - header-primary zostaje, ale GŁOŚNO.

Populacja naśladuje archiwum: gotowy stos XISF pod `STACKS\<OBIEKT>\...`, nagłówek bez `OBJECT`,
obiekt zatwierdzony człowiekiem z propozycji ścieżki (`object_source='path'`). Potem plik dostaje
kartę `OBJECT` (makro albo edycja zewnętrzna + skan) - stan wytwarza klinga skanu
(`repo.refresh_location` z nowym odciskiem), nie surowy UPDATE.

Bramki, których właścicielem jest ten plik:
  * **E5-1 (a)** - przepięcie klatki ze źródła słabego zostawia ślad W TRANSAKCJI przepięcia
    (`object.unassigned` z powodem i `next_object_*`), przebieg liczy je w `ResolveSummary`, a linia
    raportu Dostawy mówi o tym tylko wtedy, gdy zaszło (QUIET), z odmianą liczby.
  * **E5-1 (b)** - `human-facts --baseline` rozstrzyga PO TOŻSAMOŚCI KLATEK (migawka + znak wodny
    dziennika): przejście `path → nagłówek` BEZ zmiany obiektu nie jest ubytkiem (osobny wiersz,
    kod 0), każda inna utrata faktu ręki jest (kod 1) - także gdy suma jej nie widzi (bramka Z1).
  * **E5-2** - wiersz Porządków ze STANU: potwierdzony folder + nagłówek, którego drabina nie
    rozpoznaje albo rozpoznaje jako inny obiekt."""
import json
import os

import pytest

from horreum import audit, cli, db, repo, resolver
from horreum.gui import queries

NOW = "2026-09-26T12:00:00Z"
LATER = "2026-09-26T13:00:00Z"
R = "R:\\ASTRO_"


def _pusta():
    con = db.connect(":memory:")
    db.migrate(con)
    return con


def _stos_potwierdzony(con, folder, sha="st1"):
    """Stos pod `STACKS\\<folder>` bez `OBJECT`, zatwierdzony z propozycji ścieżki klingą gestu."""
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="master_light", filetype="xisf",
                               camera_id=None, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=None, now=NOW)
    repo.add_location(con, frame_id=fid, volume="VOL", now=NOW,
                      path=rf"{R}\STACKS\{folder}\A140R_2600MM\Ha\{folder}_Ha.xisf")
    p = next(p for p in resolver.path_proposals(con) if fid in p.frame_ids)
    g = repo.user_assign_object(con, alias_norm=None, canon=p.canon, catalog=p.catalog,
                                kind=p.kind, frame_ids=[fid], now=NOW, object_source="path")
    assert g.assigned == 1
    return fid


def _karta(con, fid, object_raw):
    """Plik dostał kartę `OBJECT` - re-skan klingą skanu (nowy odcisk nagłówka)."""
    lid = con.execute("SELECT id FROM location WHERE frame_id = ?", (fid,)).fetchone()[0]
    repo.refresh_location(con, location_id=lid, frame_id=fid, mtime=2.0, file_sha1="f2",
                          header_hash=f"h-{object_raw}", hdu_index=None, compressed=None,
                          size_bytes=None, unreadable_since=None, unreadable_kind=None,
                          unreadable_reason=None, present=1, now=LATER, raw_json="{}",
                          hot_fields={"object_raw": object_raw}, kind="master_light")


def _stan(con, fid):
    return tuple(con.execute("SELECT o.canon, f.object_source FROM frame f LEFT JOIN object o "
                             "ON o.id = f.object_id WHERE f.id = ?", (fid,)).fetchone())


def _oid(con, canon):
    return con.execute("SELECT id FROM object WHERE canon = ?", (canon,)).fetchone()[0]


def _slad(con, fid):
    """Ślad przepięcia ze źródła słabego: `(payload, reason)` odpięć klatki z kluczem `next_*`."""
    return [(json.loads(p), r) for p, r in con.execute(
        "SELECT payload, reason FROM event WHERE verb = 'object.unassigned' AND target = ? "
        "AND json_extract(payload, '$.next_object_id') IS NOT NULL ORDER BY id",
        (f"frame:{fid}",))]


def _odniesienie(con):
    """Spis „przed" tak, jak zapisuje go `human-facts --json` i wczytuje `--baseline`."""
    return audit.HumanFacts(**json.loads(json.dumps(audit.human_facts_census(con).snapshot)))


def _porownaj(con, przed):
    po = audit.human_facts_census(con)
    przejete = audit.path_to_header_since(con, przed.event_watermark)
    return po.spadki(przed, przejete), po.reka_obiektu(przed, przejete)


POWOD = "nagłówek przegłosował potwierdzenie ze ścieżki (header-primary)"


# ═══════════════════════════════════════════════════ E5-1 (a) - przebieg mówi GŁOŚNO


def test_naglowek_z_INNYM_obiektem_przepina_i_zostawia_slad_klatki():
    """Header-primary zostaje: karta `NGC 7000` w stosie zatwierdzonym jako `vdB30` wygrywa. Ślad
    to `object.unassigned` z powodem i stanem PO (`next_object_*`), licznik „inny obiekt". Drugi
    przebieg to cisza."""
    con = _pusta()
    fid = _stos_potwierdzony(con, "vdB30")
    bylo = _oid(con, "vdB30")
    _karta(con, fid, "NGC 7000")
    s = resolver.run_resolver(con, LATER)
    assert _stan(con, fid) == ("NGC7000", "header")
    assert (s.objects_path_overridden, s.objects_path_to_header) == (1, 0)
    assert _slad(con, fid) == [({"object_id": bylo, "object_source": "path",
                                 "next_object_id": _oid(con, "NGC7000"),
                                 "next_object_source": "header"}, POWOD)]
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    s2 = resolver.run_resolver(con, LATER)
    assert (s2.objects_path_overridden, s2.objects_path_to_header) == (0, 0)
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed


def test_naglowek_z_TYM_SAMYM_obiektem_liczy_sie_osobno():
    """Karta mówi to samo, co zatwierdzony folder (`NGC 7000` pod `STACKS\\NGC7000`): obiekt bez
    zmian, źródło przechodzi na nagłówek. Ślad niesie `next_object_id == object_id`."""
    con = _pusta()
    fid = _stos_potwierdzony(con, "NGC7000")
    oid = _oid(con, "NGC7000")
    _karta(con, fid, "NGC 7000")
    s = resolver.run_resolver(con, LATER)
    assert _stan(con, fid) == ("NGC7000", "header")
    assert (s.objects_path_overridden, s.objects_path_to_header) == (0, 1)
    assert _slad(con, fid) == [({"object_id": oid, "object_source": "path",
                                 "next_object_id": oid, "next_object_source": "header"}, POWOD)]


def test_przebieg_BEZ_przepiecia_nie_zostawia_sladu():
    """QUIET: klatki nazwane nagłówkiem od początku i potwierdzenie ze ścieżki bez karty - zero
    odpięć z kluczem `next_*`, zero liczników. Przepięcie nagłówek→nagłówek też kluczy nie niesie."""
    con = _pusta()
    stos = _stos_potwierdzony(con, "vdB30")
    fid, _ = repo.upsert_frame(con, sha1_data="l1", kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json="{}", object_raw="NGC 7000", now=NOW)
    s = resolver.run_resolver(con, LATER)
    assert (s.objects_path_overridden, s.objects_path_to_header) == (0, 0)
    assert _slad(con, stos) == [] and _slad(con, fid) == []


def test_przerwany_przebieg_NIE_gubi_sladu_klatek_juz_przepietych(monkeypatch):
    """Z3: ślad zapisuje klinga w transakcji przepięcia, nie podsumowanie po pętli. Przebieg
    przerwany wyjątkiem po pierwszym przepięciu zostawia w dzienniku ślad tej klatki - i spis ręki
    go czyta (przejście uprawnione pierwszej klatki nie jest ubytkiem)."""
    con = _pusta()
    a = _stos_potwierdzony(con, "NGC7000", sha="a")
    b = _stos_potwierdzony(con, "vdB30", sha="b")
    przed = _odniesienie(con)
    _karta(con, a, "NGC 7000")
    _karta(con, b, "M 31")
    prawdziwa = repo.assign_object
    wolania = []

    def _przerwij_po_pierwszym(*args, **kw):
        if wolania:
            raise RuntimeError("przerwany przebieg")
        wolania.append(kw["frame_id"])
        return prawdziwa(*args, **kw)

    monkeypatch.setattr(repo, "assign_object", _przerwij_po_pierwszym)
    with pytest.raises(RuntimeError):
        resolver.run_resolver(con, LATER)
    assert wolania == [a]
    assert [p["next_object_id"] for p, _ in _slad(con, a)] == [_oid(con, "NGC7000")]
    assert _stan(con, b) == ("vdB30", "path")                  # druga klatka nietknięta
    spadki, rozbior = _porownaj(con, przed)
    assert spadki == {} and rozbior == ((), (a,))


def test_linia_raportu_Dostawy_tylko_gdy_zaszlo_z_odmiana_liczby():
    """Linia „[rozwiąż]" dokleja ostrzeżenie (inny obiekt) i informację (ten sam obiekt) wyłącznie
    przy niezerowych licznikach, z liczbą odmienioną (`t_plural`: 1 klatkę, 2 klatki, 5 klatek)."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from horreum.gui import i18n
    from horreum.gui.pipeline import PipelineView
    formatuj = PipelineView._format_resolve
    cicho = formatuj(None, resolver.ResolveSummary())
    glosno = formatuj(None, resolver.ResolveSummary(objects_path_overridden=2,
                                                    objects_path_to_header=5))
    inny = i18n.t_plural("pipeline.fmt.resolve_path_overridden", 2)
    ten_sam = i18n.t_plural("pipeline.fmt.resolve_path_to_header", 5)
    assert inny not in cicho and ten_sam not in cicho
    assert glosno.endswith(inny + ten_sam)
    poprzedni = i18n.current_lang()
    i18n.set_lang("pl")
    try:
        assert "przepiął 1 klatkę " in i18n.t_plural("pipeline.fmt.resolve_path_overridden", 1)
        assert "przepiął 2 klatki " in i18n.t_plural("pipeline.fmt.resolve_path_overridden", 2)
        assert ": 5 klatek -" in i18n.t_plural("pipeline.fmt.resolve_path_to_header", 5)
        assert ": 1 klatka -" in i18n.t_plural("pipeline.fmt.resolve_path_to_header", 1)
        i18n.set_lang("en")
        assert "moved 1 frame off" in i18n.t_plural("pipeline.fmt.resolve_path_overridden", 1)
        assert "3 frames - same" in i18n.t_plural("pipeline.fmt.resolve_path_to_header", 3)
    finally:
        i18n.set_lang(poprzedni)


# ═══════════════════════════════════════════════════ E5-1 (b) - spis ręki po TOŻSAMOŚCI


def test_spis_przejscie_do_naglowka_BEZ_zmiany_obiektu_to_nie_ubytek():
    """Warunek „ręka nietykalna": klatka wypada z migawki ręki, ale dziennik po znaku wodnym niesie
    dowód przejścia z tym samym obiektem - `spadki` puste, przejście w rozbiorze osobno."""
    con = _pusta()
    fid = _stos_potwierdzony(con, "NGC7000")
    przed = _odniesienie(con)
    assert (przed.object_hand, przed.object_hand_frames) == (1, (fid,))
    _karta(con, fid, "NGC 7000")
    resolver.run_resolver(con, LATER)
    spadki, rozbior = _porownaj(con, przed)
    assert spadki == {} and rozbior == ((), (fid,))


def test_spis_przepiecie_na_INNY_obiekt_JEST_ubytkiem():
    """Falsyfikator poprzedniego: karta z innym obiektem zdejmuje gest człowieka - ślad niesie
    `next_object_id` różny od obiektu sprzed, więc niczego nie wyjaśnia."""
    con = _pusta()
    fid = _stos_potwierdzony(con, "vdB30")
    przed = _odniesienie(con)
    _karta(con, fid, "NGC 7000")
    resolver.run_resolver(con, LATER)
    spadki, rozbior = _porownaj(con, przed)
    assert spadki == {"object_hand": (1, 0)} and rozbior == ((fid,), ())


def test_Z1_suma_nie_ukrywa_ubytku_tozsamosc_rozstrzyga(tmp_path, capsys):
    """Scenariusz bramki `sol` Z1 dosłownie: odniesienie A=path:NGC7000, B=path:vdB30 (ręka 2).
    Potem A przechodzi do nagłówka z tym samym obiektem, B przepina nagłówek na M31, nowa klatka C
    dostaje rękę. Suma spada o 1 przy jednym przejściu - po sumach „ubytków BRAK"; po tożsamości
    ubytkiem jest B, kod wyjścia 1."""
    path = str(tmp_path / "h.db")
    con = db.open_db(path)
    a = _stos_potwierdzony(con, "NGC7000", sha="a")
    b = _stos_potwierdzony(con, "vdB30", sha="b")
    con.close()
    assert cli.main(["human-facts", path, "--json"]) == 0
    odniesienie = tmp_path / "przed.json"
    odniesienie.write_text(capsys.readouterr().out, encoding="utf-8")
    con = db.open_db(path)
    _karta(con, a, "NGC 7000")
    _karta(con, b, "M 31")
    resolver.run_resolver(con, LATER)
    c = _stos_potwierdzony(con, "vdB31", sha="c")
    assert audit.human_facts_census(con).object_hand == 1
    con.close()
    assert cli.main(["human-facts", path, "--baseline", str(odniesienie)]) == 1
    out = capsys.readouterr().out
    assert "UBYTEK object_hand: 2 -> 1" in out
    assert "(ten sam obiekt, nie ubytek): 1" in out
    assert f"  klatki, ktore stracily fakt reki osi obiektu (1): {b}" in out.splitlines()
    assert c not in (a, b)


def test_Z2_pozniejsze_naglowek_na_naglowek_NIE_udaje_przejscia():
    """Z2: path:A → nagłówek:B (ubytek), potem nagłówek:B → nagłówek:A. Rekonstrukcja z bieżącego
    stanu widziała „A przed, A teraz" i tłumiła ubytek; dowód z chwili przepięcia (`next_object_id`
    = B) - nie. Drugie przepięcie kluczy `next_*` nie niesie (źródło sprzed nie jest słabe)."""
    con = _pusta()
    fid = _stos_potwierdzony(con, "NGC7000")
    przed = _odniesienie(con)
    _karta(con, fid, "M 31")
    resolver.run_resolver(con, LATER)
    _karta(con, fid, "NGC 7000")
    resolver.run_resolver(con, LATER)
    assert _stan(con, fid) == ("NGC7000", "header")
    assert audit.path_to_header_since(con, przed.event_watermark) == frozenset()
    spadki, rozbior = _porownaj(con, przed)
    assert spadki == {"object_hand": (1, 0)} and rozbior == ((fid,), ())


def test_Z2_odpiecie_slownikowe_NIE_udaje_przejscia():
    """Z2, druga droga: `retire_alias_and_unassign` odpina klatkę ze ścieżki (zdjęcie wpisu `LMC`
    ze słownika) bez kluczy `next_*` - brak dowodu przejścia, więc to ubytek (migracja słownika
    jest jawną operacją, nie przejściem do nagłówka)."""
    con = _pusta()
    fid = _stos_potwierdzony(con, "LMC")
    oid = _oid(con, "LMC")
    repo.add_object_alias(con, alias_norm="LMC", object_id=oid, source="curated", now=NOW)
    przed = _odniesienie(con)
    assert repo.retire_alias_and_unassign(con, object_id=oid, alias_norms=["LMC"],
                                          now=LATER) == (1, 1)
    assert audit.path_to_header_since(con, przed.event_watermark) == frozenset()
    spadki, _ = _porownaj(con, przed)
    assert spadki == {"object_hand": (1, 0)}


def test_odniesienie_BEZ_migawki_porownuje_sumy_bez_tlumienia():
    """Odniesienie sprzed E5-1 (bez `object_hand_frames` i znaku wodnego): porównanie wraca do sum
    i niczego nie wyjaśnia - przejście uprawnione pokaże się jako ubytek, prawdziwy nie zniknie."""
    stare = audit.HumanFacts(object_hand=1, object_cleared=0, config_hand=0, lineage_inputs=0,
                             lineage_excluded=0, calibration_facts=0, calibration_links=0)
    assert (stare.object_hand_frames, stare.event_watermark) == (None, None)
    po = audit.HumanFacts(object_hand=0, object_cleared=0, config_hand=0, lineage_inputs=0,
                          lineage_excluded=0, calibration_facts=0, calibration_links=0,
                          object_hand_frames=(), event_watermark=9)
    assert po.reka_obiektu(stare, frozenset({7})) is None
    assert po.spadki(stare, frozenset({7})) == {"object_hand": (1, 0)}
    con = _pusta()
    assert audit.path_to_header_since(con, None) == frozenset()


def test_cli_human_facts_raportuje_przejscie_osobnym_wierszem_i_kodem_0(tmp_path, capsys):
    """Konsola: spis „przed" z `--json` jako odniesienie, przebieg, spis „po" z `--baseline` -
    wiersz przejścia, „ubytkow: BRAK" i kod wyjścia 0."""
    path = str(tmp_path / "h.db")
    con = db.open_db(path)
    fid = _stos_potwierdzony(con, "NGC7000")
    con.close()
    assert cli.main(["human-facts", path, "--json"]) == 0
    odniesienie = tmp_path / "przed.json"
    odniesienie.write_text(capsys.readouterr().out, encoding="utf-8")
    con = db.open_db(path)
    _karta(con, fid, "NGC 7000")
    resolver.run_resolver(con, LATER)
    con.close()
    assert cli.main(["human-facts", path, "--baseline", str(odniesienie)]) == 0
    out = capsys.readouterr().out
    assert "potwierdzenia ze sciezki przejete przez naglowek (ten sam obiekt, nie ubytek): 1" in out
    assert "UBYTEK" not in out


# ═══════════════════════════════════════════════════ E5-2 - rozjazd widoczny ze STANU


def test_naglowek_NIEROZPOZNANY_zostaje_przy_folderze_i_jest_w_Porzadkach():
    """Nazwa, której drabina nie zna: przebieg zostawia klatkę przy obiekcie z folderu (żaden
    kubełek przeglądu jej nie widzi, bo obiekt JEST) - wiersz Porządków ją liczy, przed przebiegiem
    i po nim, bo mówi o stanie, nie o zdarzeniach."""
    con = _pusta()
    fid = _stos_potwierdzony(con, "vdB30")
    _karta(con, fid, "moja mglawica 7")
    assert queries.path_header_conflict_frame_ids(con) == {fid}
    s = resolver.run_resolver(con, LATER)
    assert _stan(con, fid) == ("vdB30", "path")
    assert (s.objects_path_overridden, s.objects_review) == (0, 0)
    resolver.run_resolver(con, LATER)
    assert queries.path_header_conflict_frame_ids(con) == {fid}
    assert queries.tasks_state(con)["path_header_conflict_frames"] == 1


def test_naglowek_INNY_obiekt_jest_w_Porzadkach_do_najblizszego_Rozwiaz():
    """Nazwa rozpoznana jako inny obiekt: rozjazd do przebiegu, który go przepina (głośno, E5-1);
    po nim źródło przestaje być słabe i klatka wypada."""
    con = _pusta()
    fid = _stos_potwierdzony(con, "vdB30")
    _karta(con, fid, "NGC 7000")
    assert queries.path_header_conflict_frame_ids(con) == {fid}
    resolver.run_resolver(con, LATER)
    assert queries.path_header_conflict_frame_ids(con) == set()


@pytest.mark.parametrize("object_raw", ["NGC 7000", "ngc7000", "North America"])
def test_naglowek_z_TYM_SAMYM_obiektem_nie_jest_rozjazdem(object_raw):
    """Porównanie po KANONIE przez tę samą drabinę co przebieg - pisownia ze spacją, małe litery
    i nazwa potoczna wskazują ten sam obiekt, więc rozjazdu nie ma."""
    con = _pusta()
    fid = _stos_potwierdzony(con, "NGC7000")
    _karta(con, fid, object_raw)
    assert queries.path_header_conflict_frame_ids(con) == set()


def test_pusta_karta_i_brak_karty_nie_zeznaja():
    """Nagłówek bez nazwy (brak karty albo pusty napis) nie przeczy folderowi - ta sama reguła
    „obecne zeznanie" (`_to_text`) co w przebiegu, który pustego zeznania nie liczy do przeglądu.
    Sam biały znak JEST zeznaniem (przebieg liczy go jako nierozpoznane), więc tu też wchodzi."""
    con = _pusta()
    a = _stos_potwierdzony(con, "vdB30", sha="a")
    b = _stos_potwierdzony(con, "NGC7000", sha="b")
    _karta(con, a, "")
    assert queries.path_header_conflict_frame_ids(con) == set()
    _karta(con, b, "   ")
    assert queries.path_header_conflict_frame_ids(con) == {b}


def test_wycofana_klatka_wypada_z_listy_roboty():
    """Guard żywotności jak u sąsiadów: wycofanie klingą gestu (po zniknięciu jedynej kopii - klingą
    obecności) zdejmuje klatkę z wiersza."""
    con = _pusta()
    fid = _stos_potwierdzony(con, "vdB30")
    _karta(con, fid, "moja mglawica 7")
    lid, sciezka = con.execute("SELECT id, path FROM location WHERE frame_id = ?",
                               (fid,)).fetchone()
    assert repo.mark_location_vanished(con, location_id=lid, expected_path=sciezka, root=R,
                                       run_id="t", now=LATER)
    assert queries.path_header_conflict_frame_ids(con) == {fid}
    assert repo.retire_frames(con, frame_ids=[fid], now=LATER).done == 1
    assert queries.path_header_conflict_frame_ids(con) == set()


def test_reka_rozstrzyga_rozjazd_przypisaniem():
    """Droga naprawy z perspektywy: „Przypisz obiekt" nadpisuje źródło słabe ręką (`user`), więc
    klatka wypada z wiersza, a przebieg jej już nie tyka."""
    con = _pusta()
    fid = _stos_potwierdzony(con, "vdB30")
    _karta(con, fid, "moja mglawica 7")
    g = repo.user_assign_object(con, alias_norm=None, canon="vdB30", catalog="vdB",
                                kind="deep_sky", frame_ids=[fid], now=LATER, overwrite_weak=True)
    assert g.assigned == 1
    assert queries.path_header_conflict_frame_ids(con) == set()
    resolver.run_resolver(con, LATER)
    assert _stan(con, fid) == ("vdB30", "user")


def test_wiersz_Porzadkow_prowadzi_do_perspektywy_z_tymi_klatkami(tmp_path, monkeypatch):
    """Wiersz AKCYJNY i ROBOTA (poza `_BEZ_ROBOTY`): liczba = predykat stanu, klik prowadzi do
    Zbiorów z perspektywą pokazującą dokładnie te klatki, pasek kryteriów nazywa zawężenie."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import QApplication
    from horreum.gui import grid as grid_mod, i18n, rows, tasks as tasks_mod
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: d)
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: None)
    con = db.open_db(str(tmp_path / "h.db"))
    fid = _stos_potwierdzony(con, "vdB30")
    _stos_potwierdzony(con, "NGC7000", sha="st2")               # zgodny - poza wierszem
    _karta(con, fid, "moja mglawica 7")
    view = grid_mod.FramesView(con, now_fn=None)
    tv = tasks_mod.TasksView(con)
    tv.open_collection.connect(view.apply_perspective)
    try:
        assert "path_header_conflict_frames" not in tasks_mod._BEZ_ROBOTY
        tv.refresh_counts()
        wiersz = next(tv.tasks.item(i) for i in range(tv.tasks.count())
                      if tv.tasks.item(i).data(Qt.UserRole) == "path_header_conflict_frames")
        assert wiersz.text() == i18n.t("tasks.path_header_conflict_frames")
        assert wiersz.data(rows.SECONDARY) == "1  ›" and wiersz.data(rows.STRONG) is True
        tv._on_task_clicked(wiersz)
        assert view._frame_ids == [fid]
        assert i18n.t("grid.criteria.only_path_header_conflict") in \
            view.sel_bar.criteria_label.toolTip()
    finally:
        tv.close()
        view.close()
        con.close()


def test_Z4_kalibracja_ze_zrodlem_path_i_OBJECT_nie_wchodzi():
    """Z4: przebieg rozstrzyga obiekt wyłącznie na `LIGHT_KINDS`, więc wiersz też. Flat ze źródłem
    `path` (stan, który dziś wytwarza następczyni-kalibracja w `repo.transfer_human_facts`) i kartą
    `OBJECT` nie jest robotą tego wiersza. Stan wstawiony surowym SQL - żadna klinga NIE powinna go
    wytworzyć (guard rodzaju w `user_assign_object`), a fikstura odtwarza właśnie defekt."""
    con = _pusta()
    oid, _ = repo.upsert_object(con, canon="NGC7000", catalog="NGC", kind="deep_sky", now=NOW)
    fid, _ = repo.upsert_frame(con, sha1_data="flat1", kind="flat", filetype="fits",
                               camera_id=None, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json="{}", object_raw="FlatWizard", now=NOW)
    con.execute("UPDATE frame SET object_id = ?, object_source = 'path' WHERE id = ?", (oid, fid))
    con.commit()
    assert queries.path_header_conflict_frame_ids(con) == set()
