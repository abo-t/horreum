"""View-model ekranu planera (T5b, `horreum.gui.planner_model`) — CZYSTA prezentacja, BEZ Qt
(plik nie importuje PySide6 → wlicza się do pełnego `pytest` bez `[gui]`).

Pilnuje tego, co przy ekranie łatwo zgubić: chip zestawu jest SOCZEWKĄ (nic nie znika, rada liczy
się dla wybranego sprzętu TĄ SAMĄ funkcją co rdzeń), porządek listy należy do rdzenia, a predykat
„Pokaż klatki celu" pada na pokryciu — bo pusty filtr pokazałby gridowi CAŁĄ bazę.
"""
from dataclasses import replace
from datetime import date

import pytest

from horreum import repo, targets
from horreum.gui import planner_model as pm
from horreum.gui import i18n, queries
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

def test_chip_niczego_nie_ukrywa(res):
    """D-0731-13: chip zmienia SPOJRZENIE, nie zbiór. Zmierzone na kopii żywej pf4: `framing`
    ma wpis dla KAŻDEGO zestawu w KAŻDYM wierszu, więc „filtr po obecności w framing" nie wyciąłby
    nic - a ukrywanie wierszy łamałoby regułę „wyceniaj, nie wycinaj". Porządek pod chipem pilnuje
    `test_chip_liczy_kubelek_kadru_dla_soczewki` (PL-3 (1))."""
    base = sorted(v.canon for v in pm.view_rows(res))
    for telescope in pm.rig_choices(res):
        assert sorted(v.canon for v in pm.view_rows(res, telescope)) == base


def test_porzadek_ekranu_to_klucz_rdzenia_z_kubelkiem_kadru(res):
    """PL-1 R2: ekran (porządek rady) i `horreum plan` mają JEDEN klucz - `targets._sort_key`
    z kubełkiem kadru `best_rig`. Bez chipa widok oddaje wiersze rdzenia bez przestawiania, a w obrębie
    tej samej widoczności i luki kubełek nie maleje."""
    core = [r.target.canon for r in res.rows]
    assert [v.canon for v in pm.view_rows(res)] == core
    keys = [targets._sort_key(r) for r in res.rows]
    assert keys == sorted(keys)
    buckets = {targets._fill_bucket(r.framing_in(r.best_rig)) for r in res.rows}
    assert len(buckets) > 1, "fixture z jednym kubełkiem - test straciłby sens"


def test_chip_liczy_kubelek_kadru_dla_soczewki(res):
    """PL-3 (1), O1: pod chipem zestawu porządek rady liczy kubełek kadru dla SOCZEWKI (ta sama
    `targets._fill_bucket`), nie dla `best_rig` - inaczej cel dobry na innym zestawie stał wysoko
    z małym „Wypełn." w komórce. Widoczność i luka zostają przed kubełkiem (cel pod horyzontem nie
    przeskakuje widocznego), a remis w kubełku trzyma kolejność rdzenia (sort stabilny)."""
    core_pos = {r.target.canon: i for i, r in enumerate(res.rows)}
    moved = 0
    for telescope in pm.rig_choices(res):
        rows = pm.view_rows(res, telescope)
        keys = []
        for v in rows:
            _rig, fr = pm.lens(v.source, res, telescope)
            # Człony przed kubełkiem z JAWNYCH pól, nie z wycinka `_sort_key` - nowy człon wstawiony
            # do klucza rdzenia przed kubełek przewraca ten test zamiast cicho przesunąć widok.
            keys.append((not v.source.window.visible, 0 if v.source.coverage.gaps else 1,
                         targets._fill_bucket(fr), core_pos[v.canon]))
        assert keys == sorted(keys)
        moved += [v.canon for v in rows] != [r.target.canon for r in res.rows]
    assert moved, "fixture bez rozjazdu soczewki i best_rig - test straciłby sens"


def test_chip_bez_kadrowania_zostawia_porzadek_rdzenia(res):
    """Soczewka bez kadrowania dla żadnego celu (zestaw spoza wyniku) daje kubełek 3 wszędzie - remis
    całej listy, więc sort wtórny oddaje porządek rdzenia bit w bit, nie przypadkową permutację."""
    assert [v.canon for v in pm.view_rows(res, "brak-takiego")] == \
        [r.target.canon for r in res.rows]


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
        for v in pm.view_rows(res, telescope):
            _rig, fr = pm.lens(v.source, res, telescope)
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


# ─────────────────────────────────────────────────────────── szukajka po kanonie (AR-146)

def _stara_regula(pool, needle):
    """Reguła szukajki sprzed AR-146 (goły podciąg bez wielkości liter) - wzorzec „nic, co trafiało,
    nie przestaje trafiać"."""
    igla = needle.casefold()
    return {t.canon for t in pool
            if igla in t.canon.casefold() or any(igla in a.casefold() for a in t.aliases)}


def _trafione(pool, needle):
    exact, rest = targets.find_matches(pool, needle)
    return [t.canon for t in exact], {t.canon for t in exact + rest}


def test_szukajka_trafia_po_kanonie_katalogowym():
    """Wizytacja W4: „M27” i „Arp 244” trafiały, „M 27”, „Arp244” dawały 0 - filtr porównywał
    surowy podciąg. Każdy zapis tego samego oznaczenia trafia ten sam rekord, DOKŁADNIE."""
    pool = targets.load_targets(targets.ALL_LAYERS)
    for zapis in ("M27", "M 27", "m27", "Messier 27"):
        assert _trafione(pool, zapis)[0] == ["NGC6853"], zapis
    for zapis in ("Arp 244", "Arp244", "arp 244"):
        assert _trafione(pool, zapis)[0] == ["NGC4038"], zapis
    assert _trafione(pool, "ngc 7000")[0] == ["NGC7000"]


def test_szukajka_nie_gubi_niczego_co_trafiala():
    """Podciąg zostaje BIT W BIT pod kanonem: nazwy własne, ukryte nazwy `PN G`, region, przykłady
    z testów planera."""
    pool = targets.load_targets(targets.ALL_LAYERS)
    for igla in ("NGC7000", "CTB1", "IC410", "NGC6960", "PN G", "Veil", "Eagle Nebula",
                 "Eastern Veil", "C4", "x", "M27", "Arp 244"):
        stare = _stara_regula(pool, igla)
        assert stare, igla
        assert stare <= _trafione(pool, igla)[1], igla


def test_szukajka_dokladne_przed_podciagiem(con):
    """`sh2 13` to kanon `Sh2-13` i prefiks `Sh2-131`... - trafienie dokładne stoi na liście
    pierwsze w porządku rady i pod każdą soczewką, mimo że klucz rady ustawiłby je inaczej."""
    _park_ready(con)
    res = targets.plan(con, night=date(2026, 8, 15), find="sh2 13", limit=None)
    assert res.find_exact == frozenset({"Sh2-13"}) and len(res.rows) > 1
    po_radzie = sorted(res.rows, key=targets._sort_key)
    assert po_radzie[0].target.canon != "Sh2-13", "fixture bez przestawienia - test bez sensu"
    assert res.rows[0].target.canon == "Sh2-13"
    for order in (pm.ORDER_CORE, pm.ORDER_LENS):
        for rig in (None,) + pm.rig_choices(res):
            assert pm.view_rows(res, rig, order=order)[0].canon == "Sh2-13", (order, rig)


def test_pusty_wynik_dla_nazwy_znanej_spoza_puli(con):
    """„M13” dawało pusty stan „nie znam celu”, choć NGC6205 (gromada kulista) jest znany - asset
    planera świadomie go nie bierze. Zdanie mówi, czym jest wpisana nazwa; typu dla obiektu spoza
    assetu nie ma skąd wziąć, więc go nie zmyślamy."""
    _park_ready(con)

    def zdanie(igla, layers=targets.DEFAULT_LAYERS):
        res = targets.plan(con, night=date(2026, 8, 15), find=igla, layers=layers, limit=None)
        assert res.rows == ()
        return pm.empty_find_text(res, igla)

    assert zdanie("M 13") == "„M 13” = NGC6205, poza celami planera."
    assert zdanie("NGC6205") == "„NGC6205”, poza celami planera."     # wpisane = kanon - bez „=”
    assert zdanie("LMC") == "„LMC”, poza celami planera."             # rekord-nazwa
    # Cel warstwy niewczytanej (cirrus przy domyślnym rdzeniu) NIE jest „poza celami planera".
    assert zdanie("ldn 1235") == ("„ldn 1235” (DrkN) - cel spoza wczytanych warstw: "
                                  "zaznacz „Pokaż cirrus (LBN/LDN)”, żeby go zobaczyć.")
    assert zdanie("LDN 134").startswith("„LDN 134” = LBN10 (EmN) - cel spoza wczytanych warstw")
    assert zdanie("NGC99999").startswith("Nie znam celu „NGC99999”")  # sam kształt to nie wiedza
    assert zdanie("zzqq").startswith("Nie znam celu „zzqq”")
    i18n.set_lang("en")
    assert zdanie("M 13") == "“M 13” = NGC6205, not among the planner targets."


def test_pusty_wynik_gdy_cel_chowa_filtr_statusu_nie_mowi_nie_znam(con):
    """`find` przebija `skip`, ale nie jawny filtr statusu: NGC7000 bez oznaczenia przy statusie
    „planned" daje pustą listę - cel JEST, więc „nie znam celu" byłoby nieprawdą."""
    _park_ready(con)
    res = targets.plan(con, night=date(2026, 8, 15), find="NGC 7000", status="planned",
                       limit=None)
    assert res.rows == () and res.counts["feasible"] == 1 and res.find_outside is None
    # Zdanie nie zgaduje, KTÓRY filtr chowa (wołanie z `only_gaps`/`only_new` też tu trafia).
    assert pm.empty_find_text(res, "NGC 7000") == (
        "„NGC 7000” trafia 1 cel, ale chowają go bieżące filtry.")
    gaps = targets.plan(con, night=date(2026, 8, 15), find="NGC 7000", only_new=True, limit=None)
    if gaps.rows == ():
        assert "bieżące filtry" in pm.empty_find_text(gaps, "NGC 7000")
    i18n.set_lang("en")
    assert pm.empty_find_text(res, "NGC 7000") == (
        "“NGC 7000” matches 1 target, but the current filters hide it.")


@pytest.mark.parametrize("nazwa, kanon", [("Heart Nebula", "IC1805"), ("Soul Nebula", "IC1848"),
                                          ("Elephant's Trunk Nebula", "Sh2-131")])
def test_nazwa_potoczna_resolvera_trafia_dokladnie(con, nazwa, kanon):
    """Nazwy potoczne osi obiektu (`resolve.objects`), których asset nie nosi jako aliasu, dawały
    pustą listę i zdanie „poza celami planera" o celu, który JEST w rdzeniu. Szukajka bierze klucz
    z resolvera - trafienie dokładne."""
    _park_ready(con)
    res = targets.plan(con, night=date(2026, 8, 15), find=nazwa, limit=None)
    assert kanon in res.find_exact and res.rows[0].target.canon == kanon
    assert res.find_outside is None


def test_find_outside_dla_kanonu_z_assetu_nie_mowi_poza(con):
    """TARCZA: kanon, który jest w assecie, nigdy nie wraca jako „poza celami planera" (`target=None`)
    - z puli wołania niesie `loaded=True`, z warstwy niewczytanej - swój rekord."""
    for igla, kanon in (("M 27", "NGC6853"), ("Heart Nebula", "IC1805")):
        out = targets.find_outside(igla)
        assert out.target is not None and out.target.canon == kanon and out.loaded is True
    cirrus = targets.find_outside("LDN 134")
    assert cirrus.target.canon == "LBN10" and cirrus.loaded is False
    assert targets.find_outside("M 13").target is None                 # gromady w assecie nie ma
    # Zdanie dla rekordu z puli nie mówi „poza" (plan go tak nie poda, ale funkcja jest wspólna).
    _park_ready(con)
    pusty = targets.plan(con, night=date(2026, 8, 15), find="zzqq", limit=None)
    zdanie = pm.empty_find_text(replace(pusty, find_outside=targets.find_outside("M 27")), "M 27")
    assert "poza" not in zdanie and "bieżące filtry" in zdanie


def test_warstwa_bez_przelacznika_nie_wybucha(con):
    """Wołanie z innym zestawem warstw niż ekran (`layers=("cirrus",)`): cel rdzenia dostaje
    zdanie z nazwą warstwy zamiast `KeyError`."""
    _park_ready(con)
    res = targets.plan(con, night=date(2026, 8, 15), find="NGC 7000", layers=("cirrus",),
                       limit=None)
    assert res.rows == () and res.find_outside.target.layer == "core"
    assert pm.empty_find_text(res, "NGC 7000") == (
        "„NGC 7000” (HII) - cel spoza wczytanych warstw: zaznacz „core”, żeby go zobaczyć.")


# ─────────────────────────────────── przełącznik kandydatek i mimik PN (decyzja Zdzinia Q14)

def test_przelacznik_pn_chowa_kandydatki_i_mimiki_zostawia_potwierdzone(con, res):
    """Domyślnie wyłączony - odpowiedź bit w bit ta sama (bez klucza `hidden_by_pn`). Włączony
    chowa `candidate` i `mimic` z licznikiem w nocie; `confirmed` i cele bez statusu zostają."""
    assert res.pn_filter == "off" and "hidden_by_pn" not in res.counts
    po_statusie = {}
    for r in res.rows:
        po_statusie.setdefault(r.target.status, set()).add(r.target.canon)
    assert {"candidate", "mimic", "confirmed", None} <= set(po_statusie), po_statusie.keys()
    on = targets.plan(con, night=date(2026, 8, 15), limit=None, hide_doubtful_pn=True)
    zostaly = {r.target.canon for r in on.rows}
    assert on.pn_filter == "on"
    assert not (po_statusie["candidate"] | po_statusie["mimic"]) & zostaly
    assert po_statusie["confirmed"] | po_statusie[None] <= zostaly
    schowane = len(po_statusie["candidate"]) + len(po_statusie["mimic"])
    assert on.counts["hidden_by_pn"] == schowane == len(res.rows) - len(on.rows)
    noty = [t for _l, t in pm.header_notes(on)]
    assert f"Przełącznik PN schował {schowane} " in " | ".join(noty)


def test_przelacznik_pn_w_trybie_szukania_nieczynny(con, res):
    """Jak filtr kadru: pytanie wprost bije przełącznik (`pn_filter='find'`), kandydatka się znajduje."""
    kandydatka = next(r.target.canon for r in res.rows if r.target.status == "candidate")
    found = targets.plan(con, night=date(2026, 8, 15), limit=None, hide_doubtful_pn=True,
                         find=kandydatka)
    assert found.pn_filter == "find" and "hidden_by_pn" not in found.counts
    assert kandydatka in {r.target.canon for r in found.rows}


def test_park_overview_ten_sam_material_co_cli(con):
    """SPOT: literał parku ma JEDNEGO właściciela — dialog ekranu i CLI liczą lighty tak samo."""
    _park_ready(con)
    repo.set_telescope_park(con, telescope_id=2, in_park=1, now=NOW)
    rows = queries.park_overview(con)
    by_canon = {r["telescop_canon"]: r for r in rows}
    assert by_canon["RC8"]["in_park"] == 1 and by_canon["A140R"]["in_park"] is None
    assert by_canon["A140R"]["lights"] == 4
    assert [r["lights"] for r in rows] == sorted((r["lights"] for r in rows), reverse=True)


# ─────────────────────── AR-175: wiersz trafienia mówi alias, pudło nazwy znanej przy samym podciągu

def test_plan_find_mowi_pudlo_przy_samych_trafieniach_podciagu(con):
    """AR-175: `find_outside` liczony był wyłącznie przy pustej puli - „M 4” dawało trzy wiersze bez
    zdania, że samo M4 (NGC6121) jest poza celami. Teraz także przy samych trafieniach podciągu;
    trafienie dokładne - bez. `find_via` niesie alias wierszy trafionych nie-kanonem.
    Mutant: `find_outside` tylko przy pustej puli."""
    _park_ready(con)
    res = targets.plan(con, night=date(2026, 8, 15), find="M 4", limit=None)
    assert {r.target.canon for r in res.rows} >= {"NGC1976", "NGC1982", "NGC4472"}
    assert res.find_outside.canon == "NGC6121" and res.find_outside.target is None
    assert res.find_via["NGC1976"] == "M 42" and res.find_via["NGC4472"] == "M 49"
    dokladne = targets.plan(con, night=date(2026, 8, 15), find="M 27", limit=None)
    assert dokladne.find_outside is None and dokladne.find_via.get("NGC6853") == "M 27"


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_wiersz_trafienia_mowi_alias_i_zdanie_pudla(con, lang):
    """AR-175: kolumna „Cel” (`ViewRow.label`) mówi „NGC1976 (M 42)”, a `canon` zostaje kanonem
    (zaznaczenie, kuratela); zdanie pudła nazwy znanej - PL i EN (EN bez polskich znaków).
    Mutant: `label` = `canon`."""
    i18n.set_lang(lang)
    _park_ready(con)
    res = targets.plan(con, night=date(2026, 8, 15), find="M 4", limit=None)
    wiersze = {v.canon: v for v in pm.view_rows(res)}
    assert wiersze["NGC1976"].label == "NGC1976 (M 42)" and wiersze["NGC1976"].canon == "NGC1976"
    zdanie = pm.find_miss_text(res, "M 4")
    if lang == "pl":
        assert zdanie == ("„M 4” = NGC6121, poza celami planera - lista to cele, których nazwa "
                          "zawiera „M 4”.")
    else:
        assert zdanie == ("“M 4” = NGC6121, not among the planner targets - the list shows targets "
                          "whose name contains “M 4”.")
        assert not set(zdanie) & set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ„")
    assert pm.find_miss_text(targets.plan(con, night=date(2026, 8, 15), find="M 27", limit=None),
                             "M 27") is None


def test_zdanie_pudla_cel_warstwy_niewczytanej_przy_trafieniach_podciagu(con):
    """AR-175: „LBN 1” to cel cirrusu (warstwa niewczytana), a rdzeń ma trafienia podciągu (IC1310…) -
    zdanie pudła mówi typ i przełącznik warstwy (`planner.find_hits_layer`), nie „poza celami planera”.
    Mutant: gałąź warstwy zgubiona (zdanie „poza celami”) albo bez typu."""
    _park_ready(con)
    res = targets.plan(con, night=date(2026, 8, 15), find="LBN 1", limit=None)
    assert res.rows and res.find_outside.canon == "LBN1" and res.find_outside.target.layer == "cirrus"
    assert pm.find_miss_text(res, "LBN 1") == i18n.t(
        "planner.find_hits_layer", name=i18n.t("planner.find_self", needle="LBN 1"), type="EmN",
        layer=i18n.t("planner.layer_cirrus"), needle="LBN 1")
    assert "(EmN)" in pm.find_miss_text(res, "LBN 1")


# ─────────────── AR-375: jedna forma liczby progu · AR-385: pusta lista mówi dźwignię z liczb rdzenia

@pytest.mark.parametrize("v, miejsc, tekst", [
    (6.5, 2, "6.5"), (6.0, 2, "6"), (6.25, 2, "6.25"), (13.0, 2, "13"), (12.75, 2, "12.75"), (1.0, 2, "1"),
    (32.5, 2, "32.5"), (100.0, 2, "100"), (0.0, 2, "0"), (3.333, 2, "3.33"), (30.0, 0, "30")])
def test_tekst_progu_prawdziwa_precyzja_bez_zer_koncowych(v, miejsc, tekst):
    """AR-375 (decyzja Zdzinia: prawdziwa precyzja wpisu, „13 mag” zamiast dwóch form): tyle miejsc, ile trzyma pole
    progu, zera końcowe obcięte. Falsyfikatory: `:g` (bez sufitu precyzji pola), `.0f`/`.1f` (zaokrąglenie wpisu),
    obcięcie zer bez kropki (`30` → `3`)."""
    assert pm.tekst_progu(v, miejsc) == tekst


_LICZNIKI = {"pool": 1692, "feasible": 854, "above_horizon": 485, "matched": 0, "visible": 0, "rows": 0, "marked": 0,
             "hidden_by_status": 0}


def _pusty(res, rows=(), **pola):
    """Wynik bez wierszy z licznikami `pola` (klucze `counts`) i parametrami cięcia (`status`, `max_cost`,
    `rig_filter`) - wejście reguły zdania pustej listy bez rachunku nieba."""
    wynik = {k: pola.pop(k) for k in ("status", "max_cost", "rig_filter") if k in pola}
    return replace(res, rows=rows, counts={**_LICZNIKI, **pola}, **wynik)


def test_pusta_lista_mowi_dzwignie_z_licznikow_rdzenia(res):
    """AR-385: zdanie pustej listy wybiera krok lejka z liczb rdzenia - progi typu (filtr kadru tylko, gdy coś
    ściął), wysokość, a dalej każde cięcie z licznikiem zdaniem z liczbą, w kolejności rdzenia. Szukana nazwa, status
    i próg kosztu z WYNIKU, liczba progu formaterem tytułu. Falsyfikatory: zdanie progów przy filtrze statusu (stan sprzed
    AR-385); brak kroku wysokości; zła kolejność; koszt w drugiej formie liczby; zdanie progów jako rezerwa bez
    liczników (fałszywa dźwignia)."""
    i18n.set_lang("pl")
    progi = "Żaden cel nie przeszedł progów rozmiaru i jasności - poluzuj rozmiar albo magnitudo."
    assert pm.empty_text(_pusty(res, feasible=0, above_horizon=0)) == progi
    assert pm.empty_text(_pusty(res, feasible=0, above_horizon=0, rig_filter="on", hidden_by_rig=0)) == progi
    assert pm.empty_text(_pusty(res, feasible=0, above_horizon=0, rig_filter="on", hidden_by_rig=7)) == \
        i18n.t("planner.empty_rig")
    assert pm.empty_text(_pusty(res, feasible=22, above_horizon=0)) == \
        "22 cele po progach nie sięgają wymaganej wysokości - poluzuj próg wysokości."
    status = pm.empty_text(_pusty(res, status="done", hidden_by_status_filter=485))
    assert status == "Filtr statusu „zrobiony” schował 485 celów - wybierz „(dowolny)”."
    koszt = pm.empty_text(_pusty(res, max_cost=4.5, hidden_by_cost=2))
    assert koszt == "Próg kosztu ≤4.5 schował 2 cele - podnieś go albo wyłącz."
    razem = _pusty(res, status="planned", max_cost=3.0, hidden_by_status_filter=1, hidden_by_status=2,
                   hidden_by_pn=5, hidden_by_cost=12)
    assert pm.empty_text(razem) == " ".join((
        "Filtr statusu „zaplanowany” schował 1 cel - wybierz „(dowolny)”.",
        i18n.t("planner.hidden_by_status", n=2), i18n.t_plural("planner.pn_hidden", 5),
        "Próg kosztu ≤3 schował 12 celów - podnieś go albo wyłącz."))
    # Lista widoku pusta przy wierszach wyniku = soczewka filtra kadru; bez liczników (`only_gaps` spoza ekranu) - zdanie
    # neutralne, bez dźwigni, której wynik nie zna; tryb szukania - nazwa z WYNIKU (`PlanResult.find`).
    assert pm.empty_text(_pusty(res, rows=res.rows[:1], rig_filter="on")) == i18n.t("planner.empty_rig")
    assert pm.empty_text(_pusty(res)) == "Żaden cel nie przeszedł bieżących filtrów."
    assert pm.empty_text(replace(res, find="NGC 7000")) == pm.empty_find_text(res, "NGC 7000")
    i18n.set_lang("en")
    assert pm.empty_text(_pusty(res, status="done", hidden_by_status_filter=1)) == \
        "The status filter “done” hid 1 target - choose “(any)”."


@pytest.mark.parametrize("n, cele", [(1, "cel"), (2, "cele"), (5, "celów"), (12, "celów"), (22, "cele")])
def test_pusta_lista_odmiana_liczebnika(res, n, cele):
    """Odmiana przez katalog (`t_plural`): 1 · 2-4 · 5 · 12-14 · 22 - zdanie statusu i kosztu."""
    i18n.set_lang("pl")
    assert f"schował {n} {cele} -" in pm.empty_text(_pusty(res, status="skip", hidden_by_status_filter=n))
    assert f"schował {n} {cele} -" in pm.empty_text(_pusty(res, max_cost=2.0, hidden_by_cost=n))


def test_pusta_lista_przy_filtrze_statusu_z_prawdziwego_rachunku(con):
    """AR-385 na prawdziwym rdzeniu: filtr „zrobiony” bez oznaczeń (stan bazy Zdzinia: 0 oznaczeń `done`) daje pustą
    listę, a zdanie nazywa status i liczbę celów, które schował - wszystkie nad horyzontem."""
    _park_ready(con)
    res = targets.plan(con, night=date(2026, 8, 15), status="done", limit=None)
    assert res.rows == () and res.counts["hidden_by_status_filter"] == res.counts["above_horizon"] > 0
    assert pm.empty_text(res) == i18n.t_plural("planner.empty_by_status", res.counts["above_horizon"],
                                               status="zrobiony", any="(dowolny)")
