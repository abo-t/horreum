"""Read-model osi TELESKOP (`horreum.gui.queries`, PLAN_gui §5/§7) — CZYSTA logika, BEZ Qt
(ten plik nie importuje PySide6, więc wlicza się do pełnego `pytest` w środowisku bez Qt, §7.2).

Pokrycie: aktywne teleskopy z licznością (kanon-filtr JAWNY, kolizja kamery, frame `config NULL`
poza sumą, `frame_count=0` dla teleskopu bez klatek), roll-up po scaleniu + zniknięcie source,
`merged_under`, audyt eventów (cała oś vs jeden teleskop), oraz że odczyt nie pisze do bazy."""
import ast
import json
import re
from pathlib import Path

import horreum
from horreum import repo
from horreum.gui import queries

NOW = "2026-06-29T13:00:00"


def _counts(con):
    return {r["id"]: r["frame_count"] for r in queries.active_telescopes(con)}


# --- active_telescopes: liczność, kanon-filtr, LEFT JOIN ---

def test_active_liczy_klatki_kolizja_kamery_i_config_null_poza_suma(s8):
    con, ids = s8
    A, B, C, D = ids["A"], ids["B"], ids["C"], ids["D"]
    rows = queries.active_telescopes(con)
    # wszystkie 4 kanoniczne obecne (żaden jeszcze nie scalony)
    assert {r["id"] for r in rows} == {A, B, C, D}
    counts = {r["id"]: r["frame_count"] for r in rows}
    assert counts == {A: 2, B: 3, C: 2, D: 0}        # nullcfg poza sumą; D bez klatek = 0
    # kolumny do listy GUI
    a_row = next(r for r in rows if r["id"] == A)
    assert a_row["status"] == "proposed" and a_row["label"] is None
    assert a_row["f_ratio_nominal"] == 5.6 and a_row["focal_nominal"] == 784


def test_active_label_widoczny_po_zapisie(s8):
    con, ids = s8
    repo.label_telescope(con, telescope_id=ids["A"], label="A140R", now=NOW)
    a_row = next(r for r in queries.active_telescopes(con) if r["id"] == ids["A"])
    assert a_row["label"] == "A140R"


def test_active_po_merge_rolluje_klatki_i_chowa_source(s8):
    """R3 ścieżką read-modelu: po merge(A→B) source znika z listy aktywnych, a jego klatki rolują się
    pod kanon B (kolizja kamery: cfg_a i cfg_b tej samej cam1 sumują się). Unmerge rozdziela."""
    con, ids = s8
    A, B, C, D = ids["A"], ids["B"], ids["C"], ids["D"]
    repo.merge_telescope(con, source_id=A, target_id=B, now=NOW)

    counts = _counts(con)
    assert A not in counts                              # source zniknął (merged_into=B)
    assert counts == {B: 5, C: 2, D: 0}                 # 2+3 pod kanonem B

    repo.unmerge_telescope(con, telescope_id=A, now=NOW)
    assert _counts(con) == {A: 2, B: 3, C: 2, D: 0}     # rozdzielenie


def test_active_approved_scalony_nie_wycieka(s8):
    """§3b: approved + potem scalony NIE przecieka jako osobny wiersz (kanon-filtr JAWNY). Approve
    PRZED merge (approve scalonego = ValueError); merge zachowuje status jako audyt, ale wiersz znika
    z aktywnych."""
    con, ids = s8
    A, B = ids["A"], ids["B"]
    repo.approve_telescope(con, telescope_id=A, now=NOW)
    repo.merge_telescope(con, source_id=A, target_id=B, now=NOW)
    active_ids = {r["id"] for r in queries.active_telescopes(con)}
    assert A not in active_ids                          # approved-ale-scalony nie wycieka
    # status pozostaje jako audyt historyczny
    assert con.execute("SELECT status FROM telescope WHERE id=?", (A,)).fetchone()["status"] == "approved"


# --- merged_under ---

def test_merged_under_listuje_czlonkow(s8):
    con, ids = s8
    A, B, C = ids["A"], ids["B"], ids["C"]
    repo.merge_telescope(con, source_id=A, target_id=B, now=NOW)
    repo.merge_telescope(con, source_id=C, target_id=B, now=NOW)   # multi-merge pod B
    under = queries.merged_under(con, B)
    assert [r["id"] for r in under] == sorted([A, C])
    assert queries.merged_under(con, A) == []                      # nic pod A


# --- axis_events: audyt ---

def test_axis_events_cala_os_najnowsze_pierwsze(s8):
    con, ids = s8
    repo.label_telescope(con, telescope_id=ids["A"], label="A140R", now=NOW)
    ev = queries.axis_events(con)
    verbs = [r["verb"] for r in ev]
    assert verbs[0] == "telescope.labeled"             # najnowszy pierwszy (id DESC)
    assert "telescope.proposed" in verbs               # eventy groupera też w osi
    # tylko target telescope:* (LIKE)
    assert all(r["target"].startswith("telescope:") for r in ev)


def test_axis_events_jeden_teleskop_filtruje_target(s8):
    con, ids = s8
    A, B = ids["A"], ids["B"]
    repo.label_telescope(con, telescope_id=A, label="A140R", now=NOW)
    repo.approve_telescope(con, telescope_id=A, now=NOW)
    repo.label_telescope(con, telescope_id=B, label="ED120", now=NOW)

    only_a = queries.axis_events(con, telescope_id=A)
    assert {r["target"] for r in only_a} == {f"telescope:{A}"}
    verbs = {r["verb"] for r in only_a}
    assert {"telescope.proposed", "telescope.labeled", "telescope.approved"} <= verbs
    # payload audytu czytelny (before→after)
    labeled = next(r for r in only_a if r["verb"] == "telescope.labeled")
    assert json.loads(labeled["payload"]) == {"before": None, "after": "A140R"}


def test_axis_events_limit(s8):
    con, ids = s8
    repo.label_telescope(con, telescope_id=ids["A"], label="A140R", now=NOW)
    assert len(queries.axis_events(con, limit=1)) == 1


# --- odczyt nie pisze ---

def test_read_model_nie_emituje_eventow(s8):
    """Odczyt to czysty SELECT — żadne zapytanie read-modelu nie dokłada eventu ani nie zmienia stanu."""
    con, ids = s8
    before = con.execute("SELECT count(*) FROM event").fetchone()[0]
    queries.active_telescopes(con)
    queries.merged_under(con, ids["A"])
    queries.axis_events(con)
    queries.axis_events(con, telescope_id=ids["A"])
    after = con.execute("SELECT count(*) FROM event").fetchone()[0]
    assert before == after


# --- PORZĄDKI: tasks_state (F5) — liczniki ze STANU ---

def test_tasks_state_liczniki_na_s8_obj(s8_obj):
    """Arytmetyka fixture (przeliczona w recenzji F5): unresolved = objrev1+objrev2+nullcfg (present0
    MA obiekt); dups = a1 (2×present=1); teleskopy A–D wszystkie bez etykiety; zero obserwatoriów;
    vanished = present0 (jedyna lokacja present=0) — bez guardu EXISTS licznik złapałby też
    klatki BEZ lokacji w ogóle (w fixture jest ich 10). Kluczy jest SIEDEM: `xisf_frames` zniknął
    w P6c razem z wierszem Porządków (pisarz XISF istnieje, więc „tylko do odczytu" przestało
    być prawdą, a licznik formatu nie jest zadaniem), `stacks_lineage_pending` doszedł 0808
    z kubełkiem rodowodu — w tej fixture jest ZERO, bo nie ma w niej ani jednej integracji, i to
    jest właściwa odpowiedź: brak przebiegu rodowodu to nie to samo, co robota do zrobienia —
    a `superseded_frames` doszedł 0809 z perspektywą „Zastąpione" i też jest ZEREM, bo fixture nie
    zna podmiany treści. Zero jest tu WŁAŚCIWE dwa razy z różnych powodów i oba są wypowiedziane,
    żeby przyszła zmiana nie wzięła braku populacji za dowód poprawności predykatu.

    Od D-OW-3/R2 kluczy jest DZIEWIĘĆ: doszły `retired_frames` (perspektywa „Wycofane" — zapis
    historii) i `retired_conflict_frames` („wycofana, a plik wrócił" — jedyny z dwóch, który JEST
    robotą). Oba są tu ZEREM z trzeciego, znowu innego powodu: fixture nie zna gestu wycofania.
    ⚠ Zero w `retired_conflict_frames` jest przy tym NIETRYWIALNE — `vanished_frames` liczy w tej
    fixture klatkę `present0`, więc gdyby guard wycofania pomylił kierunek, ta sama klatka wpadłaby
    tutaj i licznik pokazałby 1."""
    con, ids = s8_obj
    st = queries.tasks_state(con)
    assert st == {
        "unresolved_lights": 3,
        "stacks_lineage_pending": 0,
        "dup_frames": 1,
        # 0021: duplikat `a1` ma dwie kopie, ale żadna nie ma ZEBRANEGO zeznania (fikstura wkłada
        # kopie klingą bez faktów z nagłówka) - „nie wiem" nie jest rozjazdem, więc zero. Predykat
        # na danych z rozjazdem pinują `test_copy_facts.py` (stan) i `test_gui_copy_facts.py` (wiersz).
        "copy_conflict_frames": 0,
        # AR-5: ten sam powód, co wyżej - bez zebranych faktów kopii predykat mówi „nie wiem",
        # nie „zeznanie z nieobecnej kopii". Stan z rozjazdem pinuje `test_orphan_testimony.py`.
        "orphan_testimony_frames": 0,
        "telescopes_unlabeled": 4,
        "observatories_unnamed": 0,
        "vanished_frames": 1,
        "retired_frames": 0,
        "retired_conflict_frames": 0,
        "superseded_frames": 0,
        # D-V-9a: fikstura ma klatkę `present0` z JEDYNĄ kopią martwą (czyli zniknętą),
        # a nie żywą obok martwej - więc ten licznik ma tu być 0. Gdyby predykat zgubił
        # warunek istnienia żywej kopii, wchłonąłby `present0` i pokazał 1.
        "missing_copy_frames": 0,
        # Wersje stosów: fikstura nie ma ani jednej integracji, więc nie ma grup bliźniaków -
        # zero z czwartego powodu (brak populacji, nie dowód poprawności predykatu; ten pinują
        # testy `test_gui_stack_versions.py` na własnych danych).
        "stack_versions": 0,
    }


def test_znikniete_NIE_pokazuja_klatki_zastapionej_ktorej_gest_nie_zamknie():
    """G2-6d: perspektywa „Zniknięte" jest listą ROBOTY, a jej gestem jest wycofanie - klinga
    (`repo._retire_verdict`) klatkę zastąpioną odrzuca. Stan jest osiągalny zwykłą drogą:
    `repo.mark_superseded` odmawia tylko przy kopii OBECNEJ, więc zastąpiona z martwą kopią
    istnieje. Bliźniaczka o tym samym kształcie, ale NIEzastąpiona, ZOSTAJE - guard ma wyciąć
    zastąpienie, nie zniknięcie. Licznik Porządków czyta ten sam predykat i mówi to samo.

    Falsyfikator: zdejmij `AND f.superseded_by IS NULL` z `vanished_frame_ids` - zastąpiona wraca
    do zbioru i asercja na `vanished_frame_ids` czerwienieje (a licznik Porządków pokazuje 2)."""
    from horreum import db

    con = db.open_db(":memory:")

    def _zniknieta(sha, path):
        fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="light", filetype="fits",
                                   camera_id=None, now=NOW)
        lid, _ = repo.add_location(con, frame_id=fid, volume="TESTVOL", path=path, now=NOW)
        repo.mark_location_vanished(con, location_id=lid, expected_path=path,
                                    root=r"R:\ASTRO_", run_id="g2-6d", now=NOW)
        return fid

    zastapiona = _zniknieta("sha-zastapiona", r"R:\ASTRO_\a.fit")
    blizniaczka = _zniknieta("sha-blizniaczka", r"R:\ASTRO_\b.fit")
    nastepczyni, _ = repo.upsert_frame(con, sha1_data="sha-nastepczyni", kind="light",
                                       filetype="fits", camera_id=None, now=NOW)
    assert repo.mark_superseded(con, frame_id=zastapiona, superseded_by=nastepczyni,
                                now=NOW) is True

    assert queries.vanished_frame_ids(con) == {blizniaczka}
    assert queries.tasks_state(con)["vanished_frames"] == 1
    # Powierzchnia i klinga mówią to samo: gest tej listy tej klatki nie przyjmuje.
    g = repo.retire_frames(con, frame_ids=[zastapiona], now=NOW)
    assert (g.done, g.skipped_superseded) == (0, 1)
    assert zastapiona in queries.superseded_frame_ids(con)       # nie znika z oczu - ma swoją listę


def test_duplikaty_NIE_pokazuja_klatki_wycofanej_ktorej_pliki_wrocily():
    """G2-10d - bliźniak G2-6d na „Duplikatach". Wycofanie wymaga braku obecnej kopii tylko
    w chwili zapisu; re-skan potrafi potem znaleźć tę samą treść pod DWIEMA nowymi ścieżkami
    (`add_location` - reguła N-lokacji), a werdyktu nic nie gasi („ręka nietykalna"). Bez guardu
    taka klatka trafiała do „Duplikatów", których gest („która kopia zbędna") dotyczy klatek
    żywych - a jej pierwszą robotą jest werdykt ręki, którego przesłanka upadła. Bliźniaczka
    o tym samym kształcie, ale NIEwycofana, ZOSTAJE - guard ma wyciąć wycofanie, nie duplikat.
    Licznik Porządków czyta ten sam predykat i mówi to samo.

    Guard zastąpienia stoi obok z tego samego powodu, ale jego stanu nie budujemy: zastąpiona
    z obecną kopią jest naruszeniem inwariantu (`audit.supersede_invariants`), którego skan nie
    wytwarza (`repo.clear_superseded`) - test pinowałby ukrywanie złamanego stanu (D-V-9e).

    Falsyfikator: zdejmij `AND f.retired_at IS NULL` z `dup_frame_ids` - wycofana wraca do zbioru
    (a licznik Porządków pokazuje 2)."""
    from horreum import db

    con = db.open_db(":memory:")

    def _z_kopiami(sha, *sciezki):
        fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="light", filetype="fits",
                                   camera_id=None, now=NOW)
        return fid, [repo.add_location(con, frame_id=fid, volume="TESTVOL", path=p, now=NOW)[0]
                     for p in sciezki]

    wycofana, (lid,) = _z_kopiami("sha-wycofana", r"R:\ASTRO_\stary.fit")
    repo.mark_location_vanished(con, location_id=lid, expected_path=r"R:\ASTRO_\stary.fit",
                                root=r"R:\ASTRO_", run_id="g2-10d", now=NOW)
    assert repo.retire_frames(con, frame_ids=[wycofana], now=NOW).done == 1
    for p in (r"R:\ASTRO_\wrocil_a.fit", r"R:\ASTRO_\wrocil_b.fit"):   # re-skan: dwie kopie wracają
        repo.add_location(con, frame_id=wycofana, volume="TESTVOL", path=p, now=NOW)
    blizniaczka, _ = _z_kopiami("sha-blizniaczka", r"R:\ASTRO_\a.fit", r"R:\ASTRO_\b.fit")

    assert queries.dup_frame_ids(con) == {blizniaczka}
    assert queries.tasks_state(con)["dup_frames"] == 1
    # klatka nie znika z oczu: prowadzi do niej wiersz AKCYJNY „Wycofane, a plik wrócił"
    assert queries.retired_conflict_frame_ids(con) == {wycofana}


def _seed_stosy_z_powodami(con):
    """Pięć gotowych obrazów pokrywających WSZYSTKIE stany rodowodu: dwa czekające na gest, dwa ze
    zwietrzałym powodem (obiekt / odniesienie nadane PO przebiegu) i jeden z gotowym rodowodem."""
    con.execute("INSERT OR IGNORE INTO object(canon, catalog, kind) "
                "VALUES ('IC443','catalog','deep_sky')")
    oid = con.execute("SELECT id FROM object WHERE canon = 'IC443'").fetchone()[0]
    for fid in (901, 902, 903, 904, 905):
        # obiekt tylko tam, gdzie ma czynić powód nieaktualnym (902) — reszta bez, żeby test
        # mierzył POWÓD, nie obecność obiektu
        con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at, object_id) "
                    "VALUES (?, ?, 'master_light', 'xisf', ?, ?)",
                    (fid, f"m{fid}", NOW, oid if fid == 902 else None))
    wiersze = [(901, "degenerate_window", None),   # czeka na gest człowieka
               (902, "no_object", None),           # ZWIETRZAŁ — obiekt nadany po przebiegu
               (903, "offset_unknown", 60),        # ZWIETRZAŁ — odniesienie wskazane po przebiegu
               (904, "offset_unknown", None),      # czeka: odniesienia nikt nie wskazał
               (905, None, None)]                  # rodowód policzony — nie ma o co pytać
    for fid, powod, offset in wiersze:
        con.execute("INSERT INTO integration (id, master_frame_id, created_at, "
                    "unresolved_reason, utc_offset_min) VALUES (?, ?, ?, ?, ?)",
                    (fid, fid, NOW, powod, offset))
    con.commit()


def test_kubelek_rodowodu_bierze_tylko_powody_AKTUALNE(s8_obj):
    """Kubełek rodowodu (0808) liczy obrazy czekające NA GEST, a nie wszystkie z zapisanym powodem.

    Rozróżnienie nie jest kosmetyką komunikatu, tylko treścią kubełka: stos, którego powód
    zwietrzał, czeka na PRZELICZENIE etapem Dostawy, a nie na decyzję człowieka — wysłanie go
    do listy gestów byłoby wysłaniem po robotę, której tam nie ma. Zmierzone na żywej pf4 0808:
    46 stosów z powodem, z czego 11 zwietrzałych zaraz po nadaniu nazw ręką."""
    con, ids = s8_obj
    _seed_stosy_z_powodami(con)
    assert queries.lineage_pending_frame_ids(con) == {901, 904}


def test_licznik_porzadkow_rodowodu_JEST_dlugoscia_swojej_listy(s8_obj):
    """D-PD-10 dla kubełka rodowodu: wiersz Porządków i perspektywa, którą on otwiera, muszą liczyć
    TYM SAMYM predykatem. Osobny literał `COUNT` byłby drugim właścicielem i rozjechałby się przy
    pierwszej zmianie kształtu — user zobaczyłby „35" i listę na 46 pozycji."""
    con, ids = s8_obj
    _seed_stosy_z_powodami(con)
    assert queries.tasks_state(con)["stacks_lineage_pending"] \
        == len(queries.lineage_pending_frame_ids(con)) == 2


def test_zwietrzenie_powodu_ma_JEDNEGO_wlasciciela():
    """Ten sam predykat obsługuje panel „Rodowód" (jeden obraz) i perspektywę (całe archiwum),
    więc kontrakt wiersza jest wspólny: `unresolved_reason` + `object_now` + `utc_offset_min`
    + `inputs`. Powód spoza pary wrażliwej nie wietrzeje sam z siebie — inaczej sito zjadłoby
    robotę do zrobienia."""
    def wiersz(**kw):
        return {"unresolved_reason": None, "object_now": None, "utc_offset_min": None,
                "inputs": 0, **kw}

    assert queries.lineage_reason_stale(wiersz(unresolved_reason="no_object", object_now=7)) is True
    assert queries.lineage_reason_stale(wiersz(unresolved_reason="no_object")) is False
    assert queries.lineage_reason_stale(
        wiersz(unresolved_reason="offset_unknown", utc_offset_min=0)) is True, \
        "zero minut to WSKAZANE odniesienie (UTC), nie brak wskazania — trójstan migracji 0016"
    assert queries.lineage_reason_stale(
        wiersz(unresolved_reason="degenerate_window", object_now=7, utc_offset_min=60)) is False
    # WERDYKT RĘKI WIETRZY KAŻDY POWÓD: przebieg zostawia taki stos nietknięty (ranga `user`),
    # więc powód zamarza w bazie — bez tego członu obraz z potwierdzonym materiałem wracałby
    # do kubełka po każdym przeliczeniu.
    assert queries.lineage_reason_stale(
        wiersz(unresolved_reason="degenerate_window", inputs=9)) is True
    # …ale ODRZUCENIE wszystkich kandydatów nie jest rodowodem: `inputs` liczy niewykluczone.
    assert queries.lineage_reason_stale(
        wiersz(unresolved_reason="degenerate_window", inputs=0)) is False


def test_tasks_state_reaguje_na_stan_nie_eventy(s8_obj):
    """REVIEW-ZE-STANU: nazwanie teleskopu ZDEJMUJE go z licznika (stan bieżący), a liczba eventów
    nie ma znaczenia. Scalenie też zdejmuje (licznik tylko kanonicznych)."""
    con, ids = s8_obj
    repo.label_telescope(con, telescope_id=ids["A"], label="A140R", now=NOW)
    assert queries.tasks_state(con)["telescopes_unlabeled"] == 3
    repo.merge_telescope(con, source_id=ids["B"], target_id=ids["C"], now=NOW)
    assert queries.tasks_state(con)["telescopes_unlabeled"] == 2   # B scalony → poza kanonem


def test_tasks_state_pusta_baza_same_zera(tmp_path):
    from horreum import db
    con = db.open_db(str(tmp_path / "empty.db"))
    try:
        assert all(v == 0 for v in queries.tasks_state(con).values())
    finally:
        con.close()


# --- guard mieszania serialu (F5R#3) ---

def test_has_real_volume_locations(s8_obj, tmp_path):
    """Baza fixture ma lokacje z realnymi serialami (vol1/vol2/vol3) → True; świeża/pusta → False;
    baza znająca WYŁĄCZNIE '?' → False (czysty świat placeholdera nie blokuje skanu)."""
    con, ids = s8_obj
    assert queries.has_real_volume_locations(con) is True

    from horreum import db
    fresh = db.open_db(str(tmp_path / "fresh.db"))
    try:
        assert queries.has_real_volume_locations(fresh) is False
        fid, _ = repo.upsert_frame(fresh, sha1_data="sha-q", kind="light", filetype="fits",
                                   camera_id=None, now=NOW)
        repo.add_location(fresh, frame_id=fid, volume="?", path="/x/q.fits", now=NOW)
        assert queries.has_real_volume_locations(fresh) is False   # sam '?' nie jest „realny"
    finally:
        fresh.close()


# --- P4 (#8/Z6): alias_target + unreadable_copies ---

def test_alias_target_trafia_i_milczy(s8_obj):
    """`alias_target` = pre-check konfliktu w dialogu (#8): znany alias → object_id, nieznany → None."""
    con, ids = s8_obj
    assert queries.alias_target(con, "FLATWIZARD") is None          # fixture nie zna aliasu
    repo.add_object_alias(con, alias_norm="FLATWIZARD",
                          object_id=ids["objects"]["NGC7000"], source="user", now=NOW)
    assert queries.alias_target(con, "FLATWIZARD") == ids["objects"]["NGC7000"]


def test_unreadable_copies_per_kopia_nie_per_klatka(s8_obj):
    """Z6/#13: drążenie niesie DOKŁADNE KOPIE — klatka z 2 oznaczonymi kopiami = 2 wiersze;
    oznaczona+czysta = 1 wiersz; `present` per kopia (oznaczona może być present=0 — znikła
    po oznaczeniu i to MA być widoczne). ORDER: najnowsze oznaczenie na górze."""
    con, ids = s8_obj
    assert queries.unreadable_copies(con) == []                     # fixture bez oznaczeń
    locs = con.execute(
        "SELECT id, volume FROM location WHERE frame_id = ? ORDER BY id",
        (ids["frames"]["a1"],)).fetchall()
    assert len(locs) == 2                                           # a1: vol1 + vol2 (fixture R#3)
    repo.refresh_location_unreadable(con, location_id=locs[0]["id"], sha1_data="sha-a1",
                                     path="/astro/a1.fits", mtime="t2", reason="OSError",
                                     kind="io", now=NOW)
    repo.refresh_location_unreadable(con, location_id=locs[1]["id"], sha1_data="sha-a1",
                                     path="/backup/a1.fits", mtime="t2", reason="OSError",
                                     kind="io", now="2026-06-29T13:00:01")
    rows = queries.unreadable_copies(con)
    assert len(rows) == 2                                           # DWIE kopie tej samej klatki
    assert [r["volume"] for r in rows] == ["vol2", "vol1"]          # nowsze oznaczenie na górze
    assert {r["path"] for r in rows} == {"/astro/a1.fits", "/backup/a1.fits"}
    assert all(r["frame_id"] == ids["frames"]["a1"] and r["present"] == 1 for r in rows)
    # oznaczona kopia, która POTEM zniknęła (present=0), dalej wynika z markera (forward-guard #13)
    with con:
        con.execute("UPDATE location SET present = 0 WHERE id = ?", (locs[0]["id"],))
    rows = queries.unreadable_copies(con)
    assert len(rows) == 2
    assert {r["present"] for r in rows} == {0, 1}


def test_unreadable_copies_czysta_kopia_poza_lista(s8_obj):
    """Klatka z JEDNĄ oznaczoną i JEDNĄ czystą kopią → tylko oznaczona na liście (1 wiersz)."""
    con, ids = s8_obj
    loc = con.execute("SELECT id FROM location WHERE volume = 'vol2'").fetchone()
    repo.refresh_location_unreadable(con, location_id=loc["id"], sha1_data="sha-a1",
                                     path="/backup/a1.fits", mtime="t2", reason="OSError",
                                     kind="io", now=NOW)
    rows = queries.unreadable_copies(con)
    assert len(rows) == 1 and rows[0]["volume"] == "vol2"
    # review_queue niesie ten sam fakt licznikiem per-KLATKA (DISTINCT, spójność z resolverem)
    assert queries.review_queue(con)["unreadable_count"] == 1


def test_unreadable_copies_rodzaj_i_powod_z_kolumny_per_KOPIA(s8_obj):
    """Z6/P4-2: `kind`/`reason` opisują TĘ kopię, nie klatkę - obie kopie `a1` mają tę samą
    tożsamość, a każda niesie własną diagnozę, bo mieszka ona w wierszu `location`. Powód bez
    prefiksu dziennika (to kolumna, nie `event.reason`).

    Falsyfikator: wróć do powodu z dziennika (podzapytanie po `event`) → `kind` znika, a powód
    wraca z prefiksem - obie asercje czerwienieją."""
    con, ids = s8_obj
    locs = con.execute("SELECT id, path FROM location WHERE frame_id = ? ORDER BY id",
                       (ids["frames"]["a1"],)).fetchall()
    repo.refresh_location_unreadable(con, location_id=locs[0]["id"], sha1_data="sha-a1",
                                     path=locs[0]["path"], mtime="t2",
                                     reason="OSError: [Errno 5] I/O error", kind="io", now=NOW)
    repo.refresh_location_unreadable(con, location_id=locs[1]["id"], sha1_data="sha-a1",
                                     path=locs[1]["path"], mtime="t2",
                                     reason="ParseError: line 4, column 5322", kind="parse",
                                     now="2026-06-29T13:00:01")
    diagnozy = {r["path"]: (r["kind"], r["reason"]) for r in queries.unreadable_copies(con)}
    assert diagnozy[locs[0]["path"]] == ("io", "OSError: [Errno 5] I/O error")
    assert diagnozy[locs[1]["path"]] == ("parse", "ParseError: line 4, column 5322")


def test_unreadable_copies_powod_najswiezszy_bije_starszy(s8_obj):
    """Powód to OSTATNIE zeznanie o kopii, nie pierwsze: kolejna awaria z inną diagnozą przestawia
    kolumnę, a marker (`unreadable_since`) zostaje przy PIERWSZYM czasie — to dwa różne fakty."""
    con, ids = s8_obj
    loc = con.execute("SELECT id, path FROM location WHERE volume = 'vol2'").fetchone()
    repo.refresh_location_unreadable(con, location_id=loc["id"], sha1_data="sha-a1",
                                     path=loc["path"], mtime="t2", reason="OSError", kind="io",
                                     now=NOW)
    # nowa próba: inny mtime i inna diagnoza (P4-2: ten sam mtime też przestawia kolumny)
    repo.refresh_location_unreadable(con, location_id=loc["id"], sha1_data="sha-a1",
                                     path=loc["path"], mtime="t3", reason="ParseError",
                                     kind="parse", now="2026-06-30T09:00:00")
    row = queries.unreadable_copies(con)[0]
    assert (row["kind"], row["reason"]) == ("parse", "ParseError")
    assert row["unreadable_since"] == NOW                       # marker trzyma PIERWSZĄ awarię


def test_unreadable_copies_kopia_przemianowana_zachowuje_powod(s8_obj):
    """P4-2 - defekt starego źródła: payload dziennika trzymał ścieżkę Z CHWILI awarii, więc kopia
    przemianowana po oznaczeniu gubiła powód (powierzchnia pokazywała myślnik przy kopii, o której
    wiadomo, co jej jest). Powód w kolumnie mieszka w tym samym wierszu co `path`, więc
    przemianowanie go nie rusza.

    Falsyfikator: wróć do podzapytania po `event` z `json_extract(payload, '$.path') = l.path` →
    po przemianowaniu `reason IS NULL` i asercja czerwienieje."""
    con, ids = s8_obj
    loc = con.execute("SELECT id, path FROM location WHERE volume = 'vol2'").fetchone()
    repo.refresh_location_unreadable(con, location_id=loc["id"], sha1_data="sha-a1",
                                     path=loc["path"], mtime="t2", reason="OSError", kind="io",
                                     now=NOW)
    with con:
        con.execute("UPDATE location SET path = ? WHERE id = ?", ("/backup/a1-NOWA.fits", loc["id"]))
    row = queries.unreadable_copies(con)[0]
    assert row["path"] == "/backup/a1-NOWA.fits"
    assert (row["kind"], row["reason"]) == ("io", "OSError")


def test_unreadable_kind_counts_po_kopiach_sumuje_sie_do_drazenia(s8_obj):
    """P4-2: rozbicie kubełka po rodzaju liczy KOPIE - klatka `a1` z dwiema kopiami o RÓŻNYCH
    rodzajach wchodzi do obu przegródek, a suma równa się długości drążenia (`unreadable_copies`),
    czyli temu, co user zobaczy po kliknięciu. Kopia sprzed 0019 (marker bez rodzaju) → „unknown".
    Błąd bazy po naszej stronie (`'db'`) ma WŁASNĄ przegródkę - nie jest faktem o pliku, więc nie
    wolno mu wpaść ani do „unknown", ani do rodzajów plikowych. Licznik wiersza
    (`unreadable_count`) zostaje przy klatkach - to inna jednostka.

    Falsyfikator: licz `count(DISTINCT frame_id)` → klatka `a1` znika z jednej przegródki i suma
    rozjeżdża się z drążeniem; zdejmij `"db"` ze słownika startowego → rozbicie nie ma przegródki
    `db` przy zerze i pierwsza asercja czerwienieje."""
    con, ids = s8_obj
    assert queries.unreadable_kind_counts(con) == {"io": 0, "parse": 0, "db": 0, "unknown": 0}
    locs = con.execute("SELECT id, path FROM location WHERE frame_id = ? ORDER BY id",
                       (ids["frames"]["a1"],)).fetchall()
    repo.refresh_location_unreadable(con, location_id=locs[0]["id"], sha1_data="sha-a1",
                                     path=locs[0]["path"], mtime="t2", reason="OSError: x",
                                     kind="io", now=NOW)
    repo.refresh_location_unreadable(con, location_id=locs[1]["id"], sha1_data="sha-a1",
                                     path=locs[1]["path"], mtime="t2", reason="ParseError: y",
                                     kind="parse", now=NOW)
    inna = con.execute("SELECT id FROM location WHERE frame_id <> ? ORDER BY id LIMIT 1",
                       (ids["frames"]["a1"],)).fetchone()
    with con:                                                   # wiersz sprzed 0019: marker bez rodzaju
        con.execute("UPDATE location SET unreadable_since = ? WHERE id = ?", (NOW, inna["id"]))
    a2, _ = repo.add_location(con, frame_id=ids["frames"]["a2"], volume="vol1",
                              path="/astro/a2.fits", now=NOW)
    repo.refresh_location_unreadable(con, location_id=a2, sha1_data="sha-a2",
                                     path="/astro/a2.fits", mtime="t2",
                                     reason="OperationalError: database is locked", kind="db",
                                     now=NOW)
    counts = queries.unreadable_kind_counts(con)
    assert counts == {"io": 1, "parse": 1, "db": 1, "unknown": 1}
    assert sum(counts.values()) == len(queries.unreadable_copies(con))
    assert queries.review_queue(con)["unreadable_count"] == 3   # KLATKI: a1 + a2 + ta druga


def test_drazenie_i_rozbicie_nieczytelnych_licza_TE_SAME_klatki_co_licznik():
    """P4-2 (bramka pakietu): licznik kubełka „kopie nieczytelne" (`resolver.review_state.unreadable`)
    pomija klatki zastąpione i wycofane - kubełek jest listą ROBOTY, a robotę zastąpionej przejęła
    następczyni, wycofanej zamknęła ręka (argument `G2-6d`). Drążenie (`unreadable_copies`)
    i rozbicie po rodzaju (`unreadable_kind_counts`) muszą liczyć te same klatki, inaczej wiersz
    mówi „1 klatka", a pod kliknięciem stoją kopie trzech. Stan jest osiągalny zwykłą drogą:
    klatkę zastąpiono albo wycofano po zniknięciu jej kopii, plik potem wrócił, ale nie dał się
    przeczytać - backstop skanu stawia marker, nie pytając o los klatki.

    Falsyfikator: zdejmij `AND f.superseded_by IS NULL AND f.retired_at IS NULL` z
    `unreadable_copies` → drążenie ma trzy klatki przy liczniku 1 i asercje drążenia czerwienieją;
    to samo w `unreadable_kind_counts` → rozbicie ma `parse`/`db` i suma 3 zamiast 1."""
    from horreum import db, resolver

    con = db.open_db(":memory:")
    root = r"R:\ASTRO_"
    kopie = {}
    for nazwa in ("zywa", "zastapiona", "wycofana"):
        fid, _ = repo.upsert_frame(con, sha1_data=f"sha-{nazwa}", kind="light", filetype="fits",
                                   camera_id=None, now=NOW)
        path = rf"{root}\{nazwa}.fit"
        lid, _ = repo.add_location(con, frame_id=fid, volume="TESTVOL", path=path, now=NOW)
        kopie[nazwa] = (fid, lid, path)
    nastepczyni, _ = repo.upsert_frame(con, sha1_data="sha-nastepczyni", kind="light",
                                       filetype="fits", camera_id=None, now=NOW)
    for nazwa in ("zastapiona", "wycofana"):                   # kopia znika - dopiero wtedy
        _fid, lid, path = kopie[nazwa]                          # klingi przyjmują klatkę
        repo.mark_location_vanished(con, location_id=lid, expected_path=path, root=root,
                                    run_id="p4-2", now=NOW)
    assert repo.mark_superseded(con, frame_id=kopie["zastapiona"][0], superseded_by=nastepczyni,
                                now=NOW) is True
    assert repo.retire_frames(con, frame_ids=[kopie["wycofana"][0]], now=NOW).done == 1
    for nazwa, kind in (("zywa", "io"), ("zastapiona", "parse"), ("wycofana", "db")):
        _fid, lid, path = kopie[nazwa]                          # plik wrócił nieczytelny
        repo.refresh_location_unreadable(con, location_id=lid, sha1_data=f"sha-{nazwa}",
                                         path=path, mtime="t2", reason="X: y", kind=kind, now=NOW)

    wiersze = queries.unreadable_copies(con)
    assert {r["frame_id"] for r in wiersze} == {kopie["zywa"][0]}
    assert resolver.review_state(con).unreadable == len({r["frame_id"] for r in wiersze}) == 1
    counts = queries.unreadable_kind_counts(con)
    assert counts == {"io": 1, "parse": 0, "db": 0, "unknown": 0}
    assert sum(counts.values()) == len(wiersze)
    con.close()


# --- telescope_label: JEDEN właściciel reguły label→canon (P-B) ---

def test_telescope_label_nazwa_usera_bije_canon(s8):
    con, ids = s8
    repo.label_telescope(con, telescope_id=ids["A"], label="Askar 140", now=NOW)
    row = next(r for r in queries.active_telescopes(con) if r["id"] == ids["A"])
    assert queries.telescope_label(row) == "Askar 140"


def test_telescope_label_bez_nazwy_spada_na_canon(s8):
    """Cała oś bywa `proposed` (realny stan po imporcie) — kolumna nie milczy, mówi nagłówkiem."""
    con, ids = s8
    row = next(r for r in queries.active_telescopes(con) if r["id"] == ids["C"])
    assert row["label"] is None and queries.telescope_label(row) == "RC8"


def test_telescope_label_ten_sam_wynik_na_wierszu_osi_i_klatki(s8):
    """Ta sama kolumna ma DWA zapisy — `label` na wierszu osi, `telescope_label` w JOIN-ie klatki.
    Właściciel zna oba, więc lista teleskopów i tabela klatek nie mają jak powiedzieć czegoś innego
    o tym samym teleskopie."""
    con, ids = s8
    repo.label_telescope(con, telescope_id=ids["A"], label="Askar 140", now=NOW)
    os_row = next(r for r in queries.active_telescopes(con) if r["id"] == ids["A"])
    frame_row = queries.base_rows(con, [ids["frames"]["a1"]])[0]
    assert "telescope_label" not in os_row.keys() and "label" not in frame_row.keys()
    assert queries.telescope_label(frame_row) == queries.telescope_label(os_row) == "Askar 140"


def test_telescope_label_klatka_bez_osi_pusty_string(s8):
    """`config_id NULL` (review) → klatka nie ma osi: '' zamiast None, bo komórka tabeli i etykieta
    kubełka chcą stringa. Brak osi to stan, nie brak danych."""
    con, ids = s8
    row = queries.base_rows(con, [ids["frames"]["nullcfg"]])[0]
    assert row["telescope_label"] is None and row["telescop_canon"] is None
    assert queries.telescope_label(row) == ""


def test_regula_label_canon_ma_jednego_wlasciciela():
    """BRAMKA po P-B (SIN-DUP): fallback `… or …["telescop_canon"]` wolno napisać WYŁĄCZNIE
    w `gui/queries.py` (`telescope_label`). Reguła siedziała w czterech miejscach warstwy widżetów
    i zdążyła się rozjechać o końcowe `or ""` — znalezisko jednostkowe podniesione do kontroli, żeby
    nie wróciło. AST, nie regex: docstring opisujący regułę (jak ten) nie ma prawa dać trafienia.
    Krotka nazw kolumn w `projection.LAYOUTS` to NIE `or` — coalesce w danych (D-P1) zostaje poza
    bramką świadomie."""
    pkg = Path(horreum.__file__).parent
    offenders = []
    for path in sorted(pkg.rglob("*.py")):
        if path.name == "queries.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
                continue
            for value in node.values:
                if (isinstance(value, ast.Subscript) and isinstance(value.slice, ast.Constant)
                        and value.slice.value == "telescop_canon"):
                    offenders.append(f"{path.relative_to(pkg)}:{node.lineno}")
    assert not offenders, f"reguła label→telescop_canon poza `queries.telescope_label`: {offenders}"


# ---------- D-V-9: jeden wybór adresu, trzy powierzchnie (SPOT) ----------

_ADRES_ZYWEJ_KOPII = ("COALESCE("
                      "(SELECT MIN(id) FROM location WHERE frame_id = f.id AND present = 1), "
                      "(SELECT MIN(id) FROM location WHERE frame_id = f.id))")
_WLASCICIELE_ADRESU = {"object_frames", "object_review_frames", "base_rows"}


def _sql_wykonywany(zrodlo):
    """SQL-literały podane do `.execute(...)`, znormalizowane białymi znakami, per funkcja.
    AST, nie regex - docstring opisujący regułę (jak ten) nie ma prawa dać trafienia."""
    drzewo = ast.parse(zrodlo)
    rodzic = {}
    for fn in ast.walk(drzewo):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for w in ast.walk(fn):
                rodzic.setdefault(id(w), fn.name)
    out = []
    for node in ast.walk(drzewo):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("execute", "executemany")):
            continue
        arg = node.args[0] if node.args else None
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            sql = re.sub(r"\s+", " ", arg.value).replace("( ", "(").replace(" )", ")")
            out.append((rodzic.get(id(node), "<modul>"), sql))
    return out


def test_wybor_adresu_ma_dokladnie_trzech_wlascicieli():
    """BRAMKA D-V-9 (SIN-DUP, wzorzec bramki `telescop_canon` wyżej): regułę „spośród kopii wygrywa
    ŻYWA, z powrotem do dowolnej" trzy read-modele deklarują jako „ZNAK W ZNAK tę samą" - i do tej
    bramki była to WYŁĄCZNIE obietnica prozy w docstringu (zarzut Z1 bramki pakietu 2026-08-14).
    Edycja jednego literału z trzech nie łamała niczego, a rozjazd znaczyłby, że ekran i lista do
    zapisu pokazują RÓŻNE kopie tej samej klatki.

    Stała modułu ODPADA jako lekarstwo: bramka AST zapisu (`test_repo_safety.py`) żąda SQL-a
    LITERAŁOWEGO, więc sklejanie go ze stałej zrobiłoby z tych zapytań „SQL dynamiczny" poza
    `repo.py`. Skoro duplikat jest wymuszony, pilnuje go kontrola, nie dobra wola."""
    zrodlo = (Path(horreum.__file__).parent / "gui" / "queries.py").read_text(encoding="utf-8")
    trafienia = [fn for fn, sql in _sql_wykonywany(zrodlo) if _ADRES_ZYWEJ_KOPII in sql]
    assert set(trafienia) == _WLASCICIELE_ADRESU, f"właściciele reguły adresu rozjechali się: {trafienia}"
    assert len(trafienia) == len(_WLASCICIELE_ADRESU), f"reguła adresu powtórzona poza spisem: {trafienia}"
