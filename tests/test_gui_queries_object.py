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
    i `unknown`, więc do partycji się NIE nadaje.

    `nameless_raw_cleared_count` jest tu od S3 i to NIE jest kosmetyka: rozszczepienie kubełka RAW
    po źródle dołożyło liczbę ROZŁĄCZNĄ z `nameless_raw_count` (drążenia są dwa), a ten helper
    jest JEDYNYM walidatorem partycji w repo. Bez tego członu kubełek istniał, klatki w nim
    siedziały, a wszystkie falsyfikatory świeciły zielono — dokładnie ta klasa, którą kolejka
    trzyma jako lekcję („bramka, której nazwa zapowiada człon, a asercja pinuje jego BRAK").
    `object_review` własnego członu NIE dostaje: jego rozszczepienie siedzi w `GROUP BY`, więc
    suma po wierszach liczy obie połówki.

    OD R-S3-1 SĄ TU KOMPLETNE CZTERY KUBEŁKI, po dwa człony na te trzy, których licznik jest
    długością drążenia. Dług był dokładnie tej samej klasy co przy RAW-ie i został znaleziony tą
    samą drogą: człon istniał w nazwie kubełka, nie istniał w równaniu — więc cofnięty light
    archiwum i cofnięty stos wypadały z LEWEJ strony, zostając w prawej (`review_frame_ids` pyta
    o sam brak obiektu). Równanie domykało się tylko dopóki żaden taki nagrobek nie istniał."""
    q = queries.review_queue(con)
    # DWIE KLASY UCIECZKI, obie po prawej stronie równania (`review_frame_ids` niesie oba
    # guardy): klatka ZASTĄPIONA i WYCOFANA nie są robotą. Bez nich jedyny walidator partycji
    # w repo jest ślepy dokładnie tam, gdzie równanie się rozjeżdża (bramka pakietu, Fable Z1).
    headerless_lights = con.execute(
        "SELECT count(*) FROM frame f WHERE f.kind IN ('light','master_light') "
        "AND f.object_id IS NULL "
        "AND f.superseded_by IS NULL AND f.retired_at IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)").fetchone()[0]
    return (sum(r["n"] for r in q["object_review"])
            + q["nameless_count"] + q["nameless_cleared_count"]
            + q["nameless_raw_count"] + q["nameless_raw_cleared_count"]
            + q["nameless_stacks_count"] + q["nameless_stacks_cleared_count"]
            + headerless_lights)


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


def test_partycja_przezywa_NAGROBEK_na_klatce_raw(s8_obj):
    """FALSYFIKATOR ROZSZCZEPIENIA PO ŹRÓDLE (S3) — brakujący bliźniak testu wyżej.

    Cofnięcie NIE wyprowadza klatki z perspektywy gridu (`object_id` wraca na NULL), ale
    wyprowadza ją z `nameless_raw_count` do drugiej, ROZŁĄCZNEJ liczby. Dopóki `_partycja`
    nie sumowała obu, kubełek istniał, klatka w nim siedziała, a równanie cicho gubiło ją
    z lewej strony — bez ani jednej czerwonej bramki.

    Falsyfikator: wytnij `nameless_raw_cleared_count` z `_partycja` → ten test czerwienieje o 1."""
    con, _ = s8_obj
    baza = len(queries.review_frame_ids(con))
    fid = _nameless_light(con, "sha-part-raw-cleared", filetype="raw")
    repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                            kind="deep_sky", frame_ids=[fid], now=NOW)
    assert repo.clear_object_assignment(con, frame_ids=[fid], now=NOW).assigned == 1

    q = queries.review_queue(con)
    assert (q["nameless_raw_count"], q["nameless_raw_cleared_count"]) == (0, 1)
    assert len(queries.review_frame_ids(con)) == baza + 1      # nagrobek ZOSTAJE do przeglądu
    assert _partycja(con) == baza + 1                          # …i partycja go widzi


def test_kotwica_kubelka_RAW_liczy_OBIE_polowki(s8_obj):
    """Bramka 13 po rozszczepieniu: kotwicą rdzenia jest SUMA obu drążeń, nie samo pierwsze.

    Do S3 równość brzmiała `len(nameless_raw_frames()) == nameless_raw_lights`, a rozszczepienie
    ją unieważniło: `nameless_raw_lights` pyta o sam brak obiektu (nagrobki liczy), a drążenie
    domyślne bierze wyłącznie połówkę nietkniętą. Stary pin przechodził tylko dopóki żaden
    nagrobek nie istniał — czyli pinował nieobecność populacji, nie równość."""
    from horreum.resolver import nameless_raw_lights

    con, _ = s8_obj
    swiezy = _nameless_light(con, "sha-anchor-raw-fresh", filetype="raw")
    cofniety = _nameless_light(con, "sha-anchor-raw-cleared", filetype="raw")
    repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                            kind="deep_sky", frame_ids=[cofniety], now=NOW)
    repo.clear_object_assignment(con, frame_ids=[cofniety], now=NOW)

    q = queries.review_queue(con)
    a, b = q["nameless_raw_count"], q["nameless_raw_cleared_count"]
    assert (a, b) == (1, 1)
    assert a + b == len(queries.nameless_raw_frames(con)) + len(
        queries.nameless_raw_frames(con, cleared=True)) == nameless_raw_lights(con) == 2
    # …i połówki są ROZŁĄCZNE, a nie kubełek i jego podzbiór
    assert {r["frame_id"] for r in queries.nameless_raw_frames(con)} == {swiezy}
    assert {r["frame_id"] for r in queries.nameless_raw_frames(con, cleared=True)} == {cofniety}


# --- I-2b/D-P-I-5: gotowy stack jako TRZECI kubełek bezimiennych ---

def _nameless_stack(con, sha):
    """Gotowy obraz po integracji BEZ karty `OBJECT` — klasa 22 plików realnego drzewa obróbki."""
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="master_light", filetype="xisf",
                               camera_id=None, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=None, now=NOW)
    return fid


def test_nameless_stos_drazy_wlasnym_kubelkiem_rozlacznie_z_lightami(s8_obj):
    """D-P-I-5 + D-0802-1: `master_light` liczy się OSOBNO od lightów archiwum — ale od 2026-08-02
    NIE dlatego, że nie ma drogi naprawy (ma tę samą: karta `OBJECT` do pliku, P6d), tylko dlatego,
    że to osobna POPULACJA i osobny licznik partycji.

    Dwa drążenia muszą zostać ROZŁĄCZNE: gdyby `nameless_frames` zaczęło podawać stacki, partycja
    `review_queue` policzyłaby je dwa razy i domykałaby się tylko przypadkiem."""
    from horreum.resolver import nameless_lights, nameless_stacks

    con, _ = s8_obj
    _nameless_light(con, "sha-nl-light")
    _nameless_stack(con, "sha-nl-stack")
    q = queries.review_queue(con)
    assert q["nameless_count"] == nameless_lights(con) == 1            # tylko light archiwum
    assert q["nameless_stacks_count"] == nameless_stacks(con) == 1     # stos własnym kubełkiem
    light_id = con.execute("SELECT id FROM frame WHERE sha1_data='sha-nl-light'").fetchone()[0]
    stos_id = con.execute("SELECT id FROM frame WHERE sha1_data='sha-nl-stack'").fetchone()[0]
    assert [r["frame_id"] for r in queries.nameless_frames(con)] == [light_id]
    assert [r["frame_id"] for r in queries.nameless_stack_frames(con)] == [stos_id]


def test_licznik_stosow_jest_dlugoscia_drazenia(s8_obj):
    """D-PD-10 dla trzeciego kubełka: licznik w kolejce to DŁUGOŚĆ read-modelu, którym kubełek
    się otwiera — nie osobny COUNT. Dwa literały rozjechałyby się przy pierwszej zmianie kształtu
    i wiersz pokazywałby inną liczbę niż lista, którą pod nim widać.

    Rdzeniowy `resolver.nameless_stacks` zostaje osobnym literałem (warstwy są dwie, zależność
    idzie w jedną stronę) — dlatego jego równość z drążeniem pinujemy tutaj."""
    from horreum.resolver import nameless_stacks

    con, _ = s8_obj
    for i in range(3):
        _nameless_stack(con, f"sha-cnt-stack-{i}")
    n = queries.review_queue(con)["nameless_stacks_count"]
    assert n == len(queries.nameless_stack_frames(con)) == nameless_stacks(con) == 3


def test_partycja_przezywa_gotowy_stos(s8_obj):
    """FALSYFIKATOR trzeciego rozdziału (bliźniak testu RAW): stack bez obiektu ZOSTAJE
    w `review_frame_ids` (predykat pyta o sam brak obiektu, a `master_light` jest kind-em osi),
    więc wycięcie go z `nameless_count` bez własnego kubełka rozspójnia partycję o jego liczbę."""
    con, _ = s8_obj
    baza = len(queries.review_frame_ids(con))
    _nameless_stack(con, "sha-part-stack")
    assert len(queries.review_frame_ids(con)) == baza + 1
    assert _partycja(con) == baza + 1


def _cofnij(con, fid):
    """Pełny gest ręki: nazwij klatkę, a potem ZDEJMIJ nazwę — zostaje nagrobek `user_cleared`
    przy `object_id IS NULL`. Ta para to jedyna droga, którą nagrobek powstaje."""
    repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                            kind="deep_sky", frame_ids=[fid], now=NOW)
    assert repo.clear_object_assignment(con, frame_ids=[fid], now=NOW).assigned == 1
    return fid


def test_partycja_przezywa_NAGROBEK_na_light_archiwum(s8_obj):
    """R-S3-1, FALSYFIKATOR CZWARTEGO ROZSZCZEPIENIA — bliźniak testu RAW-owego wyżej, którego
    do dziś brakowało.

    Light archiwum bez `object_raw` może mieć nagrobek: nazwę dostał z REGIONU (współrzędne),
    ścieżki albo xref-a, nie z karty — więc po cofnięciu wraca do kubełka bezimiennych, choć
    nagłówek nigdy o obiekcie nie mówił. Do R-S3-1 wracał tam nieodróżnialny od klatki, o której
    nikt nigdy nie decydował.

    Falsyfikator: wytnij `nameless_cleared_count` z `_partycja` → ten test czerwienieje o 1."""
    con, _ = s8_obj
    baza = len(queries.review_frame_ids(con))
    _cofnij(con, _nameless_light(con, "sha-part-fits-cleared"))

    q = queries.review_queue(con)
    assert (q["nameless_count"], q["nameless_cleared_count"]) == (0, 1)
    assert len(queries.review_frame_ids(con)) == baza + 1      # nagrobek ZOSTAJE do przeglądu
    assert _partycja(con) == baza + 1                          # …i partycja go widzi


def test_partycja_przezywa_NAGROBEK_na_gotowym_stosie(s8_obj):
    """R-S3-1 + D-OW-7: ta droga NIE jest hipotetyczna — gest osi obiektu sięga gotowego obrazu,
    więc cofnięcie na stosie jest jednym kliknięciem. Bez własnego członu równanie gubiło stos
    z werdyktem ręki dokładnie tak, jak gubiło cofniętego lighta.

    Falsyfikator: wytnij `nameless_stacks_cleared_count` z `_partycja` → czerwienieje o 1."""
    con, _ = s8_obj
    baza = len(queries.review_frame_ids(con))
    _cofnij(con, _nameless_stack(con, "sha-part-stack-cleared"))

    q = queries.review_queue(con)
    assert (q["nameless_stacks_count"], q["nameless_stacks_cleared_count"]) == (0, 1)
    assert len(queries.review_frame_ids(con)) == baza + 1
    assert _partycja(con) == baza + 1


def test_kotwice_RDZENIA_licza_OBIE_polowki_lightow_i_stosow(s8_obj):
    """Bramka 13 rozciągnięta na dwa kubełki, które rozszczepienia nie miały (R-S3-1).

    Kotwicą rdzenia jest SUMA obu drążeń, nie samo pierwsze: `nameless_lights`/`nameless_stacks`
    pytają o sam brak obiektu i nagrobki LICZĄ, a drążenie domyślne bierze wyłącznie połówkę
    nietkniętą. Gdyby zapisać starą równość, pin przechodziłby tylko dopóki żaden nagrobek nie
    istnieje — czyli pinowałby NIEOBECNOŚĆ populacji zamiast równości (ta sama pułapka, która
    przy RAW-ie przeżyła całe S3)."""
    from horreum.resolver import nameless_lights, nameless_stacks

    con, _ = s8_obj
    swiezy_l = _nameless_light(con, "sha-anchor-fits-fresh")
    cofniety_l = _cofnij(con, _nameless_light(con, "sha-anchor-fits-cleared"))
    swiezy_s = _nameless_stack(con, "sha-anchor-stack-fresh")
    cofniety_s = _cofnij(con, _nameless_stack(con, "sha-anchor-stack-cleared"))

    q = queries.review_queue(con)
    assert (q["nameless_count"], q["nameless_cleared_count"]) == (1, 1)
    assert (q["nameless_stacks_count"], q["nameless_stacks_cleared_count"]) == (1, 1)
    assert len(queries.nameless_frames(con)) + len(
        queries.nameless_frames(con, cleared=True)) == nameless_lights(con) == 2
    assert len(queries.nameless_stack_frames(con)) + len(
        queries.nameless_stack_frames(con, cleared=True)) == nameless_stacks(con) == 2
    # …i połówki są ROZŁĄCZNE, a nie kubełek i jego podzbiór
    assert {r["frame_id"] for r in queries.nameless_frames(con)} == {swiezy_l}
    assert {r["frame_id"] for r in queries.nameless_frames(con, cleared=True)} == {cofniety_l}
    assert {r["frame_id"] for r in queries.nameless_stack_frames(con)} == {swiezy_s}
    assert {r["frame_id"] for r in queries.nameless_stack_frames(con, cleared=True)} == {cofniety_s}


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


# --- R-S3-2: obie połówki nazwy stoją OBOK SIEBIE ---

def _light_z_nazwa(con, sha, object_raw):
    """Light z zeznaniem, którego drabina nie rozwiąże — surowiec obu połówek `object_review`."""
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=object_raw, now=NOW)
    return fid


def test_polowki_tej_samej_nazwy_stoja_obok_siebie(s8_obj):
    """R-S3-2: kolejność prowadzi NAZWĄ (sumą obu połówek), nie pojedynczą połówką.

    Odtworzony rozjazd zmierzony na żywej bazie: `ORDER BY n DESC` wpuszczał między połówki
    obcy kubełek (`LDN 1174 · 9` → `IC 1805 · 7` → `LDN 1174 · 5 · cofnięte ręką`), więc user
    „załatwiał" pierwszą połówkę i zostawiał drugą, nie wiedząc, że istnieje.

    Falsyfikator: przywróć `ORDER BY n DESC, object_raw, cleared` → nazwy przeplatają się
    i asercja o sąsiedztwie czerwienieje."""
    con, _ = s8_obj
    for i in range(5):                                    # „LDN 1174" nietknięte ×5
        _light_z_nazwa(con, f"sha-ldn-{i}", "LDN 1174")
    for i in range(4):                                    # „IC 1805" nietknięte ×4
        _light_z_nazwa(con, f"sha-ic-{i}", "IC 1805")
    cofniete = [_light_z_nazwa(con, f"sha-ldn-c-{i}", "LDN 1174") for i in range(2)]
    for fid in cofniete:                                  # …i ×2 z NAGROBKIEM (druga połówka)
        repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                                kind="deep_sky", frame_ids=[fid], now=NOW)
    assert repo.clear_object_assignment(con, frame_ids=cofniete, now=NOW).assigned == 2

    wiersze = [(r["object_raw"], r["cleared"], r["n"])
               for r in queries.review_queue(con)["object_review"]]
    # Suma „LDN 1174" = 7 bije „IC 1805" = 4, a POŁÓWKA cofnięta (2) NIE spada pod „IC 1805",
    # choć jest od niego DWUKROTNIE mniej liczna — o pozycji decyduje nazwa, nie połówka.
    # Dokładnie to psuł stary klucz: przy `n DESC` wiersz cofniętych spadał na sam dół.
    assert wiersze[:3] == [("LDN 1174", 0, 5), ("LDN 1174", 1, 2), ("IC 1805", 0, 4)]
    # …i to samo powiedziane wprost: każda nazwa zajmuje SPÓJNY blok wierszy.
    nazwy = [w[0] for w in wiersze]
    for nazwa in set(nazwy):
        pozycje = [i for i, n in enumerate(nazwy) if n == nazwa]
        assert pozycje == list(range(pozycje[0], pozycje[0] + len(pozycje)))


# --- R-S2b-12: „ostatnio użyte" wyprowadzone z DZIENNIKA ---

def test_ostatnio_uzyte_to_gesty_RĘKI_najswiezsze_pierwsze(s8_obj):
    """R-S2b-12: skrót podaje kanony, które CZŁOWIEK realnie wskazał — nie to, co zrobił automat.

    Kolejność jest odwrotna do zapisu (najświeższe na górze), a powtórzenie tego samego kanonu
    NIE dubluje pozycji: `GROUP BY` po obiekcie czyni listę idempotentną wobec liczby zdarzeń
    (ta sama pułapka, którą `count(event)` zastawił na kubełkach — memory `review-queue-from-state`).

    Falsyfikator: zdejmij filtr `object_source='user'` → w wyniku pojawia się kanon nadany
    ścieżką, którego ręka nigdy nie wskazała."""
    con, ids = s8_obj
    a = _light_z_nazwa(con, "sha-recent-a", "RAW-A")
    b = _light_z_nazwa(con, "sha-recent-b", "RAW-B")
    c = _light_z_nazwa(con, "sha-recent-c", "RAW-C")
    repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                            kind="deep_sky", frame_ids=[a], now=NOW)
    repo.user_assign_object(con, alias_norm=None, canon="IC1805", catalog="IC",
                            kind="deep_sky", frame_ids=[b], now=NOW)
    repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                            kind="deep_sky", frame_ids=[c], now=NOW)   # ten sam kanon PONOWNIE

    kanony = [r["canon"] for r in queries.recent_hand_objects(con)]
    assert kanony[:2] == ["NGC7000", "IC1805"]          # najświeższy pierwszy, bez duplikatu
    assert kanony.count("NGC7000") == 1

    # ŚCIEŻKA to nie gest palcem — potwierdzona propozycja nie wchodzi do „ostatnio użytych".
    d = _light_z_nazwa(con, "sha-recent-d", "RAW-D")
    repo.user_assign_object(con, alias_norm=None, canon="M42", catalog="Messier",
                            kind="deep_sky", frame_ids=[d], now=NOW, object_source="path")
    assert "M42" not in [r["canon"] for r in queries.recent_hand_objects(con)]


def test_ostatnio_uzyte_niesie_pola_wymagane_przez_klinge(s8_obj):
    """Skrót woła `user_assign_object`, która INSERTuje obiekt przy nowym kanonie — sam string
    zostawiłby zapis bez `catalog`/`kind`."""
    con, ids = s8_obj
    fid = _light_z_nazwa(con, "sha-recent-pola", "RAW-P")
    repo.user_assign_object(con, alias_norm=None, canon="IC1805", catalog="IC",
                            kind="deep_sky", frame_ids=[fid], now=NOW)
    wiersz = queries.recent_hand_objects(con)[0]
    assert (wiersz["canon"], wiersz["catalog"], wiersz["kind"]) == ("IC1805", "IC", "deep_sky")


def test_ostatnio_uzyte_respektuje_limit(s8_obj):
    con, ids = s8_obj
    for i, canon in enumerate(("NGC7000", "IC1805", "M42")):
        fid = _light_z_nazwa(con, f"sha-recent-lim-{i}", f"RAW-L{i}")
        repo.user_assign_object(con, alias_norm=None, canon=canon, catalog="NGC",
                                kind="deep_sky", frame_ids=[fid], now=NOW)
    assert len(queries.recent_hand_objects(con, limit=2)) == 2


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


# --- R-S3-4: POLITYKA KOLUMNY „Obiekt" (Qt-wolna, więc dom ma tutaj) ---

def test_object_cell_ODROZNIA_kanon_od_zeznania():
    """Kolumna niosła jeden napis dla DWÓCH różnych twierdzeń: „ten obiekt tak się nazywa" (kanon
    osi) i „tyle mówi nagłówek pliku" (surowe zeznanie). Po geście „Cofnij przypisanie" wiersz dalej
    pokazywał `NGC7023`, a facet Obiekt na tym samym ekranie był już pusty.

    Populacja NIE jest hipotetyczna: zmierzone na żywym archiwum **2364 klatki KALIBRACYJNE**
    niosą w nagłówku `FlatWizard`/`DARK`/`Target`, a kolumna twierdziła o nich, że to ich obiekt —
    choć kalibracja obiektu nie ma z DEFINICJI."""
    assert queries.object_cell({"object_canon": "NGC 7023", "object_raw": "ngc7023",
                                "kind": "light"}) == ("NGC 7023", "canon")
    assert queries.object_cell({"object_canon": None, "object_raw": "FlatWizard",
                                "kind": "flat"}) == ("FlatWizard", "kind")
    assert queries.object_cell({"object_canon": None, "object_raw": "Jakas Mgla",
                                "kind": "light"}) == ("Jakas Mgla", "raw")


def test_object_cell_NAGROBEK_bije_rodzaj_i_NIGDY_nie_jest_pustka():
    """DWIE rzeczy naraz, bo obie dałyby się zepsuć osobno.

    PIERWSZEŃSTWO: klatka cofnięta ręką ma dostać zdanie O COFNIĘCIU, także gdy jest gotowym
    obrazem albo kalibracją — to jej NAJŚWIEŻSZY fakt i to on tłumaczy, dlaczego facet obok jest
    pusty. Kolejność `if`-ów w `object_cell` JEST tą regułą.

    ZNACZNIK: zmierzone **845 klatek nieba bez `object_raw`** (w tym 757 RAW-ów z lustrzanki,
    które nie mają go gdzie nieść). Ich komórka jest PUSTA, a kursywa i szarość na pustym stringu
    są niewidzialne — bez `↺` dług zostałby otwarty dla większości własnej przyszłej populacji.

    Falsyfikator: przenieś gałąź `user_cleared` pod gałąź rodzaju → nagrobek na flacie zacznie
    twierdzić „kalibracja obiektu nie ma", gubiąc jedyną informację o geście człowieka."""
    tekst, stan = queries.object_cell({"object_canon": None, "object_raw": None,
                                       "object_source": "user_cleared", "kind": "light"})
    assert stan == "cleared" and tekst == queries.CLEARED_MARK, "pusta komórka = stan niewidzialny"

    tekst, stan = queries.object_cell({"object_canon": None, "object_raw": "NGC7023",
                                       "object_source": "user_cleared", "kind": "master_light",
                                       "path": r"R:\A\LMC\master\m.xisf"})
    assert (tekst, stan) == (f"{queries.CLEARED_MARK} NGC7023", "cleared"), "nagrobek bije podpowiedź"

    _, stan = queries.object_cell({"object_canon": None, "object_raw": "FlatWizard",
                                   "object_source": "user_cleared", "kind": "flat"})
    assert stan == "cleared", "nagrobek bije rodzaj"


def test_object_cell_PODPOWIEDZ_z_folderu_dla_bezimiennego_stosu():
    """FIRSTHAND ZDZINIA 0808: „nie widzę napisu LMC ani IC443". I nie mógł — nazwy plików generuje
    WBPP, więc sześć stosów LMC i jeden IC443 czytają się identycznie. Tożsamość siedzi WYŁĄCZNIE
    w folderze, a folder ma być DZIADKIEM (rodzic to `master` u wszystkich, więc nie rozróżnia nic).

    Podpowiedź NIE UDAJE NAZWY (nawiasy kątowe) i ma WŁASNY stan, bo mówi co innego niż kanon."""
    stos = {"kind": "master_light", "object_canon": None, "object_raw": None,
            "path": r"R:\!!ASTROFOTO\OBIEKTY_DNG\A7R3_105_LMC\master\masterLight_BIN-1.xisf"}
    assert queries.object_cell(stos) == ("⟨A7R3_105_LMC⟩", "hint")
    assert queries.object_cell(dict(stos, object_canon="LMC")) == ("LMC", "canon")

    light = {"kind": "light", "object_canon": None, "object_raw": None,
             "path": r"R:\ASTRO_\LIGHTS\IC443\portable\20190110_DSC5559.dng"}
    assert queries.object_cell(light) == ("", "canon"), "light ma własną drogę (szczebel S2)"
    # Kolumny `kind`/`path`/`object_source` nie wchodzą z KAŻDEGO zapytania gridu — brak nie ma
    # prawa wywalić renderu (dlatego `_derive` podaje słownik, nie surowy `sqlite3.Row`).
    assert queries.object_cell({"object_canon": None, "object_raw": None}) == ("", "canon")


def test_wiersz_NIEMY_o_rodzaju_NIE_dostaje_zdania_o_rodzaju():
    """Gałąź `kind` twierdzi „kalibracja obiektu nie ma z DEFINICJI" — wolno ją postawić WYŁĄCZNIE
    przy rodzaju ZNANYM (bramka pakietu 0810, zarzut zgodny u dwóch soczewek).

    Falsyfikator: wróć do `row.get("kind") not in LIGHT_KINDS` → wiersz bez klucza `kind` (`None`)
    dostaje stan `kind`, czyli tooltip o kalibracji nad klatką, o której nic nie wiadomo."""
    assert queries.object_cell({"object_canon": None, "object_raw": "NGC7023"}) == \
        ("NGC7023", "raw"), "bez `kind` fallbackiem jest `raw` — nie twierdzi nic o rodzaju"
    assert queries.object_cell(
        {"object_canon": None, "object_raw": "FlatWizard", "kind": "flat"})[1] == "kind"
    assert queries.object_cell(
        {"object_canon": None, "object_raw": "NGC7023", "kind": "light"})[1] == "raw"


def test_stany_komorki_MAJA_LUSTRO_w_stalej():
    """`OBJECT_CELL_STATES` jest lustrem gałęzi `object_cell` — z niego jedzie bramka parytetu
    z katalogiem i18n (klucz składany w locie jest dla kolektora literałów NIEWIDZIALNY)."""
    assert set(queries.OBJECT_CELL_STATES) == {"canon", "cleared", "kind", "raw", "hint"}


# --- R-S2b-3: GRUPY DO PRZYWRÓCENIA (ze STANU, nie z dziennika) ---

def test_restore_targets_grupuje_po_OBIEKCIE_i_liczy_nagrobki_bez_pamieci(s8_obj):
    """Klinga osi przyjmuje JEDEN kanon na wywołanie, a masowe cofnięcie obejmuje bywa klatki kilku
    obiektów — read-model musi więc oddać grupy, nie płaską listę.

    Nagrobek BEZ pamięci (baza-dawca sprzed migracji 0017) nie wpada do żadnej grupy i liczy się
    osobno: gest powie o nim wprost, zamiast po cichu pominąć."""
    con, ids = s8_obj
    a = _cofnij(con, _nameless_light(con, "sha-rt-a"))
    b = _cofnij(con, _nameless_light(con, "sha-rt-b"))
    sierota = _cofnij(con, _nameless_light(con, "sha-rt-c"))
    con.execute("UPDATE frame SET object_cleared_id = NULL WHERE id = ?", (sierota,))
    con.commit()

    grupy, bez_pamieci = queries.restore_targets(con, [a, b, sierota])
    assert bez_pamieci == 1
    assert [(g["canon"], sorted(g["frame_ids"])) for g in grupy] == [("NGC7000", sorted([a, b]))]

    # Klatka BEZ nagrobka nie jest celem tego gestu, choćby stała w zaznaczeniu.
    zwykla = _nameless_light(con, "sha-rt-d")
    assert queries.restore_targets(con, [zwykla]) == ([], 0)


def test_selection_object_state_LICZY_restorable_bez_nowego_zapytania(s8_obj):
    """Bramka trzeciej pozycji menu jedzie TĄ SAMĄ pętlą, co dwie pierwsze — read-model osi chodzi
    przy KAŻDEJ zmianie zaznaczenia, a osobne zapytanie byłoby powrotem do defektu zamkniętego
    w P-K (`Ctrl+A` na 16 tys. klatek).

    `restorable` liczy WYŁĄCZNIE nagrobki Z PAMIĘCIĄ: aktywna pozycja bez czego przywracać
    obiecywałaby robotę, której nie ma."""
    con, ids = s8_obj
    fid = _cofnij(con, _nameless_light(con, "sha-rs-a"))
    stan = queries.selection_object_state(con, [fid])
    assert (stan["restorable"], stan["clearable"]) == (1, 0)

    con.execute("UPDATE frame SET object_cleared_id = NULL WHERE id = ?", (fid,))
    con.commit()
    assert queries.selection_object_state(con, [fid])["restorable"] == 0
