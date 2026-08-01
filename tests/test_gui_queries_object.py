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


# --- T5a: szew „do przeglądu" — kolejka vs perspektywa gridu ---

def _nameless_light(con, sha, filetype="fits"):
    """Light z NAGŁÓWKIEM, ale bez `object_raw` i bez obiektu — klasa 25 klatek żywej pf4.
    `filetype='raw'` daje bliźniaka po drugiej stronie FORMATU (DSLR — EXIF nie zna `OBJECT`)."""
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="light", filetype=filetype,
                               camera_id=None, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=None, now=NOW)
    return fid


def test_review_queue_kubelek_bezimiennych(s8_obj):
    """T5a: klatka bez `object_raw` NIE ma jak trafić do `object_review` (GROUP BY po nazwie) —
    liczy ją własny kubełek. Bez niego kolejka milczała o tym, co grid pokazuje."""
    con, ids = s8_obj
    assert queries.review_queue(con)["nameless_count"] == 0        # fixture: same nazwane
    _nameless_light(con, "sha-nameless1")
    q = queries.review_queue(con)
    assert q["nameless_count"] == 1
    # nie przecieka do kubełka nazwanych ani do headerless (nagłówek JEST)
    assert [(r["object_raw"], r["n"]) for r in q["object_review"]] == [("FlatWizard", 2)]
    assert q["headerless_count"] == 1                              # nadal sam nullcfg


def _partycja(con):
    """Suma kubełków kolejki, która MUSI równać się `|review_frame_ids|`. JEDEN dom (nie kopia
    per test): każdy nowy kubełek dopisujesz TU i wszystkie falsyfikatory od razu go pilnują —
    inaczej trzeci kubełek wchodzi do jednej kopii, a druga cicho zostaje przy dwóch.
    Ostatni człon jest kind-scopowany: globalny `headerless_count` liczy też kalibrację
    i `unknown`, więc do partycji się NIE nadaje."""
    q = queries.review_queue(con)
    headerless_lights = con.execute(
        "SELECT count(*) FROM frame f WHERE f.kind IN ('light','master_light') "
        "AND f.object_id IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)").fetchone()[0]
    return (sum(r["n"] for r in q["object_review"]) + q["nameless_count"]
            + q["nameless_raw_count"] + q["nameless_stacks_count"] + headerless_lights)


def test_review_queue_partycja_pokrywa_perspektywe_gridu(s8_obj):
    """Szew z kolejki (rozjazd `queries.py:215` vs `:477`): kubełki kolejki MUSZĄ sumować się do
    zbioru, który grid pokazuje w perspektywie „Do przeglądu"."""
    con, ids = s8_obj
    # stan wyjściowy: objrev1+objrev2 (nazwane) + nullcfg (light bez nagłówka) = 3
    assert len(queries.review_frame_ids(con)) == 3
    assert _partycja(con) == 3
    _nameless_light(con, "sha-nameless1")
    _nameless_light(con, "sha-nameless2")
    assert len(queries.review_frame_ids(con)) == 5
    assert _partycja(con) == 5
    # rozwiązanie klatki opuszcza OBIE strony równania
    repo.assign_object(con, frame_id=ids["frames"]["objrev1"],
                       object_id=ids["objects"]["NGC7000"], object_source="user", now=NOW)
    assert _partycja(con) == len(queries.review_frame_ids(con)) == 4


# --- P-D: drążenie kubełka bezimiennych (D-PD-11) ---

def test_nameless_frames_jeden_wiersz_na_klatke_i_cel_present(s8_obj):
    """Kształt read-modelu: DOKŁADNIE jeden wiersz na klatkę mimo N lokacji, a cel to kopia
    OBECNA — nie `MIN(id)` po wszystkich. Klatka z 2 obecnymi kopiami ma `n_present=2` i zostaje
    JEDNYM wierszem (naiwny LEFT JOIN po `present=1` zawyżyłby licznik)."""
    con, ids = s8_obj
    fid = _nameless_light(con, "sha-nameless-loc")
    repo.add_location(con, frame_id=fid, volume="v1", path="/a/one.fits", now=NOW)
    rows = [r for r in queries.nameless_frames(con) if r["frame_id"] == fid]
    assert len(rows) == 1 and rows[0]["n_present"] == 1 and rows[0]["path"] == "/a/one.fits"

    lid2, _ = repo.add_location(con, frame_id=fid, volume="v2", path="/b/two.fits", now=NOW)
    rows = [r for r in queries.nameless_frames(con) if r["frame_id"] == fid]
    assert len(rows) == 1 and rows[0]["n_present"] == 2
    assert rows[0]["path"] == "/a/one.fits"                 # MIN(id) WŚRÓD OBECNYCH

    # pierwsza kopia znika → celem staje się DRUGA (a nie martwa ścieżka z MIN(id) bez `present`)
    lid1 = con.execute("SELECT id FROM location WHERE path = '/a/one.fits'").fetchone()[0]
    repo.mark_location_vanished(con, location_id=lid1, expected_path="/a/one.fits",
                                root="/a", run_id="r-pd", now=NOW)
    rows = [r for r in queries.nameless_frames(con) if r["frame_id"] == fid]
    assert len(rows) == 1 and rows[0]["n_present"] == 1 and rows[0]["location_id"] == lid2


def test_nameless_frames_klatka_bez_lokacji_zostaje_w_wyniku(s8_obj):
    """Predykat populacji NIE zależy od lokacji (D-PD-11): klatka bez obecnej kopii ZOSTAJE
    w wyniku z `n_present=0` i pustym celem — dialog pokaże ją jako pominiętą Z POWODEM. Naiwny
    `JOIN location … present=1` wyrzuciłby ją z licznika, choć zostaje w perspektywie gridu."""
    con, ids = s8_obj
    fid = _nameless_light(con, "sha-nameless-noloc")
    row = next(r for r in queries.nameless_frames(con) if r["frame_id"] == fid)
    assert row["n_present"] == 0 and row["location_id"] is None and row["path"] is None
    assert fid in queries.review_frame_ids(con)


def test_nameless_count_jest_dlugoscia_read_modelu(s8_obj):
    """D-PD-10 — JEDEN właściciel predykatu na TRZECH powierzchniach: kubełek kolejki, drążenie
    do klatek i raport dostawy (`resolver.nameless_lights`, literał rdzenia) muszą dawać tę samą
    liczbę. Rozjazd znaczyłby, że kubełek otwiera listę innej długości, niż zapowiada."""
    from horreum.resolver import nameless_lights

    con, ids = s8_obj
    for sha in ("sha-nl-1", "sha-nl-2", "sha-nl-3"):
        _nameless_light(con, sha)
    n = queries.review_queue(con)["nameless_count"]
    assert n == len(queries.nameless_frames(con)) == nameless_lights(con) == 3
    # rozwiązany obiekt wyprowadza klatkę z kubełka WSZĘDZIE naraz (tu skrótem — na żywo robi to
    # takt 3: karta w pliku → re-sync zeznania → `resolve`)
    fid = con.execute("SELECT id FROM frame WHERE sha1_data = 'sha-nl-1'").fetchone()[0]
    repo.assign_object(con, frame_id=fid, object_id=ids["objects"]["NGC7000"],
                       object_source="header", now=NOW)
    assert (queries.review_queue(con)["nameless_count"] == len(queries.nameless_frames(con))
            == nameless_lights(con) == 2)


def test_nameless_swiadomy_formatu_raw_ma_wlasny_kubelek(s8_obj):
    """RAW nie ma JAK zeznać o obiekcie (EXIF nie zna `OBJECT`), więc nie jest „do naprawienia
    kartą" — a `nameless_frames` to WEJŚCIE dialogu zapisu. Bez tego rozdziału okno „Napraw
    nagłówek…" otwierałoby się z listą, której każda pozycja i tak jest pominięta przez
    `macro.resolve_target` (RAW = read-only)."""
    from horreum.resolver import nameless_lights, nameless_raw_lights

    con, _ = s8_obj
    _nameless_light(con, "sha-nl-fits")
    _nameless_light(con, "sha-nl-raw", filetype="raw")
    q = queries.review_queue(con)
    assert q["nameless_count"] == nameless_lights(con) == 1          # tylko FITS
    assert q["nameless_raw_count"] == nameless_raw_lights(con) == 1  # RAW własnym kubełkiem
    # drążenie (wejście dialogu) NIE podaje RAW-a
    assert [r["frame_id"] for r in queries.nameless_frames(con)] == [
        con.execute("SELECT id FROM frame WHERE sha1_data='sha-nl-fits'").fetchone()[0]]


def test_partycja_przezywa_klatke_raw(s8_obj):
    """FALSYFIKATOR rozdziału: RAW zostaje w perspektywie gridu „Do przeglądu" (`object_id IS
    NULL`), więc samo wycięcie go z `nameless_count` rozspójniłoby partycję dokładnie o jego
    liczbę. Ten test pęka, gdy ktoś skasuje kubełek RAW zamiast go policzyć."""
    con, _ = s8_obj
    baza = len(queries.review_frame_ids(con))
    _nameless_light(con, "sha-part-raw", filetype="raw")
    assert len(queries.review_frame_ids(con)) == baza + 1     # RAW JEST w perspektywie gridu
    assert _partycja(con) == baza + 1                         # …i partycja go widzi


# --- I-2b/D-P-I-5: gotowy stack jako TRZECI kubełek bezimiennych ---

def _nameless_stack(con, sha):
    """Gotowy obraz po integracji BEZ karty `OBJECT` — klasa 22 plików realnego drzewa obróbki."""
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="master_light", filetype="xisf",
                               camera_id=None, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=None, now=NOW)
    return fid


def test_nameless_stos_ma_wlasny_kubelek_i_nie_wchodzi_do_dialogu(s8_obj):
    """D-P-I-5: `master_light` liczy się OSOBNO od lightów archiwum, bo droga naprawy jest trzecia
    — żadna. Drzewo obróbki trzymamy read-only (§5 briefu P-I), więc stack nie ma prawa pojawić
    się w `nameless_frames` (wejście dialogu „Napraw nagłówek…"), który obiecuje zapis karty."""
    from horreum.resolver import nameless_lights, nameless_stacks

    con, _ = s8_obj
    _nameless_light(con, "sha-nl-light")
    _nameless_stack(con, "sha-nl-stack")
    q = queries.review_queue(con)
    assert q["nameless_count"] == nameless_lights(con) == 1            # tylko light archiwum
    assert q["nameless_stacks_count"] == nameless_stacks(con) == 1     # stos własnym kubełkiem
    # drążenie (wejście dialogu zapisu) NIE podaje stacku
    assert [r["frame_id"] for r in queries.nameless_frames(con)] == [
        con.execute("SELECT id FROM frame WHERE sha1_data='sha-nl-light'").fetchone()[0]]


def test_partycja_przezywa_gotowy_stos(s8_obj):
    """FALSYFIKATOR trzeciego rozdziału (bliźniak testu RAW): stack bez obiektu ZOSTAJE
    w `review_frame_ids` (predykat pyta o sam brak obiektu, a `master_light` jest kind-em osi),
    więc wycięcie go z `nameless_count` bez własnego kubełka rozspójnia partycję o jego liczbę."""
    con, _ = s8_obj
    baza = len(queries.review_frame_ids(con))
    _nameless_stack(con, "sha-part-stack")
    assert len(queries.review_frame_ids(con)) == baza + 1
    assert _partycja(con) == baza + 1


def test_trzy_kubelki_bezimiennych_sa_rozlaczne(s8_obj):
    """Trzy drogi naprawy — trzy kubełki, ZERO zachodzenia. Gdyby predykaty się nakładały,
    partycja domykałaby się tylko przypadkiem: nadmiar w jednym kubełku kompensowałby brak
    w drugim i falsyfikatory wyżej przestałyby cokolwiek pilnować."""
    from horreum.resolver import nameless_lights, nameless_raw_lights, nameless_stacks

    con, _ = s8_obj
    _nameless_light(con, "sha-3-fits")
    _nameless_light(con, "sha-3-raw", filetype="raw")
    _nameless_stack(con, "sha-3-stack")
    assert (nameless_lights(con), nameless_raw_lights(con), nameless_stacks(con)) == (1, 1, 1)


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
