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
