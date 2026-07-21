"""Read-model osi TELESKOP (`horreum.gui.queries`, PLAN_gui §5/§7) — CZYSTA logika, BEZ Qt
(ten plik nie importuje PySide6, więc wlicza się do pełnego `pytest` w środowisku bez Qt, §7.2).

Pokrycie: aktywne teleskopy z licznością (kanon-filtr JAWNY, kolizja kamery, frame `config NULL`
poza sumą, `frame_count=0` dla teleskopu bez klatek), roll-up po scaleniu + zniknięcie source,
`merged_under`, audyt eventów (cała oś vs jeden teleskop), oraz że odczyt nie pisze do bazy."""
import json

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
    MA obiekt); dups = a1 (2×present=1); teleskopy A–D wszystkie bez etykiety; zero obserwatoriów
    i XISF; vanished = present0 (jedyna lokacja present=0) — bez guardu EXISTS licznik złapałby też
    klatki BEZ lokacji w ogóle (w fixture jest ich 10)."""
    con, ids = s8_obj
    st = queries.tasks_state(con)
    assert st == {
        "unresolved_lights": 3,
        "dup_frames": 1,
        "telescopes_unlabeled": 4,
        "observatories_unnamed": 0,
        "xisf_frames": 0,
        "vanished_frames": 1,
    }


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
