"""catalog_xref — asset ładuje się przez importlib.resources (jedzie w wheelu, bramka clone'a) +
rozpoznanie oznaczenia (`catalog_canon`), równoważność (`xref`) i etykieta (`catalog_label`)."""
import pytest

from horreum.resolve.catalog import (
    catalog_canon, catalog_label, header_form, load_catalog_xref, xref, xref_aliases,
)


def test_catalog_xref_laduje_sie():
    x = load_catalog_xref()
    assert {"messier_to_ngc", "caldwell_to_ngc", "sh2_to_ic", "cross_to_ngc"} <= set(x)


def test_ngc_wins_forma():
    """Messier/Caldwell = alias-only -> rozwiązują się do klucza NGC/IC (polityka NGC-wins)."""
    x = load_catalog_xref()
    assert x["messier_to_ngc"]["M106"] == "NGC4258"
    assert x["caldwell_to_ngc"]["C23"] == "NGC891"
    assert x["sh2_to_ic"]["Sh2-190"] == "IC1805"


# --- catalog_canon: rozpoznanie + normalizacja zapisu (§3.5) ---

@pytest.mark.parametrize("raw, expected", [
    ("NGC 4736", "NGC4736"),       # spacja precz
    ("NGC4736", "NGC4736"),
    ("ngc 224", "NGC224"),         # case-insensitive
    ("NGC 0224", "NGC224"),        # zera wiodące precz
    ("Sh2 131", "Sh2-131"),        # Sharpless: spacja -> myślnik
    ("SH2-131", "Sh2-131"),
    ("M 81", "M81"),
    ("Messier 81", "M81"),
    ("IC1805", "IC1805"),
    ("C 23", "C23"),
    ("LDN 1174", "LDN1174"),
    ("vdB 142", "vdB142"),
])
def test_catalog_canon_rozpoznaje_i_normalizuje(raw, expected):
    assert catalog_canon(raw) == expected


@pytest.mark.parametrize("raw", ["Heart Nebula", "Bode's Galaxy", "FlatWizard", "Snapshot", "", None])
def test_catalog_canon_nie_oznaczenie_to_none(raw):
    """Nazwa potoczna / nie-obiekt NIE udaje kanonu (None) — koniec cichego śmieciowego kanonu."""
    assert catalog_canon(raw) is None


def test_catalog_canon_zapis_dwuczlonowy_tylko_podkreslnik():
    """Etap 6.x firsthand: 'NGC4631_PGC42637' → pierwszy człon 'NGC4631' (scala z 'NGC4631').
    Rozdzielnik to WYŁĄCZNIE '_'; oznaczenia ze spacją wewnętrzną = JEDEN człon, nietknięte —
    regresja na ostrzeżonych przypadkach. Prefiks nie-oznaczenie → None (bez over-matchu)."""
    assert catalog_canon("NGC4631_PGC42637") == "NGC4631"
    assert catalog_canon("Sh 2-184") == "Sh2-184"       # spacja ≠ rozdzielnik (NIE 'SH'+'2-184')
    assert catalog_canon("Caldwell 23") == "C23"         # j.w. — jeden człon ze spacją
    assert catalog_canon("Foo_Bar") is None              # prefiks nie-oznaczenie → None


# --- xref: równoważność międzykatalogowa (NGC-wins, DANYMI) ---

def test_xref_messier_caldwell_sh2_na_ngc_ic():
    assert xref("M106") == "NGC4258"        # Messier -> NGC
    assert xref("C23") == "NGC891"          # Caldwell -> NGC
    assert xref("Sh2-190") == "IC1805"      # Sharpless -> IC (realny bliźniak, danymi)


def test_xref_brak_wpisu_bez_zmiany():
    """Brak wpisu → kanon bez zmian: M45 (Plejady) nie ma NGC → zostaje M45; NGC bez xref też."""
    assert xref("M45") == "M45"
    assert xref("NGC4258") == "NGC4258"
    assert xref("Sh2-131") == "Sh2-131"     # Trąba Słonia — Sh2 zachowany (brak bliźniaka IC w danych)


# --- catalog_label: etykieta z formy kanonicznej ---

@pytest.mark.parametrize("canon, label", [
    ("NGC4258", "NGC"), ("IC1805", "IC"), ("Sh2-131", "Sh2"),
    ("M45", "Messier"), ("C23", "Caldwell"), ("LDN1174", "LDN"),
    ("vdB142", "vdB"), ("Ced214", "Ced"), ("Cr399", "Collinder"), ("B33", "Barnard"),
])
def test_catalog_label(canon, label):
    assert catalog_label(canon) == label


# --- K-1: trzy gramatyki, które asset celów już wypisuje (Green SNR / ESO / HCG) ---

@pytest.mark.parametrize("tekst, canon", [
    # Green (SNR) — wariant zapisany tak, jak stoi w assecie, i tak, jak pisze go człowiek.
    ("G012.2+00.3", "G012.2+00.3"), ("G12.2+0.3", "G012.2+00.3"),
    ("G 12.2 + 0.3", "G012.2+00.3"), ("g000.0+00.0", "G000.0+00.0"),
    ("G001.4-00.1", "G001.4-00.1"), ("G1.4-0.1", "G001.4-00.1"),
    # ESO — pole i obiekt w polu, obie liczby stałoszerokościowe.
    ("ESO056-115", "ESO056-115"), ("ESO 56-115", "ESO056-115"), ("eso 056 - 115", "ESO056-115"),
    # HCG — grupa zwarta Hicksona.
    ("HCG092", "HCG092"), ("HCG 92", "HCG092"), ("hcg92", "HCG092"),
])
def test_K1_trzy_nowe_gramatyki(tekst, canon):
    assert catalog_canon(tekst) == canon


@pytest.mark.parametrize("canon, label", [
    ("G012.2+00.3", "Green"), ("ESO056-115", "ESO"), ("HCG092", "HCG"),
])
def test_K1_etykiety(canon, label):
    assert catalog_label(canon) == label


@pytest.mark.parametrize("tekst", [
    "PN G012.2+00.3",       # mgławica planetarna — IDENTYCZNY kształt liczbowy, INNY obiekt
    "PNG012.2+00.3",
    "PN_G012.2+00.3",       # …także po gałęzi cięcia dwuczłonowego
])
def test_K1_gramatyka_G_NIE_POLYKA_mgławicy_planetarnej(tekst):
    """Druga pułapka z długu K-1: `PN G###.#±##.#` ma ten sam kształt liczbowy co Green.

    Wpuszczenie go zrobiłoby z mgławicy planetarnej pozostałość po supernowej — błąd, którego
    nikt by nie zobaczył, bo kanon wyglądałby poprawnie.

    Falsyfikator ZMIERZONY, i wynik jest ciekawszy niż zapis w długu: obrona jest PODWÓJNA i każda
    połowa wystarcza sama. Zdjęcie `^` z regexa nie zmienia nic (bo `_match_rules` woła `rx.match`,
    które kotwiczy początek), a podmiana `match`→`search` też nie (bo zostaje `^`). Dopiero OBIE
    naraz wpuszczają wszystkie trzy warianty — sprawdzone. Test pinuje SKUTEK, więc przeżyje
    usunięcie którejkolwiek z połówek i zaczerwieni się dopiero, gdy zniknie ochrona jako taka."""
    assert catalog_canon(tekst) is None


@pytest.mark.parametrize("tekst, canon", [
    ("Ced214", "Ced214"), ("Cr399", "Cr399"), ("CTB1", "CTB1"),
])
def test_K1_krotkie_G_nie_zjada_sasiadow(tekst, canon):
    """Pierwsza pułapka z długu K-1: `G` jest krótkie i nie może odebrać nazw sąsiadom.

    Regresja na trójce, którą dług wymienia z nazwiska (`Ced`/`Cr`/`CTB`)."""
    assert catalog_canon(tekst) == canon
    assert catalog_label(catalog_canon(tekst)) != "Green"


def test_K1_kanon_zgadza_sie_z_ASSETEM_celow():
    """SENS CAŁEGO K-1: kanon osi obiektu ma trafiać w to, co planer wypisuje jako cel.

    Gdyby gramatyka zdjęła zera wiodące (`G12.2+0.3`), nazwa z nagłówka rozwiązałaby się na kanon,
    którego asset nie zna — i szew planer↔oś obiektu zostałby otwarty mimo zielonych testów wyżej.
    Dlatego bramka pyta ASSET, a nie listę literałów."""
    import json
    from importlib import resources
    surowe = json.loads(resources.files("horreum.data")
                        .joinpath("targets_core.json").read_text(encoding="utf-8"))
    cele = [t["c"] for t in surowe["targets"]
            if t.get("c", "").startswith(("G0", "G1", "G2", "G3", "ESO", "HCG"))]
    # 297 = liczba zmierzona przy zakładaniu długu K-1 („szew na 297 celach"). Próg, nie
    # równość: asset rośnie, a bramka ma pilnować, że gramatyki nie WYPADŁY.
    assert len(cele) >= 297, f"asset stracił cele tych gramatyk (jest {len(cele)})"
    rozjazd = [c for c in cele if catalog_canon(c) != c]
    assert rozjazd == [], f"kanon rozjeżdża się z assetem dla: {rozjazd[:5]}"


# --- header_form: kanon Horreum → forma karty OBJECT (decyzja usera 2026-09-26) ---

@pytest.mark.parametrize("canon, naglowek", [
    ("NGC7000", "NGC 7000"), ("IC1805", "IC 1805"), ("UGC1234", "UGC 1234"),
    ("PGC42637", "PGC 42637"), ("M45", "M 45"), ("C14", "C 14"),
    ("LDN1152", "LDN 1152"), ("LBN807", "LBN 807"), ("CTB1", "CTB 1"), ("Cr464", "Cr 464"),
    ("vdB1", "vdB 1"), ("Abell85", "Abell 85"), ("B33", "B 33"), ("Ced214", "Ced 214"),
    ("ESO056-115", "ESO 056-115"), ("HCG079", "HCG 079"),     # K-1: zera wiodące ZOSTAJĄ
    ("Sh2-131", "Sh2-131"),                                    # dywiz = część oznaczenia
    ("G012.2+00.3", "G012.2+00.3"),                            # współrzędna, nie skrót + numer
])
def test_header_form_per_gramatyka_i_odwracalnosc(canon, naglowek):
    """Jedna forma nagłówka na gramatykę ORAZ kontrakt odwracalności: nagłówek zapisany tą formą
    wraca przez `catalog_canon` do TEGO SAMEGO kanonu (inaczej zapis nagłówka przenosiłby klatki)."""
    assert header_form(canon) == naglowek
    assert catalog_canon(header_form(canon)) == canon


@pytest.mark.parametrize("canon", ["LMC", "Orion", "WR134", "Moon", "Jupiter", "Veil",
                                   "C/2023 A3 (Tsuchinshan-ATLAS)", "21P/Giacobini-Zinner", "", None])
def test_header_form_kanon_spoza_gramatyk_bez_zmian(canon):
    """Obiekty własne, solar, region, komety: kanonu nie ma jak rozbić na skrót i numer."""
    assert header_form(canon) == canon


def test_header_form_KAZDA_etykieta_katalogu_ma_decyzje():
    """Nowa gramatyka w `_LABELS` nie może przejść po cichu z formą nagłówka równą kanonowi: albo
    dostaje spację (`_HEADER_SPACED`), albo jest świadomym wyjątkiem (`_HEADER_UNSPACED_LABELS`)."""
    from horreum.resolve import catalog as cat
    przyklad = {"NGC": "NGC1", "IC": "IC1", "Sh2": "Sh2-1", "UGC": "UGC1", "PGC": "PGC1",
                "LBN": "LBN1", "LDN": "LDN1", "Abell": "Abell1", "vdB": "vdB1", "Ced": "Ced1",
                "Collinder": "Cr1", "CTB": "CTB1", "Barnard": "B1", "ESO": "ESO001-001",
                "HCG": "HCG001", "Green": "G001.0+00.0", "Messier": "M1", "Caldwell": "C1"}
    assert {label for _rx, label in cat._LABELS} == set(przyklad), "nowa etykieta bez przykładu"
    for label, canon in przyklad.items():
        assert catalog_label(canon) == label and catalog_canon(canon) == canon, canon
        spacja = header_form(canon) != canon
        assert spacja != (label in cat._HEADER_UNSPACED_LABELS), label
        assert catalog_canon(header_form(canon)) == canon, canon


def test_header_form_odwracalny_na_calym_ASSECIE_celow():
    """Korpus realnych kanonów (asset planera): każdy kanon gramatyki wraca do siebie, każdy spoza
    gramatyk zostaje bez zmian. Bramka pyta asset, nie listę literałów - asset rośnie."""
    import json
    from importlib import resources
    surowe = json.loads(resources.files("horreum.data")
                        .joinpath("targets_core.json").read_text(encoding="utf-8"))
    kanony = {t["c"] for t in surowe["targets"] if t.get("c")}
    gramatyka = {c for c in kanony if catalog_canon(c, split=False) == c}
    assert len(gramatyka) > 1000, len(gramatyka)
    assert [c for c in gramatyka if catalog_canon(header_form(c)) != c] == []
    assert [c for c in kanony - gramatyka if header_form(c) != c] == []


def test_xref_aliases_czyta_rownowaznosc_wstecz():
    assert xref_aliases("NGC4258") == ("M106",)
    assert xref_aliases("NGC7023") == ("C4", "LDN1174")
    assert xref_aliases("IC1805") == ("Sh2-190",)
    assert xref_aliases("M45") == ()                   # brak wpisu = brak aliasu, nie błąd
    assert all(xref(a) == "NGC7023" for a in xref_aliases("NGC7023"))


# --- AR-132: Messier → NGC/IC z katalogu, wpis pod obiekt obecny w archiwum ---

def test_xref_M64_na_NGC4826():
    """Zgłoszenie „m64 nie ma w bazie": obiekt `NGC4826` jest w archiwum (190 lightów, 4 stosy),
    a `M64` nie miał równoważności. Zapis Messiera dochodzi do kanonu NGC tą samą drogą, którą
    idzie resolver (`catalog_canon` → `xref`)."""
    from horreum.resolve.objects import resolve_object
    assert xref("M64") == "NGC4826"
    assert "M64" in xref_aliases("NGC4826")
    assert xref(catalog_canon("m 64")) == "NGC4826"
    assert xref(catalog_canon("Messier 64")) == "NGC4826"
    ident = resolve_object("M 64")
    assert (ident.canon, ident.source, ident.alias_norm) == ("NGC4826", "catalog_xref", "M64")


def test_messier_xref_forma_wyjatki_i_zgodnosc_z_assetem_celow():
    """Klucz `M<n>` i wartość NGC/IC w formie kanonu gramatyki; Messier bez NGC/IC w VII/118
    (M24, M40, M45, M102) bez wpisu. Para nie przeczy assetowi celów (kolumna M OpenNGC) - dwa
    źródła tej samej równoważności nie rozjadą się po cichu."""
    import json
    from importlib import resources
    messier = load_catalog_xref()["messier_to_ngc"]
    for m, cel in messier.items():
        assert catalog_canon(m, split=False) == m and catalog_label(m) == "Messier", m
        assert catalog_canon(cel, split=False) == cel and catalog_label(cel) in ("NGC", "IC"), cel
    assert not {"M24", "M40", "M45", "M102"} & set(messier)
    surowe = json.loads(resources.files("horreum.data")
                        .joinpath("targets_core.json").read_text(encoding="utf-8"))
    pary = {(c, r["c"]) for r in surowe["targets"] for a in r.get("n") or ()
            for c in [catalog_canon(a, split=False)] if c in messier}
    assert ("M64", "NGC4826") in pary                  # porównanie nie jest puste
    assert [(m, cel) for m, cel in pary if messier[m] != cel] == []


def test_szukanie_M64_z_ekranu_trafia_NGC4826():
    """Szukajka listwy facetu „Obiekt” (`facet_model.search_hit`, ten sam predykat w oknie
    „Przypisz obiekt”) i fraza Znajdź (`flows.znajdz.resolve`) rozumieją „M64” przez `xref`, choć
    obiekt w bazie nosi wyłącznie alias `NGC4826` (stan archiwum ze zgłoszenia)."""
    from horreum.gui import facet_model
    from horreum.gui.flows import znajdz
    aliasy = {"NGC4826": {"NGC4826"}, "NGC4736": {"NGC4736"}}
    assert facet_model.search_hit("M64", "NGC4826", aliasy) == "M64"
    assert facet_model.search_hit("m 64", "NGC4826", aliasy) == "M64"
    assert facet_model.search_hit("M64", "NGC4736", aliasy) is None
    kat = znajdz.FindCatalog(objects=((1, "NGC4826"), (2, "NGC4736"), (3, "M45")), aliases=aliasy)
    stan = znajdz.resolve(znajdz.parse("m64"), kat)
    assert stan.facets == {"object": {"in": [[1, "NGC4826"]]}}
    assert stan.note_query is None and stan.unmatched == ()


# --- D-1013-1: pełna tabela Messier → NGC/IC z VII/118 ---

def test_messier_xref_PELNA_tabela_106_kluczy_M76_na_NGC650():
    """Decyzja `Q9`: wszystkie 106 Messierów, które VII/118 wiąże z NGC/IC (110 minus M24, M40, M45,
    M102). Dwie pozycje VII/118 z dwoma obiektami rozstrzyga kolumna M OpenNGC: M76 → NGC650
    (NGC651 to druga połowa tego samego obiektu), M51 → NGC5194. Polityka pliku mówi to wprost."""
    x = load_catalog_xref()
    messier = x["messier_to_ngc"]
    assert len(messier) == 106
    assert set(messier) == {f"M{n}" for n in range(1, 111)} - {"M24", "M40", "M45", "M102"}
    assert messier["M76"] == "NGC650" and messier["M51"] == "NGC5194"
    assert (xref("M13"), xref("M25"), xref("M110")) == ("NGC6205", "IC4725", "NGC205")
    for pole in ("_doc", "_zrodlo_messier"):
        assert "pełna tabela z VII/118" in x[pole], pole


@pytest.mark.parametrize("nazwa, cel", [
    ("M33", "NGC598"), ("M 33", "NGC598"), ("Messier 33", "NGC598"), ("Sh2-190", "IC1805"),
    ("NGC598", None), ("M45", None), ("LMC", None), ("", None), (None, None),
    ("M33_NGC598", None),            # sklejka nie jest nazwą-kluczem (split=False)
])
def test_xref_key_target_jeden_predykat_nazwy_klucza(nazwa, cel):
    from horreum.resolve.catalog import xref_key_target
    assert xref_key_target(nazwa) == cel


# --- AR-135: para dopisana do bazy, która zna już obiekt pod kluczem ---

NOW_X = "2026-10-14T12:00:00"


@pytest.fixture
def bez_pary_M33():
    """Stan SPRZED dopisania pary `M33 → NGC598`: `xref` czyta spłaszczoną tabelę przez
    `_xref_flat`, więc podmieniamy ją bez pary; `_xref_reverse` ma własny cache - czyszczony po obu
    stronach. Zwraca funkcję, która „dopisuje” parę (cofa podmianę). Własny `MonkeyPatch`, nie
    fixture testu: cofnięcie w połowie testu nie może zdjąć cudzych podmian."""
    from horreum.resolve import catalog as cat
    pelna = dict(cat._xref_flat())
    mp = pytest.MonkeyPatch()
    mp.setattr(cat, "_xref_flat", lambda: {k: v for k, v in pelna.items() if k != "M33"})
    cat._xref_reverse.cache_clear()

    def dopisz():
        mp.undo()
        cat._xref_reverse.cache_clear()
    yield dopisz
    mp.undo()
    cat._xref_reverse.cache_clear()


def _baza_M33(tmp_path, obiekty):
    """Archiwum z lightami o zadanych kartach `OBJECT` (osobne piksele = osobne klatki)."""
    import numpy as np
    from astropy.io import fits
    from horreum import db
    from horreum.scan import scan_tree
    con = db.open_db(str(tmp_path / "x.db"))
    tree = tmp_path / "t"
    tree.mkdir()
    for n, obj in enumerate(obiekty, start=1):
        hdu = fits.PrimaryHDU(data=np.full((4, 4), n, np.uint16))
        for kw, val in (("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76),
                        ("IMAGETYP", "LIGHT"), ("OBJECT", obj)):
            hdu.header[kw] = val
        fits.HDUList([hdu]).writeto(str(tree / f"l{n}.fits"))
    scan_tree(con, tree, now=NOW_X)
    return con


def _klatka(con, raw):
    return con.execute("SELECT f.id FROM frame f JOIN header h ON h.frame_id = f.id "
                       "WHERE h.object_raw = ?", (raw,)).fetchone()[0]


def _stan(con, fid):
    r = con.execute("SELECT o.canon AS canon, f.object_source AS src FROM frame f "
                    "LEFT JOIN object o ON o.id = f.object_id WHERE f.id = ?", (fid,)).fetchone()
    return r["canon"], r["src"]


def _zdarzenia(con):
    return con.execute("SELECT count(*) FROM event").fetchone()[0]


def test_AR135_para_dopisana_po_fakcie_jedna_tozsamosc_i_wiersz_Porzadkow(tmp_path, bez_pary_M33):
    """Baza sprzed pary niesie obiekt `M33` z aliasem z nagłówka, klatkami z nagłówka, klatką
    z ALIASU (zeznanie `M-33`, którego gramatyka nie czyta) i klatką RĘKI. Po dopisaniu pary:

      * predykat Porządków pokazuje obiekt `M33` z jego klatkami i nazywa cel (`NGC598`);
      * `object_target("M33")` = cel pary, choć obiekt o kanonie `M33` dalej stoi w bazie;
      * przebieg przenosi klatki z nagłówka, PRZEPINA równoważność `M33` na cel (klinga
        `rebind_object_alias`), a klatka z aliasu idzie za nią w tym samym przebiegu - nazwa ma
        JEDNĄ tożsamość: lookup aliasu, przebieg i wybór celu gestu mówią `NGC598`;
      * ręka nietknięta: klatka i równoważność ręki zostają przy `M33`, predykat dalej ją pokazuje;
      * drugi przebieg nie dopisuje ani jednego zdarzenia.

    Mutant: `rebind_object_alias` zwraca False bez zapisu → lookup aliasu `M33` zostaje przy
    starym obiekcie i asercja tożsamości czerwienieje."""
    from horreum import repo
    from horreum.gui import queries
    from horreum.resolver import alias_lookup, run_resolver
    con = _baza_M33(tmp_path, ["M 33", "M33", "M-33", "Triangulum Pinwheel"])
    run_resolver(con, now=NOW_X)
    run_resolver(con, now=NOW_X)          # drugi przebieg: alias `M33` już stoi, `M-33` go trafia
    f1, f2, fa, fr = (_klatka(con, r) for r in ("M 33", "M33", "M-33", "Triangulum Pinwheel"))
    assert [_stan(con, f) for f in (f1, f2, fa)] == [
        ("M33", "header"), ("M33", "header"), ("M33", "alias")]
    g = repo.user_assign_object(con, alias_norm="TRIANGULUMPINWHEEL", canon="M33",
                                catalog="Messier", kind="deep_sky", frame_ids=[fr], now=NOW_X)
    assert g.assigned == 1
    assert queries.xref_reconcile_rows(con) == []          # bez pary nie ma czego uzgadniać

    bez_pary_M33()                                          # para dopisana
    assert queries.xref_reconcile_rows(con) == [
        ("M33", "M33", "NGC598", frozenset({f1, f2, fa, fr}))]
    assert queries.object_target(con, "M33").canon == "NGC598"

    s = run_resolver(con, now=NOW_X)
    assert (s.xref_aliases_rebound, s.xref_frames_followed, s.alias_conflicts) == (1, 1, 0)
    assert [_stan(con, f) for f in (f1, f2, fa, fr)] == [
        ("NGC598", "catalog_xref"), ("NGC598", "catalog_xref"), ("NGC598", "alias"),
        ("M33", "user")]
    assert alias_lookup(con)("M33")["canon"] == "NGC598" == queries.object_target(con, "M33").canon
    assert alias_lookup(con)("TRIANGULUMPINWHEEL")["canon"] == "M33"     # ręka zostaje
    assert con.execute("SELECT count(*) FROM object WHERE canon = 'NGC598'").fetchone()[0] == 1
    przepiecie = con.execute("SELECT payload FROM event WHERE verb = 'object.alias_rebound'"
                             ).fetchall()
    assert len(przepiecie) == 1 and '"source": "header"' in przepiecie[0][0]
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'object.alias_conflict_state'"
                       ).fetchone()[0] == 0
    assert queries.xref_reconcile_rows(con) == [("M33", "M33", "NGC598", frozenset({fr}))]
    assert queries.xref_reconcile_frame_ids(con) == {fr}

    # raport Dostawy: przepięcie ma swój człon, a przebieg bez przepięć milczy (QUIET)
    widok = pytest.importorskip("horreum.gui.pipeline").PipelineView
    from horreum.gui import i18n
    czlon = i18n.t_plural("pipeline.fmt.resolve_xref_rebound", 1, frames=1)
    assert czlon in widok._format_resolve(None, s)

    przed = _zdarzenia(con)
    s2 = run_resolver(con, now=NOW_X)
    assert _zdarzenia(con) == przed and s2.xref_aliases_rebound == 0
    assert czlon not in widok._format_resolve(None, s2)
    con.close()


def test_AR135_rownowaznosc_RECZNA_zostaje_jako_konflikt_zgloszony_RAZ(tmp_path, bez_pary_M33):
    """Równoważność `M33` postawiona RĘKĄ (`source='user'`) nie jest przepinana: `add_object_alias`
    zwraca konflikt wołającemu, przebieg agreguje go po parze i zgłasza STAN jednym zdarzeniem,
    a kolejny przebieg z tym samym stanem jest ciszą (nie per klatka, nie per przebieg)."""
    from horreum import repo
    from horreum.gui import queries
    from horreum.resolver import run_resolver
    con = _baza_M33(tmp_path, ["M 33", "Triangulum Pinwheel", "M  33"])
    fr = _klatka(con, "Triangulum Pinwheel")
    g = repo.user_assign_object(con, alias_norm="M33", canon="M33", catalog="Messier",
                                kind="deep_sky", frame_ids=[fr], now=NOW_X)
    assert g.assigned == 1
    run_resolver(con, now=NOW_X)
    oid_m33 = con.execute("SELECT id FROM object WHERE canon = 'M33'").fetchone()[0]
    assert con.execute("SELECT source FROM object_alias WHERE alias_norm = 'M33'"
                       ).fetchone()[0] == "user"

    bez_pary_M33()
    s = run_resolver(con, now=NOW_X)
    assert (s.xref_aliases_rebound, s.alias_conflicts) == (0, 1)
    widok = pytest.importorskip("horreum.gui.pipeline").PipelineView
    from horreum.gui import i18n
    assert (i18n.t_plural("pipeline.fmt.resolve_alias_conflict", 1)
            in widok._format_resolve(None, s))                 # konflikt ma powierzchnię w raporcie
    stan = con.execute("SELECT payload FROM event WHERE verb = 'object.alias_conflict_state'"
                       ).fetchall()
    assert len(stan) == 1 and f'"items": [["M33", {oid_m33}, "NGC598"]]' in stan[0][0]
    assert con.execute("SELECT object_id FROM object_alias WHERE alias_norm = 'M33'"
                       ).fetchone()[0] == oid_m33                      # ręka nietknięta
    assert _stan(con, fr) == ("M33", "user")
    assert [n for n, _c, _t, _f in queries.xref_reconcile_rows(con)] == ["M33"]

    przed = _zdarzenia(con)
    run_resolver(con, now=NOW_X)
    assert _zdarzenia(con) == przed, "ten sam stan konfliktu - drugi przebieg jest ciszą"

    # klinga wprost: konflikt wraca do wołającego, zero zapisu; przepięcie ręki odmówione
    oid_cel = con.execute("SELECT id FROM object WHERE canon = 'NGC598'").fetchone()[0]
    zapis = repo.add_object_alias(con, alias_norm="M33", object_id=oid_cel,
                                  source="catalog_xref", now=NOW_X)
    assert (zapis.created, zapis.conflict_object_id) == (False, oid_m33)
    assert repo.rebind_object_alias(con, alias_norm="M33", object_id=oid_cel,
                                    expected_object_id=oid_m33, now=NOW_X) == (False, 0)
    assert _zdarzenia(con) == przed
    con.close()


def test_AR135_alias_i_klatki_JEDNA_transakcja_awaria_w_polowie_nie_zapisuje_nic(
        tmp_path, bez_pary_M33, monkeypatch):
    """Przepięcie równoważności `M33` i klatki z niej (`M-33`, źródło `alias`) to JEDNA klinga pod
    `BEGIN IMMEDIATE`: awaria wstrzyknięta między zapisem aliasu a ruchem klatki cofa oba zapisy
    (alias przy starym obiekcie, klatka przy nim, zero `object.alias_rebound`), a następny przebieg
    dokańcza całość. Mutant: alias i klatki w osobnych transakcjach - po awarii alias wskazuje cel,
    klatka zostaje przy `M33` na zawsze (kolejny przebieg mija alias, który już wskazuje cel)."""
    from horreum import repo
    from horreum.resolver import alias_lookup, run_resolver
    con = _baza_M33(tmp_path, ["M 33", "M-33"])
    run_resolver(con, now=NOW_X)
    run_resolver(con, now=NOW_X)
    fa = _klatka(con, "M-33")
    assert _stan(con, fa) == ("M33", "alias")
    bez_pary_M33()

    prawdziwy = repo.emit_event

    def awaria(con_, **kw):
        if kw["verb"] == "object.assigned" and kw["target"] == f"frame:{fa}":
            raise RuntimeError("awaria w połowie przepięcia")
        return prawdziwy(con_, **kw)
    monkeypatch.setattr(repo, "emit_event", awaria)
    with pytest.raises(RuntimeError, match="w połowie"):
        run_resolver(con, now=NOW_X)
    assert alias_lookup(con)("M33")["canon"] == "M33"             # alias cofnięty razem z klatką
    assert _stan(con, fa) == ("M33", "alias")
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'object.alias_rebound'"
                       ).fetchone()[0] == 0
    monkeypatch.setattr(repo, "emit_event", prawdziwy)
    s = run_resolver(con, now=NOW_X)
    assert (s.xref_aliases_rebound, s.xref_frames_followed) == (1, 1)
    assert alias_lookup(con)("M33")["canon"] == "NGC598" and _stan(con, fa) == ("NGC598", "alias")
    con.close()


def test_AR135_okno_przypisania_i_skrot_ostatnio_uzyte_ida_do_celu_pary(tmp_path, bez_pary_M33):
    """Pierwszeństwo pary obejmuje KAŻDĄ powierzchnię, która wskazuje obiekt istniejący, nie tylko
    „Zmień obiekt…”: wybór starej tożsamości `M33` z listy okna przypisania zapisuje `NGC598` (żywy
    cel pary) i mówi to zdaniem przed kliknięciem, a skrót „ostatnio użyte” podaje `NGC598` zamiast
    `M33`. Jedna reguła: `queries.xref_live_target`. Mutant: okno bez reguły - `selected` niesie
    `M33`, a zapis ręki trafia do starej tożsamości obok celu pary."""
    from PySide6.QtWidgets import QApplication
    from horreum import repo
    from horreum.gui import i18n, queries
    from horreum.gui.assign_dialog import AssignObjectDialog
    from horreum.resolver import run_resolver
    QApplication.instance() or QApplication([])
    con = _baza_M33(tmp_path, ["M 33", "Triangulum Pinwheel"])
    run_resolver(con, now=NOW_X)
    fr = _klatka(con, "Triangulum Pinwheel")
    repo.user_assign_object(con, alias_norm="TRIANGULUMPINWHEEL", canon="M33", catalog="Messier",
                            kind="deep_sky", frame_ids=[fr], now=NOW_X)
    assert [r["canon"] for r in queries.recent_hand_objects(con)] == ["M33"]   # bez pary - M33
    bez_pary_M33()
    run_resolver(con, now=NOW_X)                         # `M 33` idzie do NGC598 - cel jest żywy
    assert queries.xref_live_target(con, "M33")["canon"] == "NGC598"
    assert queries.xref_live_target(con, "NGC598") is None

    assert [r["canon"] for r in queries.recent_hand_objects(con)] == ["NGC598"]
    dlg = AssignObjectDialog(con, object_raw=None, frame_count=1)
    try:
        idx = next(i for i in range(dlg.combo.count())
                   if dlg.combo.itemData(i) is not None and dlg.combo.itemData(i)[1] == "M33")
        dlg.combo.setCurrentIndex(idx)
        assert dlg.canon_preview.text() == i18n.t("assign.xref_redirect", old="M33", new="NGC598")
        dlg._validate_and_accept()
        assert dlg.selected == ("NGC598", "NGC", None, None)
    finally:
        dlg.close()
    con.close()


def test_AR135_cel_pary_tylko_jako_NAGROBEK_to_cel_nieistniejacy(tmp_path, bez_pary_M33):
    """Cel pary (`NGC598`) istnieje wyłącznie jako nagrobek (0040: gest go założył i „Cofnij” zdjął).
    Równoważność `M33` z nagłówka NIE idzie na nagrobek - zostaje raportem konfliktu; klinga
    przepięcia odmawia nagrobkowi wprost; wybór celu gestu bierze tożsamość z drabiny, nie
    z nagrobka; nagrobek nie wstaje (klatek do niego nie ma - ręka trzyma swoje przy `M33`).
    Mutant: cel przepięcia bez `retired_at IS NULL` - alias ląduje na nagrobku."""
    from horreum import repo
    from horreum.gui import queries
    from horreum.resolver import alias_lookup, run_resolver
    from test_nagrobek_osi import _cofnij_baze, _klatka_z_kopia, _nagrobek, _przebieg_bazy
    con = _baza_M33(tmp_path, ["Triangulum Pinwheel"])
    fr = _klatka(con, "Triangulum Pinwheel")
    repo.user_assign_object(con, alias_norm="TRIANGULUMPINWHEEL", canon="M33", catalog="Messier",
                            kind="deep_sky", frame_ids=[fr], now=NOW_X)
    oid_m33 = con.execute("SELECT id FROM object WHERE canon = 'M33'").fetchone()[0]
    assert repo.add_object_alias(con, alias_norm="M33", object_id=oid_m33, source="header",
                                 now=NOW_X).created
    sciezka = "R:\\ASTRO_\\LIGHTS\\g.fits"
    fid, lid = _klatka_z_kopia(con, "gest", sciezka)
    item = _przebieg_bazy(con, "R1", fid, lid, sciezka, "NGC598", (None, None, None))
    assert _cofnij_baze(con, item, "R1") is None
    oid_cel = con.execute("SELECT id FROM object WHERE canon = 'NGC598'").fetchone()[0]
    assert _nagrobek(con, "object", oid_cel) is not None

    bez_pary_M33()
    s = run_resolver(con, now=NOW_X)
    assert (s.xref_aliases_rebound, s.alias_conflicts) == (0, 1)
    assert alias_lookup(con)("M33")["object_id"] == oid_m33
    assert _nagrobek(con, "object", oid_cel) is not None
    assert repo.rebind_object_alias(con, alias_norm="M33", object_id=oid_cel,
                                    expected_object_id=oid_m33, now=NOW_X) == (False, 0)
    cel = queries.object_target(con, "M33")
    assert (cel.canon, cel.catalog) == ("NGC598", "NGC")      # nagrobek niósł `catalog` None
    assert queries.xref_reconcile_rows(con) == [("M33", "M33", "NGC598", frozenset({fr}))]
    con.close()


def test_AR135_stan_konfliktow_zdarzenie_tylko_przy_zmianie(tmp_path):
    """`flag_object_alias_conflict_state`: pusto bez historii - cisza; nowy stan - zdarzenie; ten
    sam stan (w innej kolejności) - cisza; zejście do pustki - zdarzenie z `count: 0`."""
    import json
    from horreum import db, repo
    con = db.open_db(str(tmp_path / "s.db"))
    ile = lambda: con.execute(  # noqa: E731
        "SELECT count(*) FROM event WHERE verb = 'object.alias_conflict_state'").fetchone()[0]
    assert repo.flag_object_alias_conflict_state(con, [], NOW_X) is False and ile() == 0
    a, b = ["M33", 1, "NGC598"], ["M1", 2, "NGC1952"]
    assert repo.flag_object_alias_conflict_state(con, [a, b], NOW_X) is True and ile() == 1
    assert repo.flag_object_alias_conflict_state(con, [b, a], NOW_X) is False and ile() == 1
    assert repo.flag_object_alias_conflict_state(con, [], NOW_X) is True and ile() == 2
    ostatni = con.execute("SELECT payload FROM event WHERE verb = 'object.alias_conflict_state' "
                          "ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert json.loads(ostatni) == {"count": 0, "items": []}
    assert repo.flag_object_alias_conflict_state(con, [], NOW_X) is False and ile() == 2
    con.close()
