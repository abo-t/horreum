"""Optyka teleskopu (AR-128 `O4`, AR-129 `O5`, decyzje D-1012-1 i D-1012-2).

Teleskop w Horreum to fizyczny teleskop z ogniskową, potwierdzony ręką. Testy pilnują:
  * wartości Z PLIKÓW = moda aktywnych lightów (bez nich - flatów) zestawów korzenia, odświeżanej
    przy każdej Dostawie (dawniej: pierwsza klatka, zapisana raz - A140R f/8.0 przy 7370 × f/5.6);
  * wartości RĘKI (`focal_user`, `f_ratio_user`), która wygrywa przy odczycie, a której automat nie
    dotyka; wspólnych walidatorów obu klingów ręki;
  * braku automatycznego rozdziału teleskopu po ogniskowej FITS/XISF (D-1012-2) i kubełków
    „ogniskowa/f/ niezgodna z teleskopem" (lighty i flaty z zestawem automatu, > 5 %);
  * okna „Dopisz nowy…" jako jednej transakcji z pełną Historią;
  * planera: ogniskowa ręka → pliki → klatka, zestaw po korzeniu scalenia;
  * spisu ręki osi teleskopu po rekordach.
Każdy test nazywa w docstringu mutanta, który go czerwieni (skrypt mutantów toru)."""
import json

import pytest

from horreum import audit, db, grouper, repo, resolver, sky
from horreum.gui import queries

NOW = "2026-10-12T10:00:00+00:00"
LATER = "2026-10-12T11:00:00+00:00"


def _baza():
    return db.open_db(":memory:")


def _kamera(con, model="ASI2600MM", pixel=3.76):
    cid, _ = repo.upsert_camera(con, model_canon=model, pixel_um=pixel, is_mono=1,
                                is_mono_source="header", raw_instrume=model, now=NOW)
    return cid


def _klatka(con, sha, *, telescop, focal=None, f_ratio=None, kind="light", camera_id=None,
            filetype="fits", nx=6248, ny=4176):
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind=kind, filetype=filetype,
                               camera_id=camera_id, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json=json.dumps({"NAXIS1": nx, "NAXIS2": ny}),
                       now=NOW, telescop=telescop, focallen=focal, focratio_raw=f_ratio,
                       xpixsz=3.76)
    return fid


def _tel(con, canon):
    return con.execute("SELECT * FROM telescope WHERE telescop_canon = ?", (canon,)).fetchone()


def _zdarzenia(con, verb, target=None):
    if target is None:
        return con.execute("SELECT count(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]
    return con.execute("SELECT count(*) FROM event WHERE verb = ? AND target = ?",
                       (verb, target)).fetchone()[0]


# ------------------------------------------------------------ wartość z plików (moda, Dostawa)

def test_moda_zamiast_pierwszej_klatki_i_cisza_drugiego_przebiegu():
    """A140R: pierwsza klatka f/8.0, trzy kolejne f/5.6 → oś mówi 5.6, jedno `optics_derived`
    przy powołaniu+odświeżeniu, drugi przebieg ZERO zdarzeń optyki.
    Mutant: `next(...)` pierwszej klatki zamiast mody - oś zostaje na 8.0."""
    con = _baza()
    cam = _kamera(con)
    _klatka(con, "a0", telescop="A140R", focal=784, f_ratio=8.0, camera_id=cam)
    for i in range(3):
        _klatka(con, f"a{i + 1}", telescop="A140R", focal=784, f_ratio=5.6, camera_id=cam)
    grouper.run_grouper(con, NOW)
    t = _tel(con, "A140R")
    assert (t["focal_nominal"], t["f_ratio_nominal"]) == (784, 5.6)
    przed = _zdarzenia(con, "telescope.optics_derived")
    s = grouper.run_grouper(con, LATER)
    assert s.optics_refreshed == 0 and _zdarzenia(con, "telescope.optics_derived") == przed


def test_istniejacy_teleskop_dostaje_mode_przy_kolejnej_dostawie():
    """Teleskop powołany wartością pierwszej klatki (stan sprzed 0039) - Dostawa odświeża go modą
    i pisze jedno `telescope.optics_derived` z `before`/`after`.
    Mutant: odświeżenie pominięte dla istniejącego wiersza (`propose_telescope` bez UPDATE)."""
    con = _baza()
    cam = _kamera(con)
    tid, _ = repo.propose_telescope(con, telescop_canon="A140R", f_ratio_nominal=8.0,
                                    focal_nominal=784, now=NOW)
    for i in range(3):
        _klatka(con, f"a{i}", telescop="A140R", focal=784, f_ratio=5.6, camera_id=cam)
    s = grouper.run_grouper(con, NOW)
    assert s.optics_refreshed == 1 and _tel(con, "A140R")["f_ratio_nominal"] == 5.6
    ev = con.execute("SELECT payload FROM event WHERE verb = 'telescope.optics_derived'").fetchone()
    assert json.loads(ev[0]) == {"before": {"focal": 784, "f_ratio": 8.0},
                                 "after": {"focal": 784, "f_ratio": 5.6}}


def test_glosuja_tylko_aktywne_klatki_a_bez_lightow_flaty():
    """[S4] 20 wycofanych/zastąpionych lightów f/8 przy 10 aktywnych f/5.6 → 5.6; teleskop bez
    lightów bierze modę flatów; stos (`master_light`) nie głosuje.
    Mutanty: brak filtra aktywności (moda 8.0); stosy w `OPTICS_EVIDENCE_KINDS`."""
    con = _baza()
    cam = _kamera(con)
    stare = [_klatka(con, f"s{i}", telescop="A140R", focal=784, f_ratio=8.0, camera_id=cam)
             for i in range(20)]
    nowe = [_klatka(con, f"n{i}", telescop="A140R", focal=784, f_ratio=5.6, camera_id=cam)
            for i in range(10)]
    for i in range(30):
        _klatka(con, f"m{i}", telescop="A140R", focal=800, kind="master_light", camera_id=cam,
                filetype="xisf")
    _klatka(con, "f0", telescop="FLATY", focal=110, f_ratio=2.0, kind="flat", camera_id=cam)
    grouper.run_grouper(con, NOW)
    with con:
        for i, fid in enumerate(stare):
            col = "retired_at" if i % 2 else "superseded_by"
            val = NOW if i % 2 else nowe[0]
            con.execute(f"UPDATE frame SET {col} = ? WHERE id = ?", (val, fid))
    grouper.run_grouper(con, LATER)
    a = _tel(con, "A140R")
    assert (a["focal_nominal"], a["f_ratio_nominal"]) == (784, 5.6)
    assert (_tel(con, "FLATY")["focal_nominal"], _tel(con, "FLATY")["f_ratio_nominal"]) == (110, 2.0)


def test_brak_zeznan_nie_zeruje_wartosci():
    """RC8R: 1200 mm bez ani jednej klatki z ogniskową - Dostawa zostawia 1200.
    Mutant: `refresh_telescope_optics` zapisuje `None` z braku zeznań."""
    con = _baza()
    cam = _kamera(con)
    repo.propose_telescope(con, telescop_canon="RC8R", focal_nominal=1200, now=NOW)
    _klatka(con, "r0", telescop="RC8R", camera_id=cam, filetype="raw")
    grouper.run_grouper(con, NOW)
    assert _tel(con, "RC8R")["focal_nominal"] == 1200


def test_scalenie_moda_na_korzeniu_z_glosami_czlonka_i_jeden_zestaw_planera():
    """[S2] Teleskop A (lighty 900 mm) scalony w B (bez lightów) - moda trafia na KORZEŃ B z głosami
    członka A, A nie dostaje `optics_derived`; planer daje JEDEN zestaw (B, kamera) z kluczem
    `config_id` configu członka (korzeń nie ma własnego z tą kamerą), skala z 900 mm.
    Mutanty: refresh na członku; `rigs` po surowym `config_id` z filtrem `merged_into IS NULL`."""
    con = _baza()
    cam = _kamera(con)
    for i in range(4):
        _klatka(con, f"a{i}", telescop="A", focal=900, f_ratio=7.5, camera_id=cam)
    grouper.run_grouper(con, NOW)
    b, _ = repo.propose_telescope(con, telescop_canon="B", now=NOW)
    a = _tel(con, "A")["id"]
    repo.merge_telescope(con, source_id=a, target_id=b, now=NOW)
    przed_a = _zdarzenia(con, "telescope.optics_derived", f"telescope:{a}")
    grouper.run_grouper(con, LATER)
    assert (_tel(con, "B")["focal_nominal"], _tel(con, "B")["f_ratio_nominal"]) == (900, 7.5)
    assert _zdarzenia(con, "telescope.optics_derived", f"telescope:{a}") == przed_a
    rigs = sky.rigs(con)
    cfg_a = con.execute("SELECT id FROM config WHERE telescope_id = ?", (a,)).fetchone()[0]
    assert [(r.config_id, r.telescope, r.lights) for r in rigs] == [(cfg_a, "B", 4)]
    assert rigs[0].scale_arcsec_px == pytest.approx(206.265 * 3.76 / 900)


# ------------------------------------------------------------ brak rozdziału FITS/XISF (D-1012-2)

def test_program_nie_rozdziela_teleskopu_po_ogniskowej_fits():
    """Lighty jednej nazwy FITS 1600 i 800 mm → JEDEN teleskop; 800 trafia do kubełka ogniskowej.
    Mutant: dawny rozdział po ogniskowej rozszerzony na FITS (dwa teleskopy, kubełek pusty)."""
    con = _baza()
    cam = _kamera(con)
    for i in range(5):
        _klatka(con, f"r{i}", telescop="RC8", focal=1600, f_ratio=8.0, camera_id=cam)
    duze = [_klatka(con, f"d{i}", telescop="RC8", focal=800, f_ratio=8.0, camera_id=cam)
            for i in range(2)]
    grouper.run_grouper(con, NOW)
    assert [r[0] for r in con.execute("SELECT telescop_canon FROM telescope")] == ["RC8"]
    assert resolver.optics_mismatch_frame_ids(con, "focal") == set(duze)
    assert resolver.review_state(con).focal_mismatch == 2


def test_wyjatek_raw_rozdzial_obiektywow_zostaje():
    """`Q14` (rekomendacja, do potwierdzenia): nazwa zastępcza adaptera RAW dzieli się po ogniskowej
    z EXIF-u jak dotąd; przełącznik `RAW_LENS_SPLIT=False` wyłącza rozdział.
    Mutant: przełącznik ignorowany (rozdział zawsze albo nigdy)."""
    for split, oczekiwane in ((True, {"DT 0mm F0 SAM", "DT 0mm F0 SAM @ 70mm"}),
                              (False, {"DT 0mm F0 SAM"})):
        con = _baza()
        cam = _kamera(con, "SONYA7S", 8.45)
        for i, f in enumerate((50, 50, 70)):
            _klatka(con, f"x{i}", telescop="DT 0mm F0 SAM", focal=f, camera_id=cam, filetype="raw")
        stary = grouper.RAW_LENS_SPLIT
        grouper.RAW_LENS_SPLIT = split
        try:
            grouper.run_grouper(con, NOW)
        finally:
            grouper.RAW_LENS_SPLIT = stary
        assert {r[0] for r in con.execute("SELECT telescop_canon FROM telescope")} == oczekiwane


# ------------------------------------------------------------ kubełki optyki (predykat ze stanu)

def _kubelek_baza():
    con = _baza()
    cam = _kamera(con)
    ids = {}
    for i in range(10):
        _klatka(con, f"ok{i}", telescop="RC8", focal=1600, f_ratio=8.0, camera_id=cam)
    ids["f200"] = _klatka(con, "f200", telescop="RC8", focal=1600, f_ratio=200.0, camera_id=cam)
    ids["brak_f"] = _klatka(con, "brakf", telescop="RC8", focal=1600, camera_id=cam)
    ids["ogn_auto"] = _klatka(con, "o1", telescop="RC8", focal=800, f_ratio=8.0, camera_id=cam)
    ids["ogn_reka"] = _klatka(con, "o2", telescop="RC8", focal=800, f_ratio=8.0, camera_id=cam)
    ids["prog_w"] = _klatka(con, "p1", telescop="RC8", focal=1520, f_ratio=8.0, camera_id=cam)
    ids["prog_poza"] = _klatka(con, "p2", telescop="RC8", focal=1680.0, f_ratio=8.0, camera_id=cam)
    ids["prog_poza2"] = _klatka(con, "p3", telescop="RC8", focal=1681.0, f_ratio=8.0, camera_id=cam)
    ids["stos"] = _klatka(con, "st", telescop="RC8", focal=800, kind="master_light", camera_id=cam,
                          filetype="xisf")
    ids["flat"] = _klatka(con, "fl", telescop="RC8", focal=800, f_ratio=8.0, kind="flat",
                          camera_id=cam)
    grouper.run_grouper(con, NOW)
    tel = _tel(con, "RC8")["id"]
    repo.user_assign_config(con, frame_ids=[ids["ogn_reka"]], telescope_id=tel, now=NOW,
                            overwrite=True)
    return con, ids


def test_kubelek_ogniskowej_light_flat_auto_bez_stosow_i_reki_prog_5_procent():
    """[K11] Predykat kubełka ogniskowej: light/flat z zestawem AUTOMATU > 5 % wchodzi, ta sama
    z `config_source='user'` NIE (trwały wybór ręki), stos NIE (`Q15`), 5 % to granica (1520 = 5 %
    poza, 1680 = dokładnie 5 % poza kubełkiem, 1681 w kubełku).
    Mutanty: odwrócony warunek źródła; stosy w kubełku; `>=` zamiast `>`."""
    con, ids = _kubelek_baza()
    assert resolver.optics_mismatch_frame_ids(con, "focal") == {
        ids["ogn_auto"], ids["flat"], ids["prog_poza2"]}


def test_kubelek_f_brak_f_to_nie_niezgodnosc_i_total_bez_zmian():
    """Kubełek f/: f/200 przy f/8 wchodzi, brak f/ NIE (D-1012-2 `Q12`); oba kubełki są POZA
    `total` kolejki przeglądu.
    Mutanty: brak f/ liczony jako niezgodność; kubełek dołożony do `total`."""
    con, ids = _kubelek_baza()
    assert resolver.optics_mismatch_frame_ids(con, "f_ratio") == {ids["f200"]}
    st = resolver.review_state(con)
    assert (st.f_ratio_mismatch, st.focal_mismatch, st.total) == (1, 3, 0)
    assert queries.f_ratio_mismatch_frame_ids(con) == {ids["f200"]}


def test_kubelek_porownuje_z_reka_teleskopu():
    """Ręka wygrywa przy odczycie: ogniskowa ręki 800 → klatki 1600 wchodzą do kubełka, 800 wychodzą.
    Mutant: predykat czyta `focal_nominal` zamiast `COALESCE(focal_user, focal_nominal)`."""
    con, ids = _kubelek_baza()
    repo.set_telescope_focal(con, telescope_id=_tel(con, "RC8")["id"], focal_mm=800, now=NOW)
    w = resolver.optics_mismatch_frame_ids(con, "focal")
    assert ids["ogn_auto"] not in w and ids["f200"] in w


# ------------------------------------------------------------ klingi ręki

def test_reka_ogniskowej_zapis_zdarzenie_idempotencja_i_cofniecie():
    """`set_telescope_focal`: kolumna ręki, zdarzenie {after, before, files}, ta sama wartość → False;
    `clear_telescope_focal`: NULL ręki, automat nietknięty.
    Mutanty: brak zdarzenia; clear czyszczący `focal_nominal`."""
    con = _baza()
    tid, _ = repo.propose_telescope(con, telescop_canon="A140R", focal_nominal=784, now=NOW)
    assert repo.set_telescope_focal(con, telescope_id=tid, focal_mm=780, now=NOW) is True
    assert repo.set_telescope_focal(con, telescope_id=tid, focal_mm=780, now=NOW) is False
    ev = con.execute("SELECT payload, actor FROM event WHERE verb='telescope.focal_user_set'").fetchall()
    assert len(ev) == 1 and json.loads(ev[0][0]) == {"after": 780.0, "before": None, "files": 784}
    assert ev[0][1] == "user:local"
    assert repo.clear_telescope_focal(con, telescope_id=tid, now=NOW) is True
    assert repo.clear_telescope_focal(con, telescope_id=tid, now=NOW) is False
    t = _tel(con, "A140R")
    assert (t["focal_user"], t["focal_nominal"]) == (None, 784)


def test_automat_nie_dotyka_reki_i_odswieza_sie_przy_rece():
    """Ręka 1580 przy plikach 1600: Dostawa nie zmienia ręki, a wartość z plików dalej się
    odświeża (`Q13`), planer bierze rękę.
    Mutanty: refresh piszący `focal_user`; refresh pomijany przy ręce; planer czyta pliki przed ręką."""
    con = _baza()
    cam = _kamera(con)
    for i in range(3):
        _klatka(con, f"r{i}", telescop="RC8", focal=1600, f_ratio=8.0, camera_id=cam)
    grouper.run_grouper(con, NOW)
    tid = _tel(con, "RC8")["id"]
    repo.set_telescope_focal(con, telescope_id=tid, focal_mm=1580, now=NOW)
    for i in range(5):
        _klatka(con, f"n{i}", telescop="RC8", focal=1610, f_ratio=8.0, camera_id=cam)
    grouper.run_grouper(con, LATER)
    t = _tel(con, "RC8")
    assert (t["focal_user"], t["focal_nominal"]) == (1580.0, 1610)
    assert sky.rigs(con)[0].focal_mm == 1580.0


def test_klatka_przypieta_reka_bierze_ogniskowa_teleskopu_nie_pliku():
    """Planer: klatka z plikiem 1600 przypięta ręką do teleskopu 784 daje kadr z 784.
    Mutant: zeznanie klatki przed wartością teleskopu."""
    con = _baza()
    cam = _kamera(con)
    for i in range(3):
        _klatka(con, f"a{i}", telescop="A140R", focal=784, f_ratio=5.6, camera_id=cam)
    obce = [_klatka(con, f"x{i}", telescop="RC8", focal=1600, f_ratio=8.0, camera_id=cam)
            for i in range(5)]
    grouper.run_grouper(con, NOW)
    repo.user_assign_config(con, frame_ids=obce, telescope_id=_tel(con, "A140R")["id"], now=NOW,
                            overwrite=True)
    rig = next(r for r in sky.rigs(con) if r.telescope == "A140R")
    assert (rig.lights, rig.focal_mm, rig.reason) == (8, 784.0, None)


@pytest.mark.parametrize("zly", [0, 4, 4.99, 20001, -1, "784", True, None])
def test_walidator_ogniskowej_wspolny_dla_obu_klingow(zly):
    """[S6] Ta sama odmowa w setterze i w „Dopisz nowy…", z pełnym wycofaniem (zero wierszy, zero
    zdarzeń). Mutant: walidacja tylko w setterze."""
    con = _baza()
    tid, _ = repo.propose_telescope(con, telescop_canon="T", focal_nominal=100, now=NOW)
    cam = _kamera(con)
    fid = _klatka(con, "a", telescop="T", focal=100, camera_id=cam)
    ev = con.execute("SELECT count(*) FROM event").fetchone()[0]
    with pytest.raises(ValueError):
        repo.set_telescope_focal(con, telescope_id=tid, focal_mm=zly, now=NOW)
    with pytest.raises(ValueError):
        repo.user_assign_config_new_telescope(con, frame_ids=[fid], name="Nowy", focal_mm=zly,
                                              now=NOW)
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == ev
    assert con.execute("SELECT count(*) FROM telescope").fetchone()[0] == 1


@pytest.mark.parametrize("zly", [0, 0.49, 50.01, 200, "8"])
def test_walidator_f_wspolny_dla_obu_klingow(zly):
    """[S6] f/ 0,5-50 w obu klingach (f/200 z pliku nie wejdzie do ręki).
    Mutant: zakres tylko w setterze."""
    con = _baza()
    tid, _ = repo.propose_telescope(con, telescop_canon="T", focal_nominal=100, now=NOW)
    fid = _klatka(con, "a", telescop="T", focal=100, camera_id=_kamera(con))
    with pytest.raises(ValueError):
        repo.set_telescope_f_ratio(con, telescope_id=tid, f_ratio=zly, now=NOW)
    with pytest.raises(ValueError):
        repo.user_assign_config_new_telescope(con, frame_ids=[fid], name="Nowy", focal_mm=800,
                                              f_ratio=zly, now=NOW)
    assert con.execute("SELECT count(*) FROM telescope").fetchone()[0] == 1


@pytest.mark.parametrize("zly", [2, -1, "1", 0.5])
def test_walidator_parku_wspolny(zly):
    """[S6] Trójstan parku w `set_telescope_park` i w „Dopisz nowy…". Mutant: brak walidacji parku
    w nowej klindze (INSERT nielegalnego stanu)."""
    con = _baza()
    tid, _ = repo.propose_telescope(con, telescop_canon="T", focal_nominal=100, now=NOW)
    fid = _klatka(con, "a", telescop="T", focal=100, camera_id=_kamera(con))
    with pytest.raises(ValueError):
        repo.set_telescope_park(con, telescope_id=tid, in_park=zly, now=NOW)
    with pytest.raises(ValueError):
        repo.user_assign_config_new_telescope(con, frame_ids=[fid], name="Nowy", focal_mm=800,
                                              in_park=zly, now=NOW)


def test_optyka_tylko_dla_kanonicznego():
    """Ręka optyki na wierszu scalonym → `ValueError` (lustro parku). Mutant: brak guardu."""
    con = _baza()
    a, _ = repo.propose_telescope(con, telescop_canon="A", now=NOW)
    b, _ = repo.propose_telescope(con, telescop_canon="B", now=NOW)
    repo.merge_telescope(con, source_id=a, target_id=b, now=NOW)
    with pytest.raises(ValueError):
        repo.set_telescope_focal(con, telescope_id=a, focal_mm=800, now=NOW)


# ------------------------------------------------------------ „Dopisz nowy…" (jedna transakcja)

def _nowy_baza():
    con = _baza()
    cam = _kamera(con)
    for i in range(3):
        _klatka(con, f"r{i}", telescop="RC8", focal=1600, f_ratio=8.0, camera_id=cam)
    obce = [_klatka(con, f"x{i}", telescop="RC8", focal=800, f_ratio=8.0, camera_id=cam)
            for i in range(2)]
    grouper.run_grouper(con, NOW)
    repo.set_telescope_park(con, telescope_id=_tel(con, "RC8")["id"], in_park=1, now=NOW)
    return con, obce


@pytest.mark.parametrize("park,f", [(None, None), (0, 4.0), (1, 4.0)])
def test_dopisz_nowy_dokladny_stan_i_historia(park, f):
    """[S7] Nowy teleskop: wiersz nazwany, zatwierdzony, z ręką ogniskowej (i f/ gdy podana)
    i parkiem; DOKŁADNA lista zdarzeń teleskopu - `parked` tylko dla 0/1, `f_ratio_user_set`
    tylko przy f/; klatki przypięte ręką; wartość z plików liczona tą samą derywacją (800, 8.0).
    Mutanty: `parked` przy None; brak `f_ratio_user_set`; pominięta inicjalizacja z plików."""
    con, obce = _nowy_baza()
    src = _tel(con, "RC8")["id"]
    tid, g = repo.user_assign_config_new_telescope(
        con, frame_ids=obce, name="RC8 0.5x", focal_mm=800, f_ratio=f, in_park=park,
        source_telescope_id=src, now=NOW)
    assert g.assigned == 2
    t = con.execute("SELECT * FROM telescope WHERE id = ?", (tid,)).fetchone()
    assert (t["telescop_canon"], t["label"], t["status"], t["focal_user"], t["f_ratio_user"],
            t["in_park"], t["focal_nominal"], t["f_ratio_nominal"]) == (
        "RC8 0.5x", "RC8 0.5x", "approved", 800.0, f, park, 800, 8.0)
    verby = [r[0] for r in con.execute(
        "SELECT verb FROM event WHERE target = ? ORDER BY id", (f"telescope:{tid}",))]
    oczekiwane = ["telescope.proposed", "telescope.labeled", "telescope.approved",
                  "telescope.focal_user_set"]
    if f is not None:
        oczekiwane.append("telescope.f_ratio_user_set")
    if park is not None:
        oczekiwane.append("telescope.parked")
    oczekiwane.append("telescope.optics_derived")
    assert verby == oczekiwane
    prop = json.loads(con.execute("SELECT payload FROM event WHERE verb='telescope.proposed' "
                                  "AND target = ?", (f"telescope:{tid}",)).fetchone()[0])
    assert prop["via"] == f"add:{src}"
    if park is not None:
        parked = json.loads(con.execute("SELECT payload FROM event WHERE verb='telescope.parked' "
                                        "AND target = ?", (f"telescope:{tid}",)).fetchone()[0])
        assert parked["via"] == f"add:{src}" and parked["after"] == park
    zrodla = {r[0] for r in con.execute(
        "SELECT config_source FROM frame WHERE id IN (?, ?)", obce)}
    assert zrodla == {"user"}
    assert resolver.optics_mismatch_frame_ids(con, "focal") == set()


def test_dopisz_nowy_zero_klatek_i_blad_w_srodku_wycofuja_calosc(monkeypatch):
    """[S7] Zero przypisanych klatek → `ValueError`, teleskopu nie ma; błąd po INSERT-cie (w środku
    sekwencji) → pełny rollback: zero nowych wierszy i zdarzeń.
    Mutant: osobne transakcje (sierota po błędzie w środku)."""
    con, obce = _nowy_baza()
    n_tel = con.execute("SELECT count(*) FROM telescope").fetchone()[0]
    n_ev = con.execute("SELECT count(*) FROM event").fetchone()[0]
    with pytest.raises(ValueError):
        repo.user_assign_config_new_telescope(con, frame_ids=[], name="Pusty", focal_mm=800, now=NOW)

    def wybuch(*a, **k):
        raise RuntimeError("awaria w środku gestu")
    monkeypatch.setattr(repo, "approve_telescope", wybuch)
    with pytest.raises(RuntimeError):
        repo.user_assign_config_new_telescope(con, frame_ids=obce, name="Środek", focal_mm=800,
                                              now=NOW)
    assert con.execute("SELECT count(*) FROM telescope").fetchone()[0] == n_tel
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == n_ev


def test_nazwa_nowego_teleskopu_zajeta_bez_wielkosci_liter():
    """Nazwa zderza się z kanonem albo etykietą innego teleskopu bez wielkości liter → `ValueError`.
    Mutant: porównanie z wielkością liter (UNIQUE wybuchłby w środku transakcji)."""
    con, obce = _nowy_baza()
    repo.label_telescope(con, telescope_id=_tel(con, "RC8")["id"], label="Ritchey", now=NOW)
    for zla in ("rc8", "RITCHEY", "  "):
        with pytest.raises(ValueError):
            repo.user_assign_config_new_telescope(con, frame_ids=obce, name=zla, focal_mm=800,
                                                  now=NOW)


# ------------------------------------------------------------ lista wyboru i grupy okna

def test_lista_wyboru_w_tolerancji():
    """Lista okna: teleskopy z ogniskową (ręka, potem pliki) w 5 % od 800 mm - 784, 789, 800, 762
    tak, 1600 nie. Odniesieniem jest ogniskowa TELESKOPU, jak w predykacie kubełka (762 + 5 % =
    800,1), więc teleskop z listy nie zostawia klatki w kubełku po geście.
    Mutant: lista bez filtra albo z odniesieniem innym niż predykat kubełka."""
    con = _baza()
    for canon, f in (("A140R", 784), ("ED120R", 789), ("N800", 800), ("RC8", 1600), ("X", 762)):
        repo.propose_telescope(con, telescop_canon=canon, focal_nominal=f, now=NOW)
    assert {r["telescop_canon"] for r in queries.telescopes_near_focal(con, 800)} == {
        "A140R", "ED120R", "N800", "X"}
    repo.set_telescope_focal(con, telescope_id=_tel(con, "X")["id"], focal_mm=700, now=NOW)
    assert "X" not in {r["telescop_canon"] for r in queries.telescopes_near_focal(con, 800)}


def test_grupy_okna_dziela_po_teleskopie_zrodlowym():
    """[S5] Jeden folder i kamera, ta sama ogniskowa pliku, dwa teleskopy źródłowe o przeciwnym
    parku → dwie grupy, każda ze swoim źródłem i parkiem.
    Mutant: klucz grupy bez teleskopu źródłowego."""
    con = _baza()
    cam = _kamera(con)
    for canon, park in (("P", 1), ("H", 0)):
        for i in range(3):
            _klatka(con, f"{canon}{i}", telescop=canon, focal=1600, f_ratio=8.0, camera_id=cam)
        _klatka(con, f"{canon}x", telescop=canon, focal=800, f_ratio=8.0, camera_id=cam)
    grouper.run_grouper(con, NOW)
    for canon, park in (("P", 1), ("H", 0)):
        repo.set_telescope_park(con, telescope_id=_tel(con, canon)["id"], in_park=park, now=NOW)
    with con:
        lok = ("INSERT INTO location(frame_id, volume, path, present) "
               "SELECT id, 'V', 'X:\\archiwum\\M64\\' || sha1_data || '.fits', 1 FROM frame")
        con.execute(lok)
    grupy = queries.focal_mismatch_groups(con)
    assert sorted((g["focal_mm"], g["source_in_park"], g["n_frames"]) for g in grupy) == [
        (800, 0, 1), (800, 1, 1)]
    assert len({g["source_id"] for g in grupy}) == 2


# ------------------------------------------------------------ spis ręki osi teleskopu

def _spis_z(con):
    return audit.human_facts_census(con)


def test_spis_reki_teleskopu_po_rekordach():
    """[S8] Dla KAŻDEGO pola rekordu zmiana wartości przy tej samej liczności bez gestu ręki to
    ubytek; ta sama zmiana gestem ręki po znaku wodnym - nie; nowy rekord - nie; round-trip JSON.
    Mutanty: porównanie liczności; brak normalizacji REAL/INTEGER; wyjaśnianie zdarzeniem automatu."""
    con = _baza()
    a, _ = repo.propose_telescope(con, telescop_canon="A", focal_nominal=784, now=NOW)
    b, _ = repo.propose_telescope(con, telescop_canon="B", focal_nominal=800, now=NOW)
    repo.label_telescope(con, telescope_id=a, label="Askar", now=NOW)
    repo.set_telescope_focal(con, telescope_id=a, focal_mm=800, now=NOW)
    repo.set_telescope_park(con, telescope_id=b, in_park=1, now=NOW)
    przed = audit.HumanFacts(**json.loads(json.dumps(_spis_z(con).snapshot)))
    assert przed == _spis_z(con)                                     # round-trip JSON
    for pole, sql in (("focal_user", "UPDATE telescope SET focal_user = 900 WHERE id = ?"),
                      ("label", "UPDATE telescope SET label = 'Zamiana' WHERE id = ?"),
                      ("in_park", "UPDATE telescope SET in_park = 0 WHERE id = ?"),
                      ("status", "UPDATE telescope SET status = 'approved' WHERE id = ?")):
        cel = b if pole in ("in_park",) else a
        con.execute("SAVEPOINT s")
        con.execute(sql, (cel,))
        teraz = _spis_z(con)
        gesty = audit.telescope_hand_gestures_since(con, przed.event_watermark)
        # każda zmiana pola ręki BEZ gestu - także „w górę" (zatwierdzenie bez gestu) - to zapis
        # automatu na fakcie ręki, więc naruszenie
        assert "telescope_hand" in teraz.spadki(przed, gesty_teleskopu=gesty), pole
        con.execute("ROLLBACK TO s")
        con.execute("RELEASE s")
    repo.set_telescope_focal(con, telescope_id=a, focal_mm=900, now=LATER)   # gest ręki
    teraz = _spis_z(con)
    gesty = audit.telescope_hand_gestures_since(con, przed.event_watermark)
    assert teraz.spadki(przed, gesty_teleskopu=gesty) == {}
    repo.refresh_telescope_optics(con, telescope_id=a, focal=700, f_ratio=None, now=LATER)
    assert _spis_z(con).spadki(przed, gesty_teleskopu=audit.telescope_hand_gestures_since(
        con, przed.event_watermark)) == {}                           # automat ręki nie dotyka


def test_spis_wyjasnia_tylko_gest_tego_pola_i_tylko_reki():
    """Gest ręki na INNYM polu tego samego teleskopu nie wyjaśnia zmiany pola ręki optyki; zdarzenie
    tego pola z aktorem AUTOMATU też nie.
    Mutanty: wyjaśnianie po samym id teleskopu; wyjaśnianie bez filtra aktora `user:*`."""
    con = _baza()
    a, _ = repo.propose_telescope(con, telescop_canon="A", focal_nominal=784, now=NOW)
    repo.set_telescope_focal(con, telescope_id=a, focal_mm=800, now=NOW)
    przed = _spis_z(con)
    repo.label_telescope(con, telescope_id=a, label="Askar", now=LATER)
    with con:
        con.execute("UPDATE telescope SET focal_user = 900 WHERE id = ?", (a,))
        con.execute("INSERT INTO event(ts, actor, verb, target, payload) VALUES "
                    "(?, 'grouper', 'telescope.focal_user_set', ?, '{}')", (LATER, f"telescope:{a}"))
    gesty = audit.telescope_hand_gestures_since(con, przed.event_watermark)
    assert _spis_z(con).reka_teleskopu(przed, gesty) == ((a, "focal_user", 800.0, 900.0),)


def test_po_migracji_reka_rc8r_przezywa_sprzeczne_zeznanie(tmp_path):
    """[S1] Baza v38 z RC8R powołanym ręką (1200) → migracja → lighty `TELESCOP=RC8R` z ogniskową
    1000 → Dostawa: wartość z plików 1000, ręka 1200, planer 1200, spis ręki bez ubytku.
    Mutant: migracja bez backfillu (planer i oś mówią 1000, a spis tego nie widzi)."""
    path = str(tmp_path / "h.db")
    con = db.connect(path)
    for version, filename in db.MIGRATIONS:
        if version <= 38:
            db._apply_migration(con, version, db._migration_sql(filename))
    _teleskop_v38(con, "RC8R", focal=1200, actor="user:local")
    db.migrate(con)
    przed = _spis_z(con)
    cam = _kamera(con, "SONYA7S")
    for i in range(3):
        _klatka(con, f"r{i}", telescop="RC8R", focal=1000, camera_id=cam)
    grouper.run_grouper(con, LATER)
    t = _tel(con, "RC8R")
    assert (t["focal_user"], t["focal_nominal"]) == (1200.0, 1000)
    assert sky.rigs(con)[0].focal_mm == 1200.0
    gesty = audit.telescope_hand_gestures_since(con, przed.event_watermark)
    assert _spis_z(con).spadki(przed, gesty_teleskopu=gesty) == {}
    con.close()


def _teleskop_v38(con, canon, *, focal, f_ratio=None, actor="grouper"):
    """Wiersz osi teleskopu i jego `telescope.proposed` na bazie v38 - gołym SQL-em, tak jak pisała
    go klinga tamtej wersji. Dzisiejsza `repo.propose_telescope` czyta nagrobek (`retired_at`,
    0040), którego schemat v38 nie zna, więc nie buduje bazy sprzed migracji."""
    tid = con.execute(
        "INSERT INTO telescope(telescop_canon, label, f_ratio_nominal, focal_nominal, status, "
        "created_at) VALUES (?, NULL, ?, ?, 'proposed', ?)", (canon, f_ratio, focal, NOW)).lastrowid
    con.execute("INSERT INTO event(ts, actor, verb, target, payload) "
                "VALUES (?, ?, 'telescope.proposed', ?, ?)",
                (NOW, actor, f"telescope:{tid}",
                 json.dumps({"telescop_canon": canon, "f_ratio_nominal": f_ratio,
                             "focal_nominal": focal, "member_count": None})))
    con.commit()
    return tid


# ------------------------------------------------------------ bramka kodu T24 (N1..N22)

def _baza_v38_a140r(path):
    """Baza v38 w stanie żywego archiwum przed 0039: A140R z wartością PIERWSZEJ klatki (f/8.0),
    a w plikach 1 × f/8.0 i 5 × f/5.6."""
    con = db.connect(path)
    for version, filename in db.MIGRATIONS:
        if version <= 38:
            db._apply_migration(con, version, db._migration_sql(filename))
    cam = _kamera(con)
    _klatka(con, "p", telescop="A140R", focal=784, f_ratio=8.0, camera_id=cam)
    for i in range(5):
        _klatka(con, f"n{i}", telescop="A140R", focal=784, f_ratio=5.6, camera_id=cam)
    tid = _teleskop_v38(con, "A140R", focal=784, f_ratio=8.0)
    cfg, _ = repo.propose_config(con, telescope_id=tid, camera_id=cam, now=NOW)
    for (fid,) in con.execute("SELECT id FROM frame").fetchall():
        repo.assign_config(con, frame_id=fid, config_id=cfg, now=NOW)
    con.commit()
    con.close()


def test_n1a_otwarcie_po_migracji_liczy_wartosc_z_plikow_bez_dostawy(tmp_path):
    """N1(a): po otwarciu bazy v38 (`db.open_db`) kolumna automatu niesie modę plików (f/5.6) BEZ
    Dostawy - kubełek f/ liczy wyłącznie mniejszość (1 klatka f/8), nie 5 dobrych plików; zdarzenie
    z aktorem `migration:0039`; drugie otwarcie nic nie pisze.
    Mutant: `open_db` bez kroku pomigracyjnego (kubełek 5 klatek f/5.6, kolumna 8.0)."""
    path = str(tmp_path / "h.db")
    _baza_v38_a140r(path)
    con = db.open_db(path)
    assert _tel(con, "A140R")["f_ratio_nominal"] == 5.6
    assert len(resolver.optics_mismatch_frame_ids(con, "f_ratio")) == 1
    ev = con.execute("SELECT actor FROM event WHERE verb = 'telescope.optics_derived'").fetchall()
    assert [r[0] for r in ev] == ["migration:0039"]
    n = con.execute("SELECT count(*) FROM event").fetchone()[0]
    con.close()
    con = db.open_db(path)
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == n
    con.close()


def test_n1b_gest_odmawia_celu_niezgodnego_z_wiekszoscia_plikow():
    """N1(b): kolumna teleskopu sprzed przeliczenia (f/8.0 przy plikach 5 × f/5.6) → cel gestu dla
    każdej klatki to odmowa `majority`; literówka ręki 0.8 - tak samo; cel zgodny z większością
    przechodzi. Mutant: strażnik większości zdjęty (cel 8.0 dla dobrych plików)."""
    con = _baza()
    cam = _kamera(con)
    _klatka(con, "p", telescop="A140R", focal=784, f_ratio=8.0, camera_id=cam)
    dobre = [_klatka(con, f"n{i}", telescop="A140R", focal=784, f_ratio=5.6, camera_id=cam)
             for i in range(5)]
    grouper.run_grouper(con, NOW)
    tid = _tel(con, "A140R")["id"]
    with con:
        con.execute("UPDATE telescope SET f_ratio_nominal = 8.0 WHERE id = ?", (tid,))
    cele = queries.optics_fix_targets(con, dobre)
    assert {(c[1], c[2]) for c in cele} == {(None, "majority")}
    repo.set_telescope_f_ratio(con, telescope_id=tid, f_ratio=0.8, now=NOW)
    assert {c[2] for c in queries.optics_fix_targets(con, dobre)} == {"majority"}
    repo.clear_telescope_f_ratio(con, telescope_id=tid, now=NOW)
    grouper.run_grouper(con, LATER)
    zla = con.execute("SELECT frame_id FROM header WHERE focratio_raw = 8.0").fetchone()[0]
    assert queries.optics_fix_targets(con, [zla])[0][1:3] == (5.6, None)


def test_n2_przypiecie_odswieza_zrodlo_i_cel_w_tej_samej_transakcji():
    """N2: teleskop X ma 2 klatki 1600 i 3 klatki 800 (moda 800); przypięcie trzech 800 ręką do
    N800 przelicza X na 1600 i N800 bez Dostawy, zdarzenie z aktorem gestu.
    Mutant: `user_assign_config` bez odświeżenia (X zostaje 800)."""
    con = _baza()
    cam = _kamera(con)
    for i in range(2):
        _klatka(con, f"x{i}", telescop="X", focal=1600, f_ratio=8.0, camera_id=cam)
    obce = [_klatka(con, f"y{i}", telescop="X", focal=800, f_ratio=4.0, camera_id=cam)
            for i in range(3)]
    _klatka(con, "n0", telescop="N800", focal=800, camera_id=cam)
    grouper.run_grouper(con, NOW)
    assert _tel(con, "X")["focal_nominal"] == 800
    repo.user_assign_config(con, frame_ids=obce, telescope_id=_tel(con, "N800")["id"], now=LATER,
                            overwrite=True)
    x = _tel(con, "X")
    assert (x["focal_nominal"], x["f_ratio_nominal"]) == (1600, 8.0)
    assert _tel(con, "N800")["f_ratio_nominal"] == 4.0          # f/ tylko z klatek ręki - jedyny świadek
    aktorzy = {r[0] for r in con.execute(
        "SELECT actor FROM event WHERE verb = 'telescope.optics_derived' AND ts = ?", (LATER,))}
    assert aktorzy == {"user:local"}


def test_n9_n10_kubelek_f_lighty_takze_przypiete_reka_bez_flatow():
    """N9/N10: kubełek f/ bierze light przypięty ręką z f/ poza tolerancją, a NIE bierze flatu.
    Mutanty: warunek `config_source IS NULL` w gałęzi f/; flaty w gałęzi f/."""
    con = _baza()
    cam = _kamera(con)
    for i in range(5):
        _klatka(con, f"r{i}", telescop="RC8", focal=1600, f_ratio=8.0, camera_id=cam)
    reka = _klatka(con, "h", telescop="RC8", focal=1600, f_ratio=200.0, camera_id=cam)
    flat = _klatka(con, "fl", telescop="RC8", focal=1600, f_ratio=200.0, kind="flat", camera_id=cam)
    grouper.run_grouper(con, NOW)
    repo.user_assign_config(con, frame_ids=[reka], telescope_id=_tel(con, "RC8")["id"], now=NOW,
                            overwrite=True)
    w = resolver.optics_mismatch_frame_ids(con, "f_ratio")
    assert reka in w and flat not in w


def test_n12_przywroc_z_plikow_jedna_transakcja(monkeypatch):
    """N12: `clear_telescope_optics` zdejmuje obie ręce jedną transakcją; błąd drugiego pola wycofuje
    pierwsze. Mutant: dwie osobne transakcje (ogniskowa zdjęta mimo błędu)."""
    con = _baza()
    tid, _ = repo.propose_telescope(con, telescop_canon="T", focal_nominal=100, now=NOW)
    repo.set_telescope_focal(con, telescope_id=tid, focal_mm=110, now=NOW)
    repo.set_telescope_f_ratio(con, telescope_id=tid, f_ratio=5.0, now=NOW)
    assert repo.clear_telescope_optics(con, telescope_id=tid, now=NOW) == (True, True)
    repo.set_telescope_focal(con, telescope_id=tid, focal_mm=110, now=NOW)
    repo.set_telescope_f_ratio(con, telescope_id=tid, f_ratio=5.0, now=NOW)

    def wybuch(*a, **k):
        raise RuntimeError("awaria drugiego pola")
    monkeypatch.setattr(repo, "clear_telescope_f_ratio", wybuch)
    with pytest.raises(RuntimeError):
        repo.clear_telescope_optics(con, telescope_id=tid, now=NOW)
    assert _tel(con, "T")["focal_user"] == 110.0


def test_n14_powody_zestawu_maja_wlasciciela():
    """N14: każdy powód, który `_rig_from_rows` produkuje, jest w `sky.RIG_REASONS`.
    Mutant: nowy powód w `sky` bez wpisu w stałej."""
    def wiersz(**k):
        base = {"telescope": "T", "camera": "C", "focal": 100.0, "pixel": 3.76, "cam_pixel": 3.76,
                "cam_conflict": 0, "cam_source": None, "tel_focal_user": None,
                "tel_focal_files": None, "nx": 100, "ny": 80, "d": "2026"}
        base.update(k)
        return base
    powody = {sky._rig_from_rows(1, [wiersz(**k)]).reason for k in (
        {"focal": None}, {"pixel": None, "cam_pixel": None}, {"nx": None})}
    powody.add(sky._rig_from_rows(1, [wiersz(focal=100.0), wiersz(focal=200.0)]).reason)
    assert powody == set(sky.RIG_REASONS)
