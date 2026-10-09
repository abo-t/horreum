"""Parser i rozwiązanie zapytania Znajdź (`horreum.gui.flows.znajdz`) - BEZ Qt i bez bazy: słownik
archiwum to dane (`FindCatalog`), więc każdy token, oba języki prefiksów, cudzysłowy, OR/AND, fraza
→ obiekt przez alias i nazwę potoczną, fraza bez trafień → uwagi i `unmatched` sprawdzamy na
wartościach. Jeden test na końcu składa słownik z prawdziwej bazy (`catalog_from_db`)."""
import pytest

from horreum.gui.flows import znajdz as z

KAT = z.FindCatalog(
    objects=((1, "M42"), (2, "LMC"), (3, "Sh2-131"), (4, "NGC7000"), (5, "IC1396")),
    filters=("Ha", "OIII", "L-Pro", "SII"),
    telescopes=((10, "Askar 103"), (11, "RC8"), (12, "RC8-bis")),
    nights=("2026-08-08", "2026-08-01", "2026-07-30", "2025-12-31"),
    aliases={"LMC": {"LARGEMAGELLANICCLOUD"}, "IC1396": {"ELEPHANTSTRUNKNEBULA"}},
    rigs=(z.Rig("RC8_ASI2600MM", 11, "RC8", 5, "ASI2600MM"),
          z.Rig("Askar103_ASI2600MM", 10, "Askar 103", 5, "ASI2600MM"),
          z.Rig("Askar103_ASI294MC", 10, "Askar 103", 6, "ASI294MC")),
)


def _r(tekst):
    return z.resolve(z.parse(tekst), KAT)


def _in(stan, facet):
    return [v for v, _ in (stan.facets.get(facet) or {}).get("in", [])]


# ---------- parse ----------

def test_parse_rozdziela_prefiksy_fraze_i_nieznane():
    q = z.parse('noc:2026-08 m 42 foo:bar filtr:Ha')
    assert q.terms == (z.Term("night", "noc", "2026-08", 0), z.Term("filter", "filtr", "Ha", 4))
    assert q.phrase == "m 42"
    assert q.unknown == ("foo:bar",)


def test_parse_cudzyslow_trzyma_spacje_i_przecinek_a_polskie_cudzyslowy_tez_dzialaja():
    q = z.parse('teleskop:"Askar 103" uwagi:„chmury, wiatr”')
    assert q.terms == (z.Term("telescope", "teleskop", "Askar 103", 0),
                       z.Term("notes", "uwagi", "chmury, wiatr", 1))
    assert q.phrase is None


def test_parse_przecinek_dzieli_wartosci_osi_ale_nie_uwag():
    """`filtr:Ha,OIII` = dwie wartości (OR); w uwagach przecinek jest treścią - uwaga to proza."""
    q = z.parse("filtr:Ha,OIII uwagi:a,b")
    assert [t.value for t in q.terms] == ["Ha", "OIII", "a,b"]


def test_parse_slowo_z_cyfra_przed_dwukropkiem_nie_jest_prefiksem():
    """`Sh2:131` albo `12:30` to słowa frazy - prefiksem jest wyłącznie słowo z samych liter."""
    q = z.parse("Sh2:131 12:30")
    assert q.terms == () and q.unknown == ()
    assert q.phrase == "Sh2:131 12:30"


def test_parse_pusta_wartosc_prefiksu_jest_niezrozumiala():
    assert z.parse("filtr:").unknown == ("filtr:",)
    assert z.parse("filtr:,").unknown == ("filtr:",)


@pytest.mark.parametrize("pl,en", [("noc", "night"), ("filtr", "filter"),
                                   ("teleskop", "telescope"), ("zestaw", "setup"),
                                   ("uwagi", "notes")])
def test_oba_jezyki_prefiksow_dzialaja_zawsze_i_bez_wielkosci_liter(pl, en):
    assert z.parse(f"{pl}:x").terms[0].axis == z.parse(f"{en}:x").terms[0].axis
    assert z.parse(f"{pl.upper()}:x").terms[0].axis == z.parse(f"{pl}:x").terms[0].axis


# ---------- resolve: osie ----------

def test_noc_prefiks_ISO_rok_miesiac_dzien():
    assert _in(_r("noc:2026-08"), "night") == ["2026-08-08", "2026-08-01"]
    assert _in(_r("night:2026"), "night") == ["2026-08-08", "2026-08-01", "2026-07-30"]
    assert _in(_r("noc:2026-07-30"), "night") == ["2026-07-30"]
    stan = _r("noc:2026-8")                     # nie ISO - nie zgaduje
    assert stan.facets == {} and stan.unmatched == ("noc:2026-8",)


def test_filtr_rownosc_norm_alnum_OR_w_obrebie_i_nieznana_wartosc():
    stan = _r("filtr:l-pro,Ha filter:Hx")
    assert _in(stan, "filter") == ["L-Pro", "Ha"]
    assert stan.unmatched == ("filter:Hx",)


def test_teleskop_rownosc_bije_prefiks_a_prefiks_dziala_bez_rownosci():
    """`rc8` nie wciąga `RC8-bis`, gdy jest równy `RC8`; `ask` znajduje jedynego Askara."""
    assert _in(_r("teleskop:rc8"), "telescope") == [11]
    assert _in(_r("telescope:ask"), "telescope") == [10]
    assert _in(_r("teleskop:rc"), "telescope") == [11, 12]


def test_zestaw_teleskop_w_facecie_kamera_w_drzewie():
    stan = _r("zestaw:rc8_asi2600mm")
    assert _in(stan, "telescope") == [11]
    assert stan.filter_tree == {"facet": "camera", "value": 5, "label": "ASI2600MM"}


def test_zestawy_bez_krzyzowek_drzewo_jest_dokladne():
    """`A_x,B_y` nie może wpuścić `A_y`: gdy iloczyn teleskopów i kamer nie jest zbiorem par,
    każda para idzie jako AND(teleskop, kamera)."""
    stan = _r("setup:RC8_ASI2600MM,Askar103_ASI294MC")
    assert _in(stan, "telescope") == [11, 10]
    pary = {tuple(c["value"] for c in g["conditions"]) for g in stan.filter_tree["conditions"]}
    assert stan.filter_tree["op"] == "OR" and pary == {(11, 5), (10, 6)}


def test_zestawy_o_wspolnej_kamerze_skladaja_sie_w_OR_kamer():
    stan = _r("zestaw:RC8_ASI2600MM,Askar103_ASI2600MM")
    assert _in(stan, "telescope") == [11, 10]
    assert stan.filter_tree == {"facet": "camera", "value": 5, "label": "ASI2600MM"}


def test_teleskop_i_zestaw_to_AND_a_nie_OR_w_facecie():
    """Różne prefiksy = AND: zestaw nie dokłada swojego teleskopu do facetu `teleskop:` (OR w obrębie
    facetu poszerzyłby zbiór), tylko staje w drzewie jako para."""
    stan = _r("teleskop:rc8 zestaw:Askar103_ASI294MC")
    assert _in(stan, "telescope") == [11]
    assert stan.filter_tree == {"op": "AND", "conditions": [
        {"facet": "telescope", "value": 10, "label": "Askar 103"},
        {"facet": "camera", "value": 6, "label": "ASI294MC"}]}


def test_uwagi_tekst_i_kilka_tekstow_skladaja_sie_w_jeden():
    assert _r("uwagi:chmury").note_query == "chmury"
    assert _r('notes:"rosa  na  lustrze"').note_query == "rosa na lustrze"
    assert _r("uwagi:chmury uwagi:wiatr").note_query == "chmury wiatr"


def test_rozne_prefiksy_skladaja_sie_AND():
    stan = _r("noc:2026-08-08 filtr:Ha teleskop:rc8")
    assert set(stan.facets) == {"night", "filter", "telescope"}


# ---------- resolve: fraza ----------

def test_fraza_trafia_obiekt_nazwa_katalogowa_i_alias():
    assert _in(_r("m 42"), "object") == [1]
    assert _in(_r("sh2 131"), "object") == [3]
    assert _in(_r("large magellanic"), "object") == [2]
    assert _in(_r("elephant"), "object") == [5]


def test_fraza_bez_trafien_staje_sie_tekstem_uwag():
    stan = _r("chmury od północy")
    assert stan.facets == {} and stan.note_query == "chmury od północy"


def test_fraza_z_obiektem_nie_idzie_do_uwag_a_uwagi_obok_dzialaja():
    stan = _r("m42 uwagi:rosa")
    assert _in(stan, "object") == [1] and stan.note_query == "rosa"


def test_fraza_z_samej_interpunkcji_nie_wybiera_calej_biblioteki():
    """Pusta igła szukajki pasuje do każdego obiektu - „-" nie może zaznaczyć wszystkich."""
    stan = _r("-")
    assert stan.facets == {} and stan.note_query is None and stan.unmatched == ("-",)


def test_fraza_z_samych_polskich_liter_idzie_do_uwag_a_nie_do_niezrozumialych():
    """`norm_alnum` zna tylko ASCII, więc „żółć" ma pustą igłę szukajki - to nie jest
    interpunkcja (`str.isalnum` po Unicode), tylko tekst uwagi; obiektów nie wybiera żadnych."""
    stan = _r("żółć")
    assert stan.facets == {} and stan.note_query == "żółć" and stan.unmatched == ()
    assert _r("?! …").unmatched == ("?! …",)


def test_rozpoznane_czesci_dzialaja_obok_nieznanych():
    stan = _r("foo:bar filtr:Ha noc:2030 m42")
    assert _in(stan, "filter") == ["Ha"] and _in(stan, "object") == [1]
    assert stan.unmatched == ("foo:bar", "noc:2030")


def test_puste_zapytanie_to_pusty_stan():
    assert _r("") == z.FindState()


# ---------- słownik z bazy ----------

def test_catalog_from_db_sklada_slownik_z_read_modeli_listwy(tmp_path):
    from fixture_s8 import seed

    from horreum import db
    con = db.open_db(str(tmp_path / "k.db"))
    ids = seed(con)
    con.execute("INSERT INTO object (id, canon, kind) VALUES (1, 'LMC', 'deep_sky')")
    con.execute("INSERT INTO object_alias (object_id, alias_norm, source) "
                "VALUES (1, 'LARGEMAGELLANICCLOUD', 'user')")
    con.execute("UPDATE frame SET object_id = 1, filter_canon = 'Ha' WHERE id = ?",
                (ids["frames"]["c1"],))
    con.execute("INSERT INTO header (frame_id, raw_json, date_obs) VALUES (?, '{}', ?)",
                (ids["frames"]["c1"], "2026-08-09T01:00:00"))
    con.commit()
    kat = z.catalog_from_db(con)
    assert kat.objects == ((1, "LMC"),)
    assert kat.filters == ("Ha",)
    assert kat.nights == ("2026-08-08",)
    assert {r.label for r in kat.rigs} >= {"RC8_ASI294MC"}
    stan = z.resolve(z.parse("large magellanic zestaw:rc8_asi294mc noc:2026-08"), kat)
    assert _in(stan, "object") == [1] and _in(stan, "night") == ["2026-08-08"]
    assert stan.filter_tree == {"facet": "camera", "value": ids["cam2"], "label": "ASI294MC"}
    con.close()


# ---------- terminy (chip na WPISANY termin) ----------

def test_jeden_termin_na_wpisany_token_z_kluczami_wszystkich_jego_skladnikow():
    """„noc:2026-08" to dwie noce, „filtr:Ha,OIII" dwa filtry, fraza „m" kilka obiektów - każdy
    z nich to JEDEN chip, który zdejmuje wszystko, co postawił."""
    stan = _r("noc:2026-08 filtr:Ha,OIII uwagi:rosa m 42")
    assert [t.label for t in stan.terms] == ["Noc: 2026-08", "Filtr: Ha, OIII", "Obiekt: m 42",
                                             "Uwagi: „rosa”"]
    noc, filtr, obiekt, uwagi = (t.keys for t in stan.terms)
    assert noc == (("facet", "night", "in", "2026-08-08"), ("facet", "night", "in", "2026-08-01"))
    assert filtr == (("facet", "filter", "in", "Ha"), ("facet", "filter", "in", "OIII"))
    assert obiekt == (("facet", "object", "in", 1),)
    assert uwagi == (("uwagi",),)


def test_termin_zestawu_niesie_teleskop_i_filtr_a_z_tokenem_teleskopu_sam_filtr():
    assert _r("zestaw:rc8_asi2600mm").terms[0].keys == (
        ("filtr",), ("facet", "telescope", "in", 11))
    stan = _r("teleskop:rc8 zestaw:Askar103_ASI294MC")
    assert [t.keys for t in stan.terms] == [(("facet", "telescope", "in", 11),), (("filtr",),)]


def test_termin_bez_trafien_nie_ma_chipu_a_czesciowy_ma_tylko_trafione_wartosci():
    stan = _r("filtr:Ha,Hx noc:2030")
    assert [t.label for t in stan.terms] == ["Filtr: Ha"]
    assert stan.unmatched == ("filtr:Hx", "noc:2030")


def test_zapytanie_bez_rozpoznanych_czesci_nie_jest_rozpoznane():
    assert not _r("bzdura:xyz").recognized and _r("bzdura:xyz").unmatched == ("bzdura:xyz",)
    assert _r("uwagi:x").recognized and _r("m42").recognized
    assert not _r("").recognized and _r("").unmatched == ()


def test_nazwy_osi_chipow_sa_w_katalogu():
    from horreum.gui.i18n_catalog import CATALOG
    assert not [k for k in z._NAZWA_OSI.values() if k not in CATALOG]


# ---------- fraza po Enterze: najpierw trafienia dokładne ----------

KAT_PREFIKS = z.FindCatalog(
    objects=((1, "M1"), (2, "M101"), (3, "M106"), (4, "NGC7000"), (5, "NGC7023"),
             (6, "Sh2-131"), (7, "IC1795")),
    aliases={"IC1795": {"HEARTOFTHESOUL"}})


def _obj(tekst):
    return _in(z.resolve(z.parse(tekst), KAT_PREFIKS), "object")


def test_fraza_dokladna_wylacza_trafienia_prefiksowe():
    """Szukajka listwy trafia też prefiksem (pisanie znak po znaku), ale po Enterze `m1` przy M1
    i M101 to M1 - choć jedno trafienie dokładne na liście wyłącza prefiksowe."""
    assert _obj("m1") == [1]
    assert _obj("M 1") == [1]


def test_fraza_bez_dokladnego_trafienia_idzie_droga_szukajki():
    assert sorted(_obj("ngc70")) == [4, 5]


def test_oznaczenie_katalogowe_i_alias_trafiaja_dokladnie():
    assert _obj("sh2 131") == [6]
    assert _obj("heart of the soul") == [7]
