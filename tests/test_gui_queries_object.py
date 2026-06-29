"""Read-model osi OBIEKT (`horreum.gui.queries`, PLAN_gui_object §3/§7) — CZYSTA logika, BEZ Qt
(plik nie importuje PySide6 → wlicza się do pełnego `pytest` bez Qt, §7.2).

Pokrycie scenariuszy §6: R1 kind-awareness (kalibracja poza), R2 kanoniczność teleskopu w filtrze
(roll-up po merge), R3 dedup 1:N location, R4 review = stan (idempotencja po re-resolve), R5/R7
rozłączność kanałów review (config-review vs headerless vs obiekt-review), R7 present=0 wciąż widoczny.
Oraz: odczyt nie pisze."""

from horreum import repo
from horreum.gui import queries

NOW = "2026-06-29T14:00:00"


# --- library_objects: zestaw, liczność, kind-awareness (R1) ---

def test_library_bez_filtra_zestaw_i_licznosc(s8_obj):
    con, ids = s8_obj
    rows = queries.library_objects(con)
    by_canon = {r["canon"]: r["frame_count"] for r in rows}
    # NGC7000: a1,a2 (A) + c1,c2 (C) + present0 (config NULL) = 5; M42: b1,b2,b3 = 3
    assert by_canon == {"M42": 3, "NGC7000": 5}
    # ORDER BY canon (M42 < NGC7000)
    assert [r["canon"] for r in rows] == ["M42", "NGC7000"]
    # catalog zwracany, BEZ kolumny object.kind (R#1)
    ngc = next(r for r in rows if r["canon"] == "NGC7000")
    assert ngc["catalog"] == "NGC"
    assert "kind" not in ngc.keys()


def test_library_kalibracja_nie_wlicza_sie(s8_obj):
    """R1: flat (calib_flat) nie ma obiektu i nie jest light → nie tworzy ani nie podbija żadnego
    wiersza biblioteki."""
    con, ids = s8_obj
    total = sum(r["frame_count"] for r in queries.library_objects(con))
    assert total == 8                       # 5 NGC7000 + 3 M42; kalibracja i obiekt-review poza


# --- library_objects: filtry (R2 + camera + filter) ---

def test_library_filtr_teleskop_kanoniczny(s8_obj):
    con, ids = s8_obj
    A, B, C = ids["A"], ids["B"], ids["C"]
    # teleskop A → tylko NGC7000 (a1,a2 = 2); B → M42 (3); C → NGC7000 (c1,c2 = 2)
    assert {r["canon"]: r["frame_count"] for r in queries.library_objects(con, telescope_id=A)} \
        == {"NGC7000": 2}
    assert {r["canon"]: r["frame_count"] for r in queries.library_objects(con, telescope_id=B)} \
        == {"M42": 3}
    assert {r["canon"]: r["frame_count"] for r in queries.library_objects(con, telescope_id=C)} \
        == {"NGC7000": 2}


def test_library_filtr_teleskop_rolluje_po_merge(s8_obj):
    """R2: po merge(A→B) filtr po kanonie B zwraca też klatki spod A (rolują się przez
    telescope_canonical). Klatki present0 (config NULL) NIE należą do żadnego teleskopu."""
    con, ids = s8_obj
    A, B = ids["A"], ids["B"]
    repo.merge_telescope(con, source_id=A, target_id=B, now=NOW)
    by_canon = {r["canon"]: r["frame_count"] for r in queries.library_objects(con, telescope_id=B)}
    # B teraz spina M42 (b1..b3 = 3) + NGC7000 spod A (a1,a2 = 2)
    assert by_canon == {"M42": 3, "NGC7000": 2}


def test_library_filtr_kamera_i_filter(s8_obj):
    con, ids = s8_obj
    cam1, cam2 = ids["cam1"], ids["cam2"]
    # cam1: NGC7000(a1,a2,present0)+M42(b1,b2,b3); cam2: NGC7000(c1,c2). present0 jest cam1.
    assert {r["canon"]: r["frame_count"] for r in queries.library_objects(con, camera_id=cam1)} \
        == {"M42": 3, "NGC7000": 3}
    assert {r["canon"]: r["frame_count"] for r in queries.library_objects(con, camera_id=cam2)} \
        == {"NGC7000": 2}
    # filter Ha tylko na a1,a2 (NGC7000)
    assert {r["canon"]: r["frame_count"] for r in queries.library_objects(con, filter_canon="Ha")} \
        == {"NGC7000": 2}


# --- object_frames: dedup 1:N location (R3), present=0 widoczny (R7) ---

def test_object_frames_dedup_location(s8_obj):
    """R3: a1 ma DWIE lokalizacje — object_frames pokazuje ją RAZ (MIN(id)); liczność klatek ==
    liczność frame'ów, nie lokalizacji."""
    con, ids = s8_obj
    rows = queries.object_frames(con, ids["objects"]["NGC7000"])
    fids = [r["frame_id"] for r in rows]
    assert len(fids) == len(set(fids)) == 5           # a1,a2,c1,c2,present0 — każdy raz mimo 1:N
    a1_rows = [r for r in rows if r["frame_id"] == ids["frames"]["a1"]]
    assert len(a1_rows) == 1
    assert a1_rows[0]["path"] == "/astro/a1.fits"      # MIN(id) → pierwsza lokalizacja


def test_object_frames_present0_wciaz_widoczny(s8_obj):
    """R7: present0 ma JEDYNĄ lokalizację present=0 — MUSI być w wyniku (tożsamość=sha1, nie obecność);
    present jako KOLUMNA statusu, nie predykat odsiewający."""
    con, ids = s8_obj
    rows = queries.object_frames(con, ids["objects"]["NGC7000"])
    p0 = next(r for r in rows if r["frame_id"] == ids["frames"]["present0"])
    assert p0["present"] == 0                          # widoczny mimo zniknięcia pliku
    assert p0["path"] == "/astro/present0.fits"


def test_object_frames_telescope_label_i_filtr(s8_obj):
    con, ids = s8_obj
    A = ids["A"]
    rows = queries.object_frames(con, ids["objects"]["NGC7000"], telescope_id=A)
    # tylko a1,a2 (pod teleskopem A); present0/c* odpadają (inny teleskop / config NULL)
    assert {r["frame_id"] for r in rows} == {ids["frames"]["a1"], ids["frames"]["a2"]}


# --- review_queue: kanały ze STANU (R4, R5, R7/R#2) ---

def test_review_queue_kanaly(s8_obj):
    con, ids = s8_obj
    q = queries.review_queue(con)
    # obiekt-review: FlatWizard ×2 (objrev1, objrev2)
    assert [(r["object_raw"], r["n"]) for r in q["object_review"]] == [("FlatWizard", 2)]
    # config-review = config NULL AND EXISTS(header): objrev1, objrev2, calib_flat, present0 = 4
    # (nullcfg ma config NULL ale BEZ headera → NIE liczy się tutaj — R#2)
    assert q["config_review_count"] == 4
    # headerless = NOT EXISTS(header): tylko nullcfg
    assert q["headerless_count"] == 1


def test_review_queue_headerless_rozlaczny_od_config_review(s8_obj):
    """R#2: nullcfg (config NULL, BEZ headera) trafia do headerless, NIE do config-review — gdyby
    config-review liczył samo `config_id IS NULL`, nullcfg zawyżyłby go do 5."""
    con, ids = s8_obj
    q = queries.review_queue(con)
    # gdyby brak EXISTS(header): config NULL = objrev1,objrev2,calib_flat,present0,nullcfg = 5
    assert q["config_review_count"] == 4              # nullcfg odsiany przez EXISTS(header)


def test_review_queue_idempotentny_po_re_resolve(s8_obj):
    """R4: ponowny przebieg resolvera (mnoży eventy object.review_summary/config.review) NIE zmienia
    kolejki — derywacja ze STANU, nie ze zliczania eventów."""
    from horreum import resolver
    con, ids = s8_obj
    before = queries.review_queue(con)
    resolver.run_resolver(con, now=NOW)               # re-resolve: eventy się mnożą, stan nie
    after = queries.review_queue(con)
    assert [(r["object_raw"], r["n"]) for r in before["object_review"]] \
        == [(r["object_raw"], r["n"]) for r in after["object_review"]]
    assert before["config_review_count"] == after["config_review_count"]
    assert before["headerless_count"] == after["headerless_count"]


def test_review_queue_frame_rozwiazany_znika(s8_obj):
    """Frame, który DOSTAŁ obiekt, opuszcza obiekt-review."""
    con, ids = s8_obj
    # rozwiąż objrev1 → przypisz NGC7000 (jak zrobiłby przyszły write usera)
    repo.assign_object(con, frame_id=ids["frames"]["objrev1"],
                       object_id=ids["objects"]["NGC7000"], object_source="user", now=NOW)
    q = queries.review_queue(con)
    assert [(r["object_raw"], r["n"]) for r in q["object_review"]] == [("FlatWizard", 1)]


def test_object_review_frames_drazenie(s8_obj):
    con, ids = s8_obj
    rows = queries.object_review_frames(con, "FlatWizard")
    assert {r["frame_id"] for r in rows} == {ids["frames"]["objrev1"], ids["frames"]["objrev2"]}


# --- facets ---

def test_facets_teleskop_kanoniczne_i_filtry(s8_obj):
    con, ids = s8_obj
    tel = queries.telescope_facets(con)
    assert {r["id"] for r in tel} == {ids["A"], ids["B"], ids["C"], ids["D"]}
    repo.merge_telescope(con, source_id=ids["A"], target_id=ids["B"], now=NOW)
    tel2 = {r["id"] for r in queries.telescope_facets(con)}
    assert ids["A"] not in tel2                        # scalony nie jest facetem (merged_into NOT NULL)
    filt = [r["filter_canon"] for r in queries.filter_facets(con)]
    assert filt == ["Ha", "OIII"]                     # distinct, posortowane


# --- odczyt nie pisze ---

def test_object_read_model_nie_emituje_eventow(s8_obj):
    con, ids = s8_obj
    before = con.execute("SELECT count(*) FROM event").fetchone()[0]
    queries.library_objects(con)
    queries.library_objects(con, telescope_id=ids["A"], camera_id=ids["cam1"], filter_canon="Ha")
    queries.object_frames(con, ids["objects"]["NGC7000"])
    queries.review_queue(con)
    queries.object_review_frames(con, "FlatWizard")
    queries.telescope_facets(con)
    queries.filter_facets(con)
    after = con.execute("SELECT count(*) FROM event").fetchone()[0]
    assert before == after


# --- telescope-liczniki NIENARUSZONE rozszerzeniem (regresja) ---

def test_rozszerzenie_nie_rusza_licznosci_teleskopu(s8_obj):
    """fixture obiektowa NIE zmienia `{A:2,B:3,C:2,D:0}` — nowe klatki są config NULL/kalibracją."""
    con, ids = s8_obj
    counts = {r["id"]: r["frame_count"] for r in queries.active_telescopes(con)}
    assert counts == {ids["A"]: 2, ids["B"]: 3, ids["C"]: 2, ids["D"]: 0}
