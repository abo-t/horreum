"""View-model ekranu planera (T5b, `horreum.gui.planner_model`) — CZYSTA prezentacja, BEZ Qt
(plik nie importuje PySide6 → wlicza się do pełnego `pytest` bez `[gui]`).

Pilnuje tego, co przy ekranie łatwo zgubić: chip zestawu jest SOCZEWKĄ (nic nie znika, rada liczy
się dla wybranego sprzętu TĄ SAMĄ funkcją co rdzeń), porządek listy należy do rdzenia, a predykat
„Pokaż klatki celu" pada na pokryciu — bo pusty filtr pokazałby gridowi CAŁĄ bazę.
"""
from datetime import date

import pytest

from horreum import repo, targets
from horreum.gui import planner_model as pm
from horreum.gui import queries
# Baza T4 (trzy zestawy o różnych ogniskowych + stanowisko) REUŻYTA, nie skopiowana — drugi taki
# builder rozjechałby się z pierwszym przy najbliższej zmianie schematu (SPOT).
from test_target_plan import _light, _park_ready, con    # noqa: F401

NOW = "2026-07-31T12:00:00+00:00"


@pytest.fixture
def res(con):
    """Plan nocy na fixture T4 — wejście wszystkich testów prezentacji."""
    _park_ready(con)
    return targets.plan(con, night=date(2026, 8, 15), limit=None)


# ─────────────────────────────────────────────────────────── chip = soczewka, nie filtr

def test_chip_niczego_nie_ukrywa_i_nie_przestawia(res):
    """D-0731-13: chip zmienia SPOJRZENIE, nie zbiór. Zmierzone na kopii żywej pf4: `framing`
    ma wpis dla KAŻDEGO zestawu w KAŻDYM wierszu, więc „filtr po obecności w framing" nie wyciąłby
    nic — a ukrywanie wierszy łamałoby regułę „wyceniaj, nie wycinaj"."""
    base = pm.view_rows(res)
    for telescope in pm.rig_choices(res):
        lensed = pm.view_rows(res, telescope)
        assert len(lensed) == len(base)
        assert [v.canon for v in lensed] == [v.canon for v in base]      # porządek = rdzeń


def test_porzadek_ekranu_to_klucz_rdzenia_z_kubelkiem_kadru(res):
    """PL-1 R2: ekran (porządek rady) i `horreum plan` mają JEDEN klucz - `targets._sort_key`
    z kubełkiem kadru `best_rig`. Widok oddaje wiersze rdzenia bez przestawiania, także pod chipem
    (soczewka kubełka nie przelicza), a w obrębie tej samej widoczności i luki kubełek nie maleje."""
    core = [r.target.canon for r in res.rows]
    for telescope in (None,) + pm.rig_choices(res):
        assert [v.canon for v in pm.view_rows(res, telescope)] == core
    keys = [targets._sort_key(r) for r in res.rows]
    assert keys == sorted(keys)
    buckets = {targets._fill_bucket(r.framing_in(r.best_rig)) for r in res.rows}
    assert len(buckets) > 1, "fixture z jednym kubełkiem - test straciłby sens"


def test_chipy_ida_w_porzadku_zestawow_po_lightach(res):
    """Kontrakt T4 §8a pkt 3: ekran pokazuje park w porządku SPRZĘTU, nie alfabetu."""
    assert pm.rig_choices(res) == tuple(r.telescope for r in res.rigs)
    lights = [r.lights for r in res.rigs]
    assert lights == sorted(lights, reverse=True)


def test_soczewka_liczy_kadr_wybranego_zestawu(res):
    """Kolumna „zestaw" pod chipem opisuje WYBRANY sprzęt, nie najlepsze dopasowanie."""
    for telescope in pm.rig_choices(res):
        for v in pm.view_rows(res, telescope):
            assert v.rig.startswith(telescope)


def test_soczewka_rady_to_ta_sama_funkcja_co_rdzen(res):
    """SPOT: rada pod chipem MUSI być `targets.recommend_channel`, nie drugą derywacją — inaczej
    ekran i CLI potrafiłyby doradzić co innego dla tego samego zestawu."""
    telescope = pm.rig_choices(res)[-1]
    rig = next(r for r in res.rigs if r.telescope == telescope)
    for row in res.rows:
        channel, reason = pm.recommendation(row, rig)
        assert (channel, reason) == targets.recommend_channel(row.coverage, row.cost, rig)


def test_soczewka_domyslna_oddaje_wynik_rdzenia(res):
    """Bez chipa nie liczymy niczego drugi raz — bierzemy gotowe pola `TargetRow`."""
    for row, v in zip(res.rows, pm.view_rows(res)):
        assert pm.recommendation(row, row.best_rig) == (row.recommend, row.recommend_reason)
        assert v.recommend == pm.recommend_text(row.recommend, row.recommend_reason)


# ─────────────────────────────────────────────────────────── komórki: brak faktu jest widoczny

def test_powod_braku_rady_zamiast_pustej_komorki():
    assert pm.recommend_text("Ha", None) == "Ha"
    assert pm.recommend_text(None, "no_gap") == "bez luk"
    assert pm.recommend_text(None, "rig_cannot") == "zestaw nie umie"
    assert pm.recommend_text(None, "no_rig") == "brak zestawu"
    assert pm.recommend_text(None, None) == "brak zestawu"       # None nie wysadza lookupu


def test_kadrowanie_i_brak_zestawu(res):
    row = res.rows[0]
    rig = res.rigs[0]
    assert pm.rig_text(rig, row.framing_in(rig)).startswith(rig.telescope)
    assert pm.rig_text(None, None) == "—"                        # kreska, nie pustka


def test_pokrycie_mowi_o_braku_klatek(res):
    """Cel nigdy nie fotografowany dostaje JAWNE „bez klatek" — pusta komórka czytałaby się
    jak „nie policzyłem"."""
    bez = [r for r in res.rows if not r.coverage.archive_canons]
    assert bez, "fixture bez celów niesfotografowanych — test straciłby sens"
    assert pm.coverage_text(bez[0]) == "bez klatek"


def _cov(**kw):
    base = dict(hours_by_filter={"Ha": 4.0}, hours_by_channel={"RGB": 0.0, "Ha": 4.0},
                gaps=("RGB",), archive_canons=("CTB1",), frames_no_exptime=0)
    return targets.Coverage(**{**base, **kw})


class _Row:
    """Wiersz-atrapa dla samej prezentacji pokrycia (I-2e) — testy niżej pytają o TEKST, nie
    o rachunek nieba, więc pełny `plan()` byłby drogą okrężną do tej samej asercji."""

    def __init__(self, coverage):
        self.coverage = coverage
        self.target = targets.Target(canon="CTB1", type="SNR", ra_deg=0.0, dec_deg=60.0,
                                     major_arcmin=100.0, minor_arcmin=None, mag=None,
                                     mag_from_b=False, aliases=(), layer="core", why=None,
                                     size_source=None)


def test_pokrycie_niesie_godziny_w_obrazach_gdy_stosy_sa(res):
    """I-2e: „w obrazach" to DRUGA liczba obok zebranych. Milczy, gdy stosów nie ma — zero przy
    każdym celu nigdy nie stackowanym byłoby szumem w najszerszej kolumnie tabeli."""
    assert "w obrazach" not in pm.coverage_text(_Row(_cov()))
    tekst = pm.coverage_text(_Row(_cov(integrated_by_filter={"Ha": 1.5},
                                       integrated_by_channel={"Ha": 1.5},
                                       stacks=((7, r"R:\ASTRO_\CTB1\m.xisf"),))))
    assert "Ha 4.0 h" in tekst and "w obrazach 1.5 h" in tekst


def test_tooltip_pokrycia_mowi_gdzie_lezy_obraz(res):
    """Druga połowa mostu: liczba godzin bez odpowiedzi „gdzie to jest" zostawia użytkownika
    z wyprawą do eksploratora. Ścieżki idą do TOOLTIPA — kolumna z nimi rozjechałaby tabelę,
    której podłogę szerokości Zdzin ustalił świadomie (D-0801-1)."""
    assert pm.coverage_tip(_Row(_cov())) == ""                      # bez stosów: cisza
    tip = pm.coverage_tip(_Row(_cov(integrated_by_filter={"Ha": 1.5},
                                    integrated_by_channel={"Ha": 1.5},
                                    stacks=((7, r"R:\ASTRO_\CTB1\m.xisf"), (9, None)))))
    assert r"R:\ASTRO_\CTB1\m.xisf" in tip
    # Obraz bez obecnej kopii NIE MILCZY: „mam go, ale nie pod ręką" to inna odpowiedź niż „nie ma"
    assert "(brak kopii pod ręką)" in tip
    assert "Zintegrowane: Ha 1.5 h" in tip


def test_plan_pusty_to_kreska_a_status_ma_etykiete(con, res):
    assert pm.plan_text(res.rows[0]) == "—"
    canon = res.rows[0].target.canon
    repo.set_target_plan(con, canon=canon, status="planned", priority=2, now=NOW)
    row = next(r for r in targets.plan(con, night=date(2026, 8, 15), limit=None).rows
               if r.target.canon == canon)
    assert pm.plan_text(row) == "zaplanowany 2"


# ─────────────────────────────────────────────────────────── most do gridu (D-0731-7)

def test_pokaz_klatki_pada_na_celu_bez_pokrycia(res):
    """Falsyfikator decyzji: cel bez kanonów archiwum MUSI mieć przycisk nieaktywny — pusty filtr
    pokazałby w gridzie PEŁNĄ bazę i skłamał."""
    bez = [r for r in res.rows if not r.coverage.archive_canons]
    assert not pm.can_show_frames(bez[0])


def test_object_ids_for_canons_bierze_obie_nazwy_celu(con):
    """Cel bywa w archiwum pod kilkoma kanonami naraz (`IC410` ORAZ `LBN807`) — most oddaje SUMĘ."""
    for canon in ("IC410", "LBN807", "M42"):
        repo.upsert_object(con, canon=canon, catalog="NGC", kind="deep_sky", now=NOW)
    rows = queries.object_ids_for_canons(con, ["IC410", "LBN807", "NIE-MA-TAKIEGO"])
    assert [r["canon"] for r in rows] == ["IC410", "LBN807"]     # nieznany = brak wiersza, nie błąd
    assert queries.object_ids_for_canons(con, []) == []


# ─────────────────────────────────────────────────────────── filtr kadru (PL-1, PL-2)

@pytest.fixture
def res_fill(con):
    """Plan z filtrem kadru na parku z wywołania: trzy zestawy o różnych ogniskowych."""
    _park_ready(con)
    return targets.plan(con, night=date(2026, 8, 15), limit=None,
                        park=["A140R", "RC8", "ED120R"], min_fill=0.3, max_panels=1)


def test_kolumna_wypelnienia_idzie_za_soczewka(res):
    """Kolumna „Wypełnienie" czyta `frame_fill` TEGO zestawu, którym patrzy soczewka."""
    for telescope in (None,) + pm.rig_choices(res):
        for row, v in zip(res.rows, pm.view_rows(res, telescope)):
            _rig, fr = pm.lens(row, res, telescope)
            assert v.fill == pm.fill_text(fr) and v.fill.endswith("%")
    assert pm.fill_text(None) == "-"


def test_bez_filtra_licznik_mowi_po_progach(res):
    assert res.rig_filter == "off"
    assert "po progach" in pm.counts_text(res) and "sprzętem" not in pm.counts_text(res)


def test_filtr_kadru_zmienia_napis_licznika_i_mowi_ile_schowal(res_fill):
    """Rozstrzygnięcie ④: liczba zmienia znaczenie, więc napis idzie razem z nią, a obok stoi
    liczba schowanych (odmieniona), żeby odsiew nie wyglądał jak ubogi katalog."""
    text = pm.counts_text(res_fill)
    assert "wykonalnych twoim sprzętem" in text and "po progach" not in text
    assert f"filtr schował {res_fill.counts['hidden_by_rig']} cel" in text
    assert "wypełnienie ≥30%" in text and "maks. paneli 1" in text


def test_bez_soczewki_filtr_rdzenia_wystarcza(res_fill):
    """`best_rig` wybrany spośród zestawów spełniających próg: widok bez chipa niczego nie chowa."""
    assert len(pm.view_rows(res_fill)) == len(res_fill.rows)
    assert pm.lens_hidden(res_fill) == 0


def test_soczewka_przy_filtrze_chowa_to_czego_ten_zestaw_nie_spelnia(res_fill):
    """„Zestaw z soczewki": chip RC8 pokazuje WYŁĄCZNIE cele, które RC8 robi w progu; liczba
    schowanych trafia do noty nagłówka. Predykat ten sam co w rdzeniu (`targets.rig_fits`)."""
    hidden = {t: pm.lens_hidden(res_fill, t) for t in pm.rig_choices(res_fill)}
    assert any(hidden.values()), "fixture bez różnicy między zestawami - test straciłby sens"
    for telescope, n in hidden.items():
        shown = pm.view_rows(res_fill, telescope)
        assert len(shown) == len(res_fill.rows) - n
        for v in shown:
            _rig, fr = pm.lens(v.source, res_fill, telescope)
            assert targets.rig_fits(fr, min_fill=0.3, max_panels=1)
        notes = " | ".join(t for _l, t in pm.header_notes(res_fill, telescope))
        assert (f"Soczewka {telescope}" in notes) == bool(n)


def test_filtr_bez_parku_ostrzega_zamiast_milczec(con):
    """Rozstrzygnięcie ③ na ekranie: poproszony filtr przy nieustawionym parku jest JAWNIE
    wyłączony (`warn`), a nie cicho nieczynny."""
    _park_ready(con)
    res = targets.plan(con, night=date(2026, 8, 15), limit=None, min_fill=0.3)
    notes = [(lvl, t) for lvl, t in pm.header_notes(res) if "Filtr kadru" in t]
    assert notes and notes[0][0] == "warn" and "park nieustawiony" in notes[0][1]
    assert "po progach" in pm.counts_text(res)


def test_licznik_przy_soczewce_mowi_ile_widac(res_fill):
    """Licznik opisuje EKRAN: przy soczewce, która chowa, obok liczby wierszy wyniku stoi liczba
    wierszy na liście („w soczewce RC8: 99"); bez chowania napis ten sam co bez soczewki."""
    base = pm.counts_text(res_fill)
    assert f"(wierszy: {res_fill.counts['rows']})" in base
    hiding = [n for n in pm.rig_choices(res_fill) if pm.lens_hidden(res_fill, n)]
    assert hiding, "fixture bez soczewki, która chowa - test straciłby sens"
    for name in pm.rig_choices(res_fill):
        text = pm.counts_text(res_fill, name)
        if name in hiding:
            shown = len(pm.view_rows(res_fill, name))
            assert shown < res_fill.counts["rows"]
            assert f"(wierszy: {res_fill.counts['rows']}; w soczewce {name}: {shown})" in text
        else:
            assert text == base


def test_mozaika_w_kolumnie_wypelnienia_jest_oznaczona(res):
    """Mozaika ma 100% z definicji (`sky.Framing.frame_fill`), jak cel idealnie wypełniający jeden
    kadr - widok niesie znacznik, żeby te dwie setki nie czytały się jednakowo. Miara bez zmian."""
    seen = set()
    for row, v in zip(res.rows, pm.view_rows(res)):
        _rig, fr = pm.lens(row, res)
        assert v.fill_mosaic == (fr is not None and fr.panels > 1)
        if v.fill_mosaic:
            assert v.fill == "100%"
        seen.add(v.fill_mosaic)
    assert seen == {True, False}


@pytest.mark.parametrize("mm, mc", [(4, 2), (2, 4)])
def test_dwie_kamery_na_jednej_optyce_to_dwa_chipy_i_dwa_kadry(con, mm, mc):
    """A140R z ASI2600MM (784 mm) i z ASI2600MC za reduktorem (400 mm) to DWA zestawy. Chipy mają
    dwie różne nazwy (z kamerą), soczewka każdego czyta kadr SWOJEGO zestawu, a „najlepsze
    dopasowanie" przy filtrze niczego nie chowa - rdzeń wybrał zestaw spełniający próg, więc
    i jego kadr go spełnia. Liczba lightów odwraca kolejność zestawów; wynik od niej nie zależy."""
    con.execute("INSERT INTO config(telescope_id, camera_id, status, created_at) "
                "VALUES (1, 2, 'proposed', ?)", (NOW,))
    mc_cfg = con.execute("SELECT id FROM config WHERE telescope_id = 1 AND camera_id = 2"
                         ).fetchone()["id"]
    for i in range(mm):
        _light(con, config_id=1, sha1=f"m{i}", focal=784.0)
    for i in range(mc):
        _light(con, config_id=mc_cfg, sha1=f"k{i}", focal=400.0, camera_id=2)
    con.commit()
    res = targets.plan(con, night=date(2026, 8, 15), limit=None, park=["A140R"], min_fill=0.3,
                       max_panels=1)
    names = pm.rig_choices(res)
    assert sorted(names) == ["A140R (ASI2600MC)", "A140R (ASI2600MM)"]
    assert res.rows and len(pm.view_rows(res)) == len(res.rows) and pm.lens_hidden(res) == 0
    for name in names:
        rig = next(r for r in res.rigs if r.name == name)
        for row in res.rows:
            got, fr = pm.lens(row, res, name)
            assert got is rig and fr is row.framing_in(rig)
        assert all(v.rig.startswith(name + " · ") for v in pm.view_rows(res, name))


# ─────────────────────────────────────────────────────────── nagłówek nocy i noty

def test_noty_naglowka_krzycza_o_nieustawionym_parku(res):
    notes = dict((text, level) for level, text in pm.header_notes(res))
    assert any("Park NIEUSTAWIONY" in t for t in notes), notes
    assert notes[next(t for t in notes if "Park NIEUSTAWIONY" in t)] == "warn"


def test_noty_naglowka_nazywaja_park_z_bazy(con):
    _park_ready(con)
    repo.set_telescope_park(con, telescope_id=1, in_park=1, now=NOW)
    res = targets.plan(con, night=date(2026, 8, 15), limit=None)
    levels = [lvl for lvl, _t in pm.header_notes(res)]
    texts = " | ".join(t for _l, t in pm.header_notes(res))
    assert "A140R" in texts and "warn" not in levels[:1]


def test_naglowek_powstaje_z_wyniku_a_nie_z_pierwszego_wiersza(con):
    """Przy pustej liście nagłówek nadal ma z czego powstać — dlatego bierze `PlanResult`."""
    _park_ready(con)
    res = targets.plan(con, night=date(2026, 8, 15), find="NIE-ISTNIEJE", limit=None)
    assert res.rows == ()
    assert "2026-08-15" in pm.night_text(res)
    assert "Będargowo" in pm.night_text(res)
    assert pm.counts_text(res).startswith("Cele:")


def test_park_overview_ten_sam_material_co_cli(con):
    """SPOT: literał parku ma JEDNEGO właściciela — dialog ekranu i CLI liczą lighty tak samo."""
    _park_ready(con)
    repo.set_telescope_park(con, telescope_id=2, in_park=1, now=NOW)
    rows = queries.park_overview(con)
    by_canon = {r["telescop_canon"]: r for r in rows}
    assert by_canon["RC8"]["in_park"] == 1 and by_canon["A140R"]["in_park"] is None
    assert by_canon["A140R"]["lights"] == 4
    assert [r["lights"] for r in rows] == sorted((r["lights"] for r in rows), reverse=True)
