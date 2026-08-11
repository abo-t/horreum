"""D-OW-3/R2 — WYCOFANIE KLATKI RĘKĄ (`frame.retired_at`, migracja 0018, paczka G2).

Klatka bez ani jednej OBECNEJ kopii tkwiła w kubełkach roboczych na zawsze, a jedynym wyjściem
była kasacja wierszy (utrata historii). Ta bateria pilnuje czterech rzeczy, w tej kolejności wagi:

1. **GRANICY** — co wycofanie zabiera (kubełki robocze) i czego NIE zabiera (godziny, archiwum,
   rodowód). Testy granicy są NEGATYWNE i to jest ich teza, nie ich brak.
2. **DOMKNIĘCIA ROZKŁADU** — sześć kubełków raportu niesie guard, a `total` nie niesie żadnego,
   więc bez klasy ucieczki `retired` bramka §5.7a zapaliłaby się przy PIERWSZYM geście.
3. **PINU RDZEŃ↔GUI** — trzy predykaty `resolver` mają bliźniaki w `gui.queries` „znak w znak";
   guard w jednej warstwie to czerwona bateria.
4. **ODWRACALNOŚCI** — paczka domyka grupę „gest bez drogi powrotu" i nie ma prawa wnieść własnego.

Bez plików na dysku: `present=0` stawiamy KLINGĄ (`repo.mark_location_vanished`), nie gołym
UPDATE-em — inaczej sondowalibyśmy własny SQL zamiast ścieżki, którą naprawdę idzie program.
"""
import json

import pytest

from horreum import audit, db, repo, resolver, supersede
from horreum.gui import queries

NOW = "2026-08-11T10:00:00+00:00"


def _baza():
    return db.open_db(":memory:")


def _klatka(con, sha, *, kind="light", filetype="fits", now=NOW):
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind=kind, filetype=filetype,
                               camera_id=None, now=now)
    return fid


def _kopia(con, frame_id, path, *, now=NOW):
    lid, _ = repo.add_location(con, frame_id=frame_id, volume="TESTVOL", path=path, now=now)
    return lid


def _zniknieta(con, sha="aaa", *, kind="light", path=r"R:\ASTRO_\x.fit"):
    """Klatka, której JEDYNA kopia zniknęła z dysku — cel gestu wycofania."""
    fid = _klatka(con, sha, kind=kind)
    lid = _kopia(con, fid, path)
    repo.mark_location_vanished(con, location_id=lid, expected_path=path,
                                root=r"R:\ASTRO_", run_id="test-retire", now=NOW)
    return fid, lid


def _naglowek(con, fid, *, object_raw=None, exptime=600.0, date_obs="2026-01-02T22:00:00"):
    con.execute("INSERT INTO header(frame_id, raw_json, object_raw, exptime, date_obs) "
                "VALUES (?, '{}', ?, ?, ?)", (fid, object_raw, exptime, date_obs))
    con.commit()


# ══════════════════════════════════════════════════════════════ 1. KLINGA

def test_wycofanie_zapisuje_stempel_i_event_ze_sciezkami():
    """Payload niesie OSTATNIE ZNANE ŚCIEŻKI: po wycofaniu żaden kubełek ich nie pokaże,
    a „gdzie ten plik leżał" jest jedynym pytaniem, które człowiek zada po fakcie."""
    con = _baza()
    fid, _ = _zniknieta(con, path=r"R:\ASTRO_\LIGHTS\ngc7000.fit")
    g = repo.retire_frames(con, frame_ids=[fid], now=NOW)
    assert (g.done, g.skipped) == (1, 0)
    assert con.execute("SELECT retired_at FROM frame WHERE id=?", (fid,)).fetchone()[0] == NOW
    ev = json.loads(
        con.execute("SELECT payload FROM event WHERE verb='frame.retired'").fetchone()[0])
    assert ev["paths"] == [r"R:\ASTRO_\LIGHTS\ngc7000.fit"]


def test_wycofanie_jest_idempotentne_i_nie_puchnie_dziennika():
    con = _baza()
    fid, _ = _zniknieta(con)
    repo.retire_frames(con, frame_ids=[fid], now=NOW)
    g = repo.retire_frames(con, frame_ids=[fid], now=NOW)
    assert (g.done, g.skipped_already) == (0, 1)
    assert con.execute("SELECT count(*) FROM event WHERE verb='frame.retired'").fetchone()[0] == 1


def test_guard_zywotnosci_broni_klatki_z_OBECNA_kopia():
    """Ten sam guard, którym broni się `mark_superseded`: gest, który ukrywa klatkę z żywym
    plikiem, chowa REALNĄ robotę — czyli robi dokładnie to, czemu ma zapobiegać."""
    con = _baza()
    fid, _ = _zniknieta(con)
    _kopia(con, fid, r"R:\ASTRO_\kopia_zapasowa.fit")      # druga ścieżka, ta sama treść — ŻYWA
    g = repo.retire_frames(con, frame_ids=[fid], now=NOW)
    assert (g.done, g.skipped_present) == (0, 1)
    assert con.execute("SELECT retired_at FROM frame WHERE id=?", (fid,)).fetchone()[0] is None


def test_guard_odmawia_sierocie_bez_zadnej_lokacji():
    """Sierota po `rebind_location` to INNY stan i inna robota — `vanished_frame_ids` odróżnia go
    guardem `EXISTS` i klinga też. Wycofanie zabrałoby ją z pola widzenia `supersede.orphans`."""
    con = _baza()
    fid = _klatka(con, "sierota")
    g = repo.retire_frames(con, frame_ids=[fid], now=NOW)
    assert (g.done, g.skipped_no_location) == (0, 1)


def test_guard_odmawia_klatce_ZASTAPIONEJ_wlasnym_powodem():
    """Stan MOŻLIWY, nie hipotetyczny: `mark_superseded` odrzuca tylko klatkę z kopią OBECNĄ, więc
    „zastąpiona + zniknięta" istnieje. Dwa terminalne werdykty na jednej klatce znaczyłyby dwie
    różne odpowiedzi na jedno pytanie — a powód musi być WŁASNY, nie zlany z „bez lokacji",
    bo o klatce zastąpionej wiadomo wszystko (jej treść niesie następczyni)."""
    con = _baza()
    a, _ = _zniknieta(con, "aaa")
    b = _klatka(con, "bbb")
    assert repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW) is True
    g = repo.retire_frames(con, frame_ids=[a], now=NOW)
    assert (g.done, g.skipped_superseded, g.skipped_no_location) == (0, 1, 0)


def test_rozbicie_powodow_sumuje_sie_do_pominietych():
    """Właścicielem składu jest `RetireGesture.skipped_breakdown`, nie literał w GUI — człon
    dołożony później wpadałby do sumy „z M" i znikał z rozbicia, czyli stamtąd, gdzie tłumaczy."""
    con = _baza()
    zniknieta, _ = _zniknieta(con, "aaa")
    zywa = _klatka(con, "bbb")
    _kopia(con, zywa, r"R:\ASTRO_\zywa.fit")
    sierota = _klatka(con, "ccc")
    g = repo.retire_frames(con, frame_ids=[zniknieta, zywa, sierota], now=NOW)
    assert g.done == 1
    assert sum(n for _k, n in g.skipped_breakdown) == g.skipped == 2


def test_przywrocenie_jest_droga_powrotu_i_gasi_stempel():
    con = _baza()
    fid, _ = _zniknieta(con)
    repo.retire_frames(con, frame_ids=[fid], now=NOW)
    g = repo.restore_frames(con, frame_ids=[fid], now=NOW)
    assert g.done == 1
    assert con.execute("SELECT retired_at FROM frame WHERE id=?", (fid,)).fetchone()[0] is None
    assert con.execute(
        "SELECT count(*) FROM event WHERE verb='frame.unretired'").fetchone()[0] == 1


def test_przywrocenie_NIE_wymaga_zeby_plik_dalej_byl_zniknięty():
    """Sedno drogi powrotu: powrót pliku na dysk jest NAJCZĘSTSZYM powodem, dla którego człowiek
    sięga po ten gest. Guard obecnej kopii po tej stronie byłby zamkniętymi drzwiami."""
    con = _baza()
    fid, lid = _zniknieta(con)
    repo.retire_frames(con, frame_ids=[fid], now=NOW)
    con.execute("UPDATE location SET present = 1 WHERE id = ?", (lid,))   # skan znalazł plik
    con.commit()
    assert repo.restore_frames(con, frame_ids=[fid], now=NOW).done == 1


# ══════════════════════════════════════════════════ 2. GRANICA — czego wycofanie NIE zabiera

def test_GRANICA_godziny_wycofanej_klatki_ZOSTAJA():
    """TEZA, nie luka. `superseded` odpada z `object_exposure`, bo jej godziny liczy NASTĘPCZYNI
    (podwójny rachunek) — wycofana następczyni NIE MA. Klatka została naświetlona naprawdę,
    więc odjęcie jej godzin byłoby kasowaniem historii, czyli tym, przed czym `retired_at` broni.
    To samo źródło karmi planer (`targets.archive_coverage`), więc oba ekrany mówią to samo."""
    con = _baza()
    oid = repo.upsert_object(con, canon="NGC7000", catalog="NGC", kind=None, now=NOW)[0]
    fid, _ = _zniknieta(con)
    _naglowek(con, fid, object_raw="NGC7000", exptime=600.0)
    repo.assign_object(con, frame_id=fid, object_id=oid, object_source="user", now=NOW)

    przed = queries.object_exposure(con, [oid])
    repo.retire_frames(con, frame_ids=[fid], now=NOW)
    assert queries.object_exposure(con, [oid]) == przed, "wycofanie NIE MA prawa odjąć godzin"


def test_GRANICA_wycofana_klatka_zostaje_w_archiwum():
    """F1: „zniknięte mają być widoczne". Wycofanie zdejmuje z ROBOTY, nie z archiwum — inaczej
    perspektywa „Wycofane" nie miałaby czego pokazać, a gest powrotu nie miałby co zaznaczyć."""
    con = _baza()
    fid, _ = _zniknieta(con)
    repo.retire_frames(con, frame_ids=[fid], now=NOW)
    assert fid in queries.all_frame_ids(con)
    assert queries.retired_frame_ids(con) == {fid}


# ══════════════════════════════════════════════════ 3. KUBEŁKI ROBOCZE — z czego wypada

def test_wypada_z_kubelka_w_ktorym_dotad_TKWIL():
    con = _baza()
    fid, _ = _zniknieta(con)
    assert queries.vanished_frame_ids(con) == {fid}
    repo.retire_frames(con, frame_ids=[fid], now=NOW)
    assert queries.vanished_frame_ids(con) == set()


def test_wypada_z_przegladu_obiektow_i_z_kolejki():
    con = _baza()
    fid, _ = _zniknieta(con)
    _naglowek(con, fid)
    assert fid in queries.review_frame_ids(con)
    assert resolver.review_state(con).total >= 1
    repo.retire_frames(con, frame_ids=[fid], now=NOW)
    assert fid not in queries.review_frame_ids(con)


def test_wypada_z_kubelka_RODOWODU_bo_ten_jest_AKCYJNY():
    """Kubełek rodowodu liczy się do odznaki sidebara i derywuje z `integration`, BEZ warunku na
    `frame` — wycofany gotowy obraz zostawałby w nim na zawsze, oferując robotę na pliku,
    którego nie ma. To dokładnie ta populacja, którą dług wskazuje jako generator."""
    con = _baza()
    fid, _ = _zniknieta(con, "stos", kind="master_light")
    con.execute("INSERT INTO integration(master_frame_id, unresolved_reason, created_at) "
                "VALUES (?, 'no_window', ?)", (fid, NOW))
    con.commit()
    assert fid in queries.lineage_pending_frame_ids(con)
    repo.retire_frames(con, frame_ids=[fid], now=NOW)
    assert fid not in queries.lineage_pending_frame_ids(con)


def test_wypada_z_sierot_bez_ogniwa():
    """Sierota wycofana ręką jest WYJAŚNIONA tak samo jak sierota z ogniwem: pytanie „gdzie ten
    plik" ma odpowiedź człowieka. Bez tego guardu wycofanie + `rebind_location` zaczerwieniłoby
    §5.15 — i to bez żadnego gestu naprawy, bo gest naprawy właśnie się odbył."""
    con = _baza()
    fid, lid = _zniknieta(con)
    nastepczyni = _klatka(con, "nowa")
    repo.retire_frames(con, frame_ids=[fid], now=NOW)
    repo.rebind_location(con, location_id=lid, frame_after=nastepczyni, now=NOW)
    assert fid not in supersede.orphans(con)


@pytest.mark.parametrize("rdzen,gui", [
    (resolver.nameless_lights, queries.nameless_frames),
    (resolver.nameless_raw_lights, queries.nameless_raw_frames),
    (resolver.nameless_stacks, queries.nameless_stack_frames),
])
def test_PIN_rdzen_i_GUI_licza_to_samo_po_wycofaniu(rdzen, gui):
    """Trzy predykaty rdzenia są bliźniakami drążeń GUI „znak w znak" i równość pinuje bramka 13.
    Guard w jednej warstwie = czerwona bateria; ten test jest jej wcześniejszym ostrzeżeniem."""
    con = _baza()
    fits, _ = _zniknieta(con, "fits1")
    raw = _klatka(con, "raw1", filetype="raw")
    _kopia(con, raw, r"R:\ASTRO_\raw.dng")
    stos, _ = _zniknieta(con, "stos1", kind="master_light", path=r"R:\ASTRO_\STACKS\s.xisf")
    for f in (fits, raw, stos):
        _naglowek(con, f)
    assert rdzen(con) == len(gui(con))
    repo.retire_frames(con, frame_ids=[fits, stos], now=NOW)
    assert rdzen(con) == len(gui(con))


# ══════════════════════════════════════════════════ 4. DOMKNIĘCIE ROZKŁADU + INWARIANTY

@pytest.mark.parametrize("wariant", ["resolved", "unresolved", "nameless", "headerless",
                                     "filetype_unknown"])
def test_rozklad_populacji_domyka_sie_po_wycofaniu(wariant):
    """`total` NIE MA żadnego guardu, a sześć kubełków ma — bez klasy ucieczki `retired` bramka
    §5.7a zapaliłaby się na PRAWIDŁOWEJ pracy programu. Dwa warianty są tu nietrywialne:
    `headerless` i `filetype_unknown` to SĄSIEDNIE klasy ucieczki, więc gdyby nie dostały guardu,
    wycofana klatka liczyłaby się DWA RAZY i suma przestrzeliłaby `total`."""
    con = _baza()
    oid = repo.upsert_object(con, canon="NGC7000", catalog="NGC", kind=None, now=NOW)[0]
    fid, _ = _zniknieta(con, wariant)
    if wariant == "resolved":
        _naglowek(con, fid, object_raw="NGC7000")
        repo.assign_object(con, frame_id=fid, object_id=oid, object_source="user", now=NOW)
    elif wariant == "unresolved":
        _naglowek(con, fid, object_raw="COS_NIEZNANEGO")
    elif wariant == "nameless":
        _naglowek(con, fid)
    elif wariant == "filetype_unknown":
        _naglowek(con, fid)
        con.execute("UPDATE frame SET filetype = NULL WHERE id = ?", (fid,))
        con.commit()
    # `headerless` = bez wiersza `header` (nic nie robimy)

    assert audit.light_population_closure(con, resolver.delta_report(con)).ok
    repo.retire_frames(con, frame_ids=[fid], now=NOW)
    zamkniecie = audit.light_population_closure(con, resolver.delta_report(con))
    assert zamkniecie.ok, f"rozkład się rozjechał: {zamkniecie.counted} != {zamkniecie.total}"
    assert zamkniecie.retired == 1


def test_inwariant_lapie_powrot_pliku_po_wycofaniu():
    """JEDYNY stan, w którym ŻYWA klatka wypada ze wszystkich kubełków. Nie jest awarią: powstaje
    zwykłym re-skanem. Nie gasimy go automatycznie (warunek stały „ręka nietykalna"), więc ma być
    GŁOŚNY — inaczej paczka leczy jeden ślepy zaułek i wnosi drugi, cichszy."""
    con = _baza()
    fid, lid = _zniknieta(con)
    repo.retire_frames(con, frame_ids=[fid], now=NOW)
    assert audit.retire_invariants(con)["wycofana_z_obecna_kopia"] == 0
    con.execute("UPDATE location SET present = 1 WHERE id = ?", (lid,))   # skan znalazł plik
    con.commit()
    assert audit.retire_invariants(con)["wycofana_z_obecna_kopia"] == 1
    assert queries.retired_conflict_frame_ids(con) == {fid}
    repo.restore_frames(con, frame_ids=[fid], now=NOW)
    assert audit.retire_invariants(con)["wycofana_z_obecna_kopia"] == 0


def test_inwariant_i_licznik_Porzadkow_licza_TO_SAMO():
    """Dwa literały, dwie warstwy (rdzeń audytu i read-model GUI) — równość pinuje ten test,
    wzorem pary `nameless_*`. Rozjazd znaczyłby, że bramka akceptacji i ekran mówią co innego."""
    con = _baza()
    fid, lid = _zniknieta(con)
    repo.retire_frames(con, frame_ids=[fid], now=NOW)
    con.execute("UPDATE location SET present = 1 WHERE id = ?", (lid,))
    con.commit()
    assert (audit.retire_invariants(con)["wycofana_z_obecna_kopia"]
            == len(queries.retired_conflict_frame_ids(con))
            == queries.tasks_state(con)["retired_conflict_frames"])


def test_wycofanie_wchodzi_do_spisu_faktow_reki():
    """Wycofanie JEST werdyktem ręki, a `retired_at` nie ma strażnika w DDL — bez tej osi
    `horreum human-facts --baseline` przepuściłby jego cichy ubytek przy wjeździe materiału."""
    con = _baza()
    fid, _ = _zniknieta(con)
    przed = audit.human_facts_census(con)
    repo.retire_frames(con, frame_ids=[fid], now=NOW)
    po = audit.human_facts_census(con)
    assert (przed.retired_hand, po.retired_hand) == (0, 1)
    assert "retired_hand" in po.counts
    assert przed.spadki(po) == {"retired_hand": (1, 0)}      # ubytek osi JEST naruszeniem


def test_inwariant_NIE_zapala_sie_na_legalnym_przepieciu_lokacji():
    """REGRESJA WŁASNA, złapana bramką pakietu (`sol`, zarzut blokujący). Pierwsza wersja
    `retire_invariants` miała człon „wycofana bez lokacji" z uzasadnieniem „to znaczy złamany guard
    klingi" — a myliła stan W CHWILI ZAPISU ze stanem BIEŻĄCYM. Sekwencja niżej jest LEGALNA
    (i pokrywa ją test `test_wypada_z_sierot_bez_ogniwa` w tym samym pliku), więc bramka §5.17
    zapalałaby się na prawidłowej pracy programu — zmierzone: 1 naruszenie."""
    con = _baza()
    fid, lid = _zniknieta(con)
    nastepczyni = _klatka(con, "nowa")
    repo.retire_frames(con, frame_ids=[fid], now=NOW)
    repo.rebind_location(con, location_id=lid, frame_after=nastepczyni, now=NOW)
    assert audit.retire_invariants(con) == {"wycofana_z_obecna_kopia": 0}
