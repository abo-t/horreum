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
