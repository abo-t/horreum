"""Oś KALIBRACJI — RODOWÓD light↔master (C4, #6): dopasowanie po przepisie, reguła czasowa,
kubełki „czego brakuje", idempotencja, re-link przy bliższym masterze."""
import json

import pytest

from horreum import db, repo
from horreum.calibration import run_calibration
from horreum.lineage import run_lineage

NOW = "2026-07-23T12:00:00+00:00"
# Masterdark: header milczy, fakty (gain/offset/temp) idą ze ŚCIEŻKI — ten sam wzorzec co C2.
MASTERDARK = (r"R:\ASTRO_\CALIBRATION\masters\darks\ASI2600MM_100_21"
              r"\MASTERDARK_26MM_G100_O21_10_0300.000_EXPOSURE_300s.xisf")


@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "h.db"))
    c.execute("INSERT INTO camera(model_canon, pixel_um, is_mono, created_at) "
              "VALUES ('ASI2600MM', 3.76, 1, ?)", (NOW,))
    c.execute("INSERT INTO telescope(telescop_canon, status, created_at) "
              "VALUES ('A140R', 'proposed', ?)", (NOW,))
    c.execute("INSERT INTO config(telescope_id, camera_id, label, status, created_at) "
              "VALUES (1, 1, 'A140R x ASI2600MM', 'proposed', ?)", (NOW,))
    yield c
    c.close()


def _frame(con, *, kind, sha1, path=None, config_id=None, filter_canon=None, exptime=None,
           set_temp=None, gain=None, offset_adu=None, xbinning=1, date_obs=None):
    """Klatka + nagłówek. `set_temp` wchodzi przez `raw_json` (kolumna GENERATED), jak w realnym
    zeznaniu — light niesie nastawę, master nie (integracja ją zjada)."""
    raw = json.dumps({"SET-TEMP": set_temp}) if set_temp is not None else "{}"
    cur = con.execute(
        "INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, filter_canon, "
        "first_seen_at) VALUES (?, ?, 'xisf', 1, ?, ?, ?)",
        (sha1, kind, config_id, filter_canon, NOW))
    fid = cur.lastrowid
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, exptime, gain, offset_adu, "
                "xbinning) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (fid, raw, date_obs, exptime, gain, offset_adu, xbinning))
    if path:
        con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (fid, path))
    con.commit()
    return fid


def _light_dark(con, sha1, *, exptime=300.0, temp=-10, gain=100, offset=21, date="2024-01-01T00:00:00"):
    """Light z kompletnym przepisem DARKA — jego klucz musi zejść BAJTOWO z kluczem masterdarka
    ze ścieżki (szew header↔ścieżka)."""
    return _frame(con, kind="light", sha1=sha1, exptime=exptime, set_temp=temp, gain=gain,
                  offset_adu=offset, date_obs=date)


def test_light_linkuje_masterdark_szew_header_sciezka(con):
    """Klucz lightu z NAGŁÓWKA (SET-TEMP/gain/offset) == klucz masterdarka ze ŚCIEŻKI (`source='path'`).
    To najgorętszy szew: dwa różne źródła składają ten sam przepis."""
    md = _frame(con, kind="master_dark", sha1="d1", path=MASTERDARK, exptime=300.0,
                date_obs="2023-01-01T00:00:00")
    lid = _light_dark(con, "l1")
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)

    assert s.lights == 1 and s.linked.get("dark") == 1
    row = con.execute("SELECT master_frame_id, relation, asserted_by, confidence FROM calibration "
                      "WHERE light_frame_id = ?", (lid,)).fetchone()
    assert (row["master_frame_id"], row["relation"]) == (md, "dark")
    assert (row["asserted_by"], row["confidence"]) == ("horreum", "recipe")
    assert con.execute("SELECT count(*) FROM event WHERE verb='calibration.linked'").fetchone()[0] == 1


def test_flat_wybiera_najblizszy_czasowo(con):
    """Profil FLAT z dwoma masterflatami różnej daty — light bierze BLIŻSZY czasowo, nie pierwszy."""
    stary = _frame(con, kind="master_flat", sha1="f_old", config_id=1, filter_canon="Ha",
                   date_obs="2022-01-01T00:00:00")
    nowy = _frame(con, kind="master_flat", sha1="f_new", config_id=1, filter_canon="Ha",
                  date_obs="2025-01-01T00:00:00")
    lid = _frame(con, kind="light", sha1="l1", config_id=1, filter_canon="Ha",
                 date_obs="2024-11-01T00:00:00")                 # bliżej `nowy`
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)

    assert s.linked.get("flat") == 1
    mid = con.execute("SELECT master_frame_id FROM calibration WHERE light_frame_id=? AND relation='flat'",
                      (lid,)).fetchone()[0]
    assert mid == nowy and mid != stary


def test_remis_tie_break_min_id(con):
    """Dwa masterflaty o TEJ SAMEJ dacie (remis |Δ|) → MIN frame.id, deterministycznie."""
    m1 = _frame(con, kind="master_flat", sha1="fa", config_id=1, filter_canon="Ha",
                date_obs="2024-01-01T00:00:00")
    _frame(con, kind="master_flat", sha1="fb", config_id=1, filter_canon="Ha",
           date_obs="2024-01-01T00:00:00")
    lid = _frame(con, kind="light", sha1="l1", config_id=1, filter_canon="Ha",
                 date_obs="2024-06-01T00:00:00")
    run_calibration(con, now=NOW)
    run_lineage(con, now=NOW)
    mid = con.execute("SELECT master_frame_id FROM calibration WHERE light_frame_id=?", (lid,)).fetchone()[0]
    assert mid == m1                                             # niższy id wygrywa remis


def test_kalibrator_to_zawsze_master_nie_surowy(con):
    """Profil ma surowy flat I masterflat — light linkuje MASTER, nigdy surowy (brief C2 §5)."""
    _frame(con, kind="flat", sha1="raw", config_id=1, filter_canon="Ha",
           date_obs="2024-05-01T00:00:00")                       # surowy — BLIŻEJ lightu
    master = _frame(con, kind="master_flat", sha1="m", config_id=1, filter_canon="Ha",
                    date_obs="2022-01-01T00:00:00")              # master — DALEJ
    lid = _frame(con, kind="light", sha1="l1", config_id=1, filter_canon="Ha",
                 date_obs="2024-06-01T00:00:00")
    run_calibration(con, now=NOW)
    run_lineage(con, now=NOW)
    mid = con.execute("SELECT master_frame_id FROM calibration WHERE light_frame_id=?", (lid,)).fetchone()[0]
    assert mid == master                                         # mimo że surowy jest bliżej


def test_brak_przepisu_w_archiwum(con):
    """Light o przepisie, którego archiwum nie zna → kubełek „brak przepisu", zero wierszy."""
    _light_dark(con, "l1", exptime=999.0)                        # żaden master 999 s
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)
    assert s.linked.get("dark", 0) == 0
    assert s.reasons.get("dark: brak przepisu w archiwum") == 1
    assert con.execute("SELECT count(*) FROM calibration").fetchone()[0] == 0


def test_brak_mastera_sa_tylko_surowe(con):
    """Profil istnieje (surowy flat), ale bez masterflata → kubełek „brak mastera"."""
    _frame(con, kind="flat", sha1="raw", config_id=1, filter_canon="Ha", date_obs="2024-01-01T00:00:00")
    _frame(con, kind="light", sha1="l1", config_id=1, filter_canon="Ha", date_obs="2024-02-01T00:00:00")
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)
    assert s.reasons.get("flat: brak mastera (są tylko surowe)") == 1
    assert con.execute("SELECT count(*) FROM calibration WHERE relation='flat'").fetchone()[0] == 0


def test_niekompletny_przepis_lightu(con):
    """Light bez nastawy (brak SET-TEMP) → dark-przepis niekompletny → kubełek, nie klucz z sentinelem."""
    _frame(con, kind="master_dark", sha1="d1", path=MASTERDARK, exptime=300.0, date_obs="2023-01-01T00:00:00")
    _frame(con, kind="light", sha1="l1", exptime=300.0, gain=100, offset_adu=21,  # set_temp brak
           date_obs="2024-01-01T00:00:00")
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)
    assert s.reasons.get("dark: niekompletny przepis lightu") == 1
    assert s.linked.get("dark", 0) == 0


def test_domkniecie_populacji_per_relacja(con):
    """Suma kubełków (linked + luki) == lighty, dla KAŻDEJ relacji — brama fałszywie zielona inaczej."""
    _frame(con, kind="master_dark", sha1="d1", path=MASTERDARK, exptime=300.0, date_obs="2023-01-01T00:00:00")
    _frame(con, kind="master_flat", sha1="f1", config_id=1, filter_canon="Ha", date_obs="2023-01-01T00:00:00")
    _light_dark(con, "l_ok", date="2024-01-01T00:00:00")         # dark linked; flat: brak przepisu (bez configu/filtra)
    _frame(con, kind="light", sha1="l_flat", config_id=1, filter_canon="Ha", exptime=999.0,
           date_obs="2024-01-01T00:00:00")                       # flat linked; dark: brak przepisu 999
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)
    for rel in ("dark", "flat"):
        gaps = sum(n for powod, n in s.reasons.items() if powod.startswith(f"{rel}:"))
        assert s.linked.get(rel, 0) + gaps == s.lights == 2


def test_idempotencja(con):
    """Drugi przebieg na niezmienionych danych = zero zapisów i zero eventów rodowodu."""
    _frame(con, kind="master_dark", sha1="d1", path=MASTERDARK, exptime=300.0, date_obs="2023-01-01T00:00:00")
    _light_dark(con, "l1")
    run_calibration(con, now=NOW)
    run_lineage(con, now=NOW)
    ev1 = con.execute("SELECT count(*) FROM event WHERE verb='calibration.linked'").fetchone()[0]
    rows1 = con.execute("SELECT count(*) FROM calibration").fetchone()[0]
    s2 = run_lineage(con, now=NOW)
    assert not s2.linked_new
    assert con.execute("SELECT count(*) FROM event WHERE verb='calibration.linked'").fetchone()[0] == ev1
    assert con.execute("SELECT count(*) FROM calibration").fetchone()[0] == rows1


def test_relink_gdy_dojdzie_blizszy_master(con):
    """Nowy wsad z masterflatem bliższym czasowo → UPDATE + unlinked(stary) + linked(nowy), JEDEN wiersz."""
    stary = _frame(con, kind="master_flat", sha1="f_old", config_id=1, filter_canon="Ha",
                   date_obs="2020-01-01T00:00:00")
    lid = _frame(con, kind="light", sha1="l1", config_id=1, filter_canon="Ha",
                 date_obs="2024-06-01T00:00:00")
    run_calibration(con, now=NOW)
    run_lineage(con, now=NOW)
    assert con.execute("SELECT master_frame_id FROM calibration WHERE light_frame_id=?", (lid,)).fetchone()[0] == stary

    nowy = _frame(con, kind="master_flat", sha1="f_new", config_id=1, filter_canon="Ha",
                  date_obs="2024-05-01T00:00:00")                # bliżej lightu
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)
    assert s.linked_new.get("flat") == 1                        # re-link policzony jako zmiana
    rows = con.execute("SELECT master_frame_id FROM calibration WHERE light_frame_id=? AND relation='flat'",
                       (lid,)).fetchall()
    assert len(rows) == 1 and rows[0][0] == nowy                # UNIQUE trzyma jeden wiersz
    assert con.execute("SELECT count(*) FROM event WHERE verb='calibration.unlinked'").fetchone()[0] == 1


def test_nowy_master_NIE_przepina_ogniwa_wskazanego_reka(con):
    """E4-2 / warunek Zdzinia 0809: „wprowadzanie nowych masterów nie może wpłynąć na wycofanie
    czegokolwiek już ustawionego ręcznie".

    Lustro testu wyżej, z jedną różnicą: ogniwo wskazała RĘKA. Do 0809 ta oś była JEDYNĄ osią
    rodowodu bez bramki precedencji — siostrzana `link_integration` ma `RANGA_ASSERT`,
    `calibration_fact` ma człon `source == 'user'`, a tutaj nowy flat przepinał bezwarunkowo.
    Warunek trzymał się wyłącznie na tym, że gestu ręki na tej osi jeszcze nie ma (populacja 0)."""
    stary = _frame(con, kind="master_flat", sha1="f_old", config_id=1, filter_canon="Ha",
                   date_obs="2020-01-01T00:00:00")
    lid = _frame(con, kind="light", sha1="l1", config_id=1, filter_canon="Ha",
                 date_obs="2024-06-01T00:00:00")
    run_calibration(con, now=NOW)
    run_lineage(con, now=NOW)
    # Ręka rozstrzyga: TEN flat, choćby jutro doszedł bliższy czasowo.
    assert repo.link_calibration(con, light_frame_id=lid, master_frame_id=stary, relation="flat",
                                 now=NOW, asserted_by="user") is True

    nowy = _frame(con, kind="master_flat", sha1="f_new", config_id=1, filter_canon="Ha",
                  date_obs="2024-05-01T00:00:00")               # bliżej lightu niż wskazany ręką
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)

    row = con.execute("SELECT master_frame_id, asserted_by FROM calibration "
                      "WHERE light_frame_id=? AND relation='flat'", (lid,)).fetchone()
    assert row[:] == (stary, "user")                            # werdykt stoi
    assert s.linked_new.get("flat") is None                     # przebieg NIE zapisał zmiany
    # FALSYFIKATOR: bramka broni przed AUTOMATEM, nie przed człowiekiem — ręka zmienia zdanie.
    assert repo.link_calibration(con, light_frame_id=lid, master_frame_id=nowy, relation="flat",
                                 now=NOW, asserted_by="user") is True
    assert con.execute("SELECT master_frame_id FROM calibration WHERE light_frame_id=? "
                       "AND relation='flat'", (lid,)).fetchone()[0] == nowy


def test_light_bez_date_obs_degeneruje_do_min_id_bez_crash(con):
    """Light bez `date_obs` w profilu wielo-masterowym → MIN frame.id, jawnie, nie crash."""
    m1 = _frame(con, kind="master_flat", sha1="fa", config_id=1, filter_canon="Ha", date_obs="2022-01-01T00:00:00")
    _frame(con, kind="master_flat", sha1="fb", config_id=1, filter_canon="Ha", date_obs="2025-01-01T00:00:00")
    lid = _frame(con, kind="light", sha1="l1", config_id=1, filter_canon="Ha", date_obs=None)
    run_calibration(con, now=NOW)
    run_lineage(con, now=NOW)
    assert con.execute("SELECT master_frame_id FROM calibration WHERE light_frame_id=?", (lid,)).fetchone()[0] == m1


# --- ODCZYT POJEDYNCZEJ KLATKI (`explain_light`, C3/#6) — materiał panelu „Rodowód" ---

def test_explain_light_oddaje_stan_a_nie_ponowna_derywacje(con):
    """Powiązanie bierze się z TABELI, nie z ponownego liczenia: panel pokazuje to, co zapisano,
    więc gdy ktoś podmieni master ręką, ekran mówi o TYM masterze, a nie o tym, który wyszedłby
    dziś z reguły czasowej (REVIEW-ZE-STANU)."""
    from horreum.lineage import explain_light
    md = _frame(con, kind="master_dark", sha1="d1", path=MASTERDARK, exptime=300.0,
                date_obs="2023-01-01T00:00:00")
    lid = _light_dark(con, "l1")
    run_calibration(con, now=NOW)
    run_lineage(con, now=NOW)

    stan = {r["relation"]: r for r in explain_light(con, lid)}
    assert set(stan) == {"dark", "flat"}                    # ZAWSZE obie klasy, także ta pusta
    assert stan["dark"]["master_frame_id"] == md
    assert stan["dark"]["master_path"] == MASTERDARK        # ścieżka pod wiersz listy
    assert (stan["dark"]["gap"], stan["dark"]["pending"]) == (None, False)
    # Flat nie ma nawet z czego złożyć klucza (ten light nie niesie filtra) — to LUKA, i to ona,
    # nie cisza, jedzie na ekran. Powód jest PRECYZYJNY: nie „brak w archiwum", tylko „klatka nie
    # podaje, czego szukać" — dwie różne naprawy.
    assert stan["flat"]["gap"] == "incomplete_recipe" and not stan["flat"]["pending"]


def test_explain_light_odroznia_nieliczone_od_luki_archiwum(con):
    """TRZECI STAN, sedno C3: master JEST, tylko powiązania nikt jeszcze nie policzył. Bez tego
    rozróżnienia ekran mówiłby „brak" o czymś, co leży w archiwum — i kazałby szukać winy
    w sprzęcie zamiast uruchomić etap. Falsyfikator: po przebiegu ten sam light ma `pending=False`."""
    from horreum.lineage import explain_light
    _frame(con, kind="master_dark", sha1="d1", path=MASTERDARK, exptime=300.0,
           date_obs="2023-01-01T00:00:00")
    lid = _light_dark(con, "l1")
    run_calibration(con, now=NOW)                           # oś przepisu tak, rodowód NIE

    przed = {r["relation"]: r for r in explain_light(con, lid)}
    assert przed["dark"]["pending"] and przed["dark"]["gap"] is None
    assert przed["dark"]["master_frame_id"] is None          # bo w tabeli nadal nic nie ma

    run_lineage(con, now=NOW)
    po = {r["relation"]: r for r in explain_light(con, lid)}
    assert not po["dark"]["pending"] and po["dark"]["master_frame_id"] is not None


def test_explain_light_milczy_o_klatce_ktora_nie_jest_lightem(con):
    """Kalibratory ma z definicji tylko klatka nieba (ta sama figura kind-aware co oś teleskopu).
    Master sam jest narzędziem — pytanie „czym go skalibrowano" nie ma treści, więc odpowiedzią
    jest `None`, a nie pusta lista udająca zmierzone zero."""
    from horreum.lineage import explain_light
    md = _frame(con, kind="master_dark", sha1="d1", path=MASTERDARK, exptime=300.0)
    assert explain_light(con, md) is None
    assert explain_light(con, 9999) is None                  # klatka, której nie ma


def test_obie_drogi_czytaja_TE_SAME_kolumny_przepisu():
    """BRAMKA KLASY, nie przypadek: przebieg i odczyt pojedynczej klatki mają dwa PEŁNE literały
    SQL (wymusza to `test_repo_safety` — sklejany SQL byłby dla niej dynamiczny). Rozjazd list
    kolumn znaczyłby, że panel tłumaczy brak z innego zeznania, niż przebieg go tworzy — cicho
    i tylko dla pola, które ktoś dodał w jednym miejscu."""
    import ast
    import pathlib

    import horreum
    # Ścieżka z PAKIETU, nie z katalogu startowego — `build.ps1` odpala pytest z innego CWD,
    # a bramka meta nie ma prawa padać z powodu miejsca uruchomienia.
    src = (pathlib.Path(horreum.__file__).parent / "lineage.py").read_text(encoding="utf-8")
    stale = [n.value for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Constant) and isinstance(n.value, str)]

    for prefiks, opis in (("SELECT f.id AS frame_id", "przepis lightu"),
                          ("SELECT f.calibration_profile_id AS pid", "kandydaci masterów")):
        listy = [s.split(" FROM ")[0] for s in stale if s.startswith(prefiks)]
        assert len(listy) == 2, f"spodziewane dwa zapytania: {opis} — jest {len(listy)}"
        assert listy[0] == listy[1], f"przebieg i panel czytają INNE kolumny — {opis}"


def test_gotowy_obraz_NIE_udaje_nieposzytej_osi_przepisu(con):
    """FALSYFIKATOR ZNALEZISKA WIZYTACJI (P1, `265cf2d`): `master_light` — gotowy obraz po integracji
    — profilu nie ma i mieć NIE BĘDZIE, bo `KIND_RECIPE` go nie zna. Predykat pytający o „każdy
    master" (`kind LIKE 'master_%'`) łapał go razem z kalibracyjnymi, więc JEDEN wciągnięty stos
    zapalał na stałe zdanie „przepisy nie są jeszcze policzone" — o bazie z policzoną osią przepisu,
    z odesłaniem do etapu, który niczego nie zmieni. Droga „Stosy" wciąga ich 128.

    Test trzyma OBIE strony: przy policzonej osi przepisu obecność stosu nie zmienia powodu luki,
    a prawdziwy master kalibracyjny bez profilu ten powód nadal zapala."""
    from horreum.lineage import explain_light
    _frame(con, kind="master_light", sha1="stos1", date_obs="2024-02-01T00:00:00")   # gotowy obraz
    lid = _light_dark(con, "l1", exptime=999.0)          # przepis, którego archiwum nie zna
    run_calibration(con, now=NOW)

    stan = {r["relation"]: r for r in explain_light(con, lid)}
    assert stan["dark"]["gap"] == "no_profile", "gotowy obraz udaje niepoliczoną oś przepisu"

    # Druga strona: master KALIBRACYJNY bez profilu to prawdziwy sygnał „uruchom Kalibrację".
    _frame(con, kind="master_dark", sha1="d_bez", exptime=300.0)   # bez ścieżki i faktów → bez profilu
    stan2 = {r["relation"]: r for r in explain_light(con, lid)}
    assert stan2["dark"]["gap"] == "not_calibrated"


# --- SUROWE FLATY POD WYDANIE (`raw_flats_for`) - odczyt, który niczego nie zapisuje do `calibration` ---

def _surowy(con, sha1, date_obs, *, filter_canon="Ha", present=True):
    """Surowy flat profilu (config 1 = A140R x ASI2600MM) z kopią na dysku; `present=False` = kopia
    zniknęła (pass obecności), czyli kandydat, którego WBPP nie dostanie."""
    fid = _frame(con, kind="flat", sha1=sha1, path=rf"R:\FLATS\{sha1}.fits", config_id=1,
                 filter_canon=filter_canon, date_obs=date_obs)
    if not present:
        con.execute("UPDATE location SET present = 0 WHERE frame_id = ?", (fid,))
        con.commit()
    return fid


def _light_ha(con, sha1, date_obs):
    return _frame(con, kind="light", sha1=sha1, config_id=1, filter_canon="Ha", date_obs=date_obs)


def test_surowe_ta_sama_noc_wszystkie_klatki_nocy(con):
    """Noc to `date(date_obs, '-12 hours')` (D-UX-1): flat o świcie (05:30) należy do nocy lightu
    z 23:00 dnia poprzedniego - inaczej poranne flaty sesji wyglądałyby na „dzień później". Wybór
    to WSZYSTKIE klatki profilu z tej nocy (WBPP składa master z kompletu sesji)."""
    from horreum.lineage import raw_flats_for
    f1 = _surowy(con, "f1", "2024-03-02T05:30:00")
    f2 = _surowy(con, "f2", "2024-03-02T05:31:00")
    lid = _light_ha(con, "l1", "2024-03-01T23:00:00")
    run_calibration(con, now=NOW)

    pick = raw_flats_for(con, [lid])[lid]
    assert pick.frame_ids == (f1, f2) and pick.gap is None
    assert (pick.night, pick.days_apart) == ("2024-03-01", 0)
    assert pick.profile_id is not None
    assert con.execute("SELECT count(*) FROM calibration").fetchone()[0] == 0   # odczyt, zero zapisu


def test_surowe_najblizsza_noc_w_oknie(con):
    """Bliższa noc wygrywa, a z dalszej nie bierze się ani jednej klatki (to inna sesja)."""
    from horreum.lineage import raw_flats_for
    _surowy(con, "daleko", "2024-03-01T22:00:00")
    blisko = _surowy(con, "blisko", "2024-03-20T22:00:00")
    lid = _light_ha(con, "l1", "2024-03-15T22:00:00")
    run_calibration(con, now=NOW)

    pick = raw_flats_for(con, [lid])[lid]
    assert pick.frame_ids == (blisko,) and (pick.night, pick.days_apart) == ("2024-03-20", 5)


def test_surowe_remis_wczesniejsza_noc(con):
    """Remis odległości → WCZEŚNIEJSZA noc, deterministycznie (nie kolejność wierszy w bazie)."""
    from horreum.lineage import raw_flats_for
    _surowy(con, "pozniej", "2024-03-20T22:00:00")                # wjeżdża PIERWSZY (niższe id)
    wczesniej = _surowy(con, "wczesniej", "2024-03-10T22:00:00")
    lid = _light_ha(con, "l1", "2024-03-15T22:00:00")
    run_calibration(con, now=NOW)

    pick = raw_flats_for(con, [lid])[lid]
    assert pick.frame_ids == (wczesniej,) and (pick.night, pick.days_apart) == ("2024-03-10", 5)


def test_surowe_poza_oknem_niesie_odleglosc(con):
    """Najbliższa noc dalej niż okno → `out_of_window` z liczbą dni i nocą (rozmowa „są, ale daleko"),
    bez klatek. Szersze okno tę samą noc przyjmuje - granica jest włączna."""
    from horreum.lineage import raw_flats_for
    f = _surowy(con, "stary", "2024-01-01T22:00:00")
    lid = _light_ha(con, "l1", "2024-03-15T22:00:00")
    run_calibration(con, now=NOW)

    pick = raw_flats_for(con, [lid])[lid]
    assert (pick.gap, pick.frame_ids) == ("out_of_window", ())
    assert (pick.night, pick.days_apart) == ("2024-01-01", 74)
    assert raw_flats_for(con, [lid], window_days=74)[lid].frame_ids == (f,)


def test_surowe_luki_przepisu_ta_sama_derywacja_co_przebieg(con):
    """`no_profile` (przepis, którego archiwum nie zna) i `incomplete_recipe` (light bez configu -
    flat nie złoży klucza bez teleskopu) - te same tokeny, które dałby `_decide` przebiegu."""
    from horreum.lineage import raw_flats_for
    _surowy(con, "f_ha", "2024-03-01T22:00:00")
    oiii = _frame(con, kind="light", sha1="l_oiii", config_id=1, filter_canon="OIII",
                  date_obs="2024-03-01T23:00:00")
    bez_configu = _frame(con, kind="light", sha1="l_bez", filter_canon="Ha", date_obs="2024-03-01T23:00:00")
    run_calibration(con, now=NOW)

    out = raw_flats_for(con, [oiii, bez_configu])
    assert (out[oiii].gap, out[oiii].profile_id) == ("no_profile", None)
    assert (out[bez_configu].gap, out[bez_configu].profile_id) == ("incomplete_recipe", None)
    assert out[oiii].frame_ids == () and out[oiii].days_apart is None


def test_surowe_pending_gdy_przepis_wskazuje_mastera(con):
    """Master flat w profilu jest, a wiersza `calibration` nie ma → `pending` (przelicz rodowód),
    a nie surowe flaty obok mastera. Po przebiegu light ma flat w stanie i z wyniku WYPADA."""
    from horreum.lineage import raw_flats_for
    _surowy(con, "f_ha", "2024-03-01T22:00:00")
    _frame(con, kind="master_flat", sha1="mf", config_id=1, filter_canon="Ha", date_obs="2023-01-01T00:00:00")
    lid = _light_ha(con, "l1", "2024-03-01T23:00:00")
    run_calibration(con, now=NOW)

    pick = raw_flats_for(con, [lid])[lid]
    assert pick.gap == "pending" and pick.frame_ids == () and pick.profile_id is not None
    run_lineage(con, now=NOW)
    assert raw_flats_for(con, [lid]) == {}                     # light z master flatem poza wynikiem


def test_surowe_wykluczone_wycofany_zastapiony_bez_kopii(con):
    """Kandydat musi być aktywny i mieć OBECNĄ kopię - inaczej wydanie zlinkowałoby plik, którego
    nie ma, albo klatkę, którą ręka wycofała. Sam taki profil daje `no_raw` (przepis jest, surowych
    nie ma); dopiero żywy flat zostaje wybrany - sam, bez wykluczonych z tej samej nocy."""
    from horreum.lineage import raw_flats_for
    wycofany = _surowy(con, "wycofany", "2024-03-01T22:00:00")
    zastapiony = _surowy(con, "zastapiony", "2024-03-01T22:01:00")
    _surowy(con, "zniknal", "2024-03-01T22:02:00", present=False)
    lid = _light_ha(con, "l1", "2024-03-01T23:00:00")
    con.execute("UPDATE frame SET retired_at = ? WHERE id = ?", (NOW, wycofany))
    con.execute("UPDATE frame SET superseded_by = ? WHERE id = ?", (wycofany, zastapiony))
    con.commit()
    run_calibration(con, now=NOW)

    pick = raw_flats_for(con, [lid])[lid]
    assert (pick.gap, pick.frame_ids) == ("no_raw", ()) and pick.profile_id is not None
    zywy = _surowy(con, "zywy", "2024-03-01T22:03:00")
    run_calibration(con, now=NOW)
    assert raw_flats_for(con, [lid])[lid].frame_ids == (zywy,)


def test_surowe_light_bez_czasu_i_klatka_nie_light(con):
    """Light bez `date_obs` nie zna nocy - `no_time`, nie zgadywana sesja. Klatka, która nie jest
    lightem, w wyniku się nie pojawia (pytanie „czym skalibrować" ma treść tylko dla nieba)."""
    from horreum.lineage import raw_flats_for
    f = _surowy(con, "f_ha", "2024-03-01T22:00:00")
    lid = _light_ha(con, "l1", None)
    run_calibration(con, now=NOW)

    out = raw_flats_for(con, [lid, f])
    assert set(out) == {lid} and out[lid].gap == "no_time" and out[lid].frame_ids == ()
    assert (out[lid].night, out[lid].days_apart) == (None, None) and out[lid].profile_id is not None


def test_surowy_flat_bez_czasu_nie_kandyduje(con):
    """Flat bez nocy nie wchodzi do wyboru - ani jako „ta sama noc", ani jako jedyny kandydat profilu
    (wtedy `no_raw`, nie wybór bez sesji). Brak nocy to brak `date_obs` ORAZ napis, którego SQLite nie
    rozpozna jako czasu (`date()` → NULL): samo `IS NOT NULL` przepuściłoby taki flat do arytmetyki
    dni i jeden śmieć w archiwum wywracałby gotowość wszystkich teczek. Flat z czasem obok - wybrany sam."""
    from horreum.lineage import raw_flats_for
    bez_czasu = _surowy(con, "f_bez", None)
    smiec = _surowy(con, "f_smiec", "nieznany")
    lid = _light_ha(con, "l1", "2024-03-01T23:00:00")
    run_calibration(con, now=NOW)
    assert raw_flats_for(con, [lid])[lid].gap == "no_raw"

    z_czasem = _surowy(con, "f_z", "2024-03-02T05:30:00")
    run_calibration(con, now=NOW)
    pick = raw_flats_for(con, [lid])[lid]
    assert pick.frame_ids == (z_czasem,) and not {bez_czasu, smiec} & set(pick.frame_ids)


def test_surowe_koszt_staly_w_liczbie_zapytan(con):
    """Koszt nie rośnie z liczbą lightów: tyle samo zapytań dla jednego lightu co dla pięciu
    (kandydaci jednym zapytaniem po zbiorze profili, nie zapytanie na light)."""
    from horreum.lineage import raw_flats_for
    _surowy(con, "f_ha", "2024-03-01T22:00:00")
    _surowy(con, "f_oiii", "2024-03-01T22:00:00", filter_canon="OIII")
    lights = [_light_ha(con, f"l{i}", "2024-03-01T23:00:00") for i in range(4)]
    lights.append(_frame(con, kind="light", sha1="l_oiii", config_id=1, filter_canon="OIII",
                         date_obs="2024-03-01T23:00:00"))
    run_calibration(con, now=NOW)

    def _ile(ids):
        n = []
        con.set_trace_callback(lambda s: n.append(s) if s.lstrip().upper().startswith("SELECT") else None)
        try:
            out = raw_flats_for(con, ids)
        finally:
            con.set_trace_callback(None)
        assert all(p.frame_ids for p in out.values())
        return len(n)

    assert _ile(lights[:1]) == _ile(lights)
