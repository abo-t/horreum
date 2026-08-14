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
    }


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
                                     path="/astro/a1.fits", mtime="t2", reason="OSError", now=NOW)
    repo.refresh_location_unreadable(con, location_id=locs[1]["id"], sha1_data="sha-a1",
                                     path="/backup/a1.fits", mtime="t2", reason="OSError",
                                     now="2026-06-29T13:00:01")
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
                                     path="/backup/a1.fits", mtime="t2", reason="OSError", now=NOW)
    rows = queries.unreadable_copies(con)
    assert len(rows) == 1 and rows[0]["volume"] == "vol2"
    # review_queue niesie ten sam fakt licznikiem per-KLATKA (DISTINCT, spójność z resolverem)
    assert queries.review_queue(con)["unreadable_count"] == 1


def test_unreadable_copies_powod_z_dziennika_per_KOPIA(s8_obj):
    """Z6: `reason` opisuje TĘ kopię, nie klatkę. Obie kopie `a1` mają ten sam `target sha1:`,
    więc rozstrzyga `payload.path` — po samym sha1 każdy wiersz dostałby powód drugiej kopii."""
    con, ids = s8_obj
    locs = con.execute("SELECT id, path FROM location WHERE frame_id = ? ORDER BY id",
                       (ids["frames"]["a1"],)).fetchall()
    repo.refresh_location_unreadable(con, location_id=locs[0]["id"], sha1_data="sha-a1",
                                     path=locs[0]["path"], mtime="t2",
                                     reason="OSError: [Errno 5] I/O error", now=NOW)
    repo.refresh_location_unreadable(con, location_id=locs[1]["id"], sha1_data="sha-a1",
                                     path=locs[1]["path"], mtime="t2",
                                     reason="ParseError: line 4, column 5322",
                                     now="2026-06-29T13:00:01")
    powody = {r["path"]: r["reason"] for r in queries.unreadable_copies(con)}
    assert powody[locs[0]["path"]] == "kopia nieczytelna: OSError: [Errno 5] I/O error"
    assert powody[locs[1]["path"]] == "kopia nieczytelna: ParseError: line 4, column 5322"


def test_unreadable_copies_powod_najswiezszy_bije_starszy(s8_obj):
    """Powód to OSTATNIE zeznanie o kopii, nie pierwsze: kolejna awaria z inną diagnozą przestawia
    kolumnę, a marker (`unreadable_since`) zostaje przy PIERWSZYM czasie — to dwa różne fakty."""
    con, ids = s8_obj
    loc = con.execute("SELECT id, path FROM location WHERE volume = 'vol2'").fetchone()
    repo.refresh_location_unreadable(con, location_id=loc["id"], sha1_data="sha-a1",
                                     path=loc["path"], mtime="t2", reason="OSError", now=NOW)
    # nowa próba: inny mtime (inaczej repo robi cichy no-op bez eventu) i inna diagnoza
    repo.refresh_location_unreadable(con, location_id=loc["id"], sha1_data="sha-a1",
                                     path=loc["path"], mtime="t3", reason="ParseError",
                                     now="2026-06-30T09:00:00")
    row = queries.unreadable_copies(con)[0]
    assert row["reason"] == "kopia nieczytelna: ParseError"
    assert row["unreadable_since"] == NOW                       # marker trzyma PIERWSZĄ awarię


def test_unreadable_copies_kopia_przemianowana_bez_powodu(s8_obj):
    """Payload dziennika trzyma ścieżkę Z CHWILI awarii. Po przemianowaniu kopii para (sha1, path)
    nie ma pokrycia → `reason IS NULL`, bo powód pożyczony od innej kopii byłby zmyśleniem;
    powierzchnia pokazuje wtedy „—" (`app._copy_reason`)."""
    con, ids = s8_obj
    loc = con.execute("SELECT id, path FROM location WHERE volume = 'vol2'").fetchone()
    repo.refresh_location_unreadable(con, location_id=loc["id"], sha1_data="sha-a1",
                                     path=loc["path"], mtime="t2", reason="OSError", now=NOW)
    assert queries.unreadable_copies(con)[0]["reason"] == "kopia nieczytelna: OSError"
    with con:
        con.execute("UPDATE location SET path = ? WHERE id = ?", ("/backup/a1-NOWA.fits", loc["id"]))
    row = queries.unreadable_copies(con)[0]
    assert row["path"] == "/backup/a1-NOWA.fits" and row["reason"] is None


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
