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
from test_target_plan import _park_ready, con    # noqa: F401

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
    assert pm.rig_text(rig, row.framing[rig.telescope]).startswith(rig.telescope)
    assert pm.rig_text(None, None) == "—"                        # kreska, nie pustka


def test_pokrycie_mowi_o_braku_klatek(res):
    """Cel nigdy nie fotografowany dostaje JAWNE „bez klatek" — pusta komórka czytałaby się
    jak „nie policzyłem"."""
    bez = [r for r in res.rows if not r.coverage.archive_canons]
    assert bez, "fixture bez celów niesfotografowanych — test straciłby sens"
    assert pm.coverage_text(bez[0]) == "bez klatek"


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
    by_canon = {r["canon"]: r for r in rows}
    assert by_canon["RC8"]["in_park"] == 1 and by_canon["A140R"]["in_park"] is None
    assert by_canon["A140R"]["lights"] == 4
    assert [r["lights"] for r in rows] == sorted((r["lights"] for r in rows), reverse=True)
