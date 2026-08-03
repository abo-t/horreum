"""ASSET KATALOGU CELÓW (planer, T2) — bateria pilnuje PLIKU, który leży w repo.

Producentem assetu jest `scripts/build_catalog.py` (dev, sieć) i bateria go NIE uruchamia. Testuje
to, co realnie jedzie w wheelu i we frozen: `horreum/data/targets_core.json` + `targets_cirrus.json`
+ `resolve/data/objects_own.json`. Te same inwarianty co falsyfikatory budowy (brief
`PLAN_planer_T2_katalog.md` §7), bo asset można też podmienić ręcznie — a wtedy skrypt nie ma nic
do powiedzenia.

PLIK CZŁOWIEKA NIESIE DWIE KLASY REKORDÓW (D-OW-1/E′): rekordy-CELE (komplet `t`/`r`/`d`/`a`)
i rekordy-NAZWY (żadnego z nich — obiekt, którego planer nie planuje, ale resolver zna). Dlatego
inwarianty dzielą się na dwie rodziny: TOŻSAMOŚĆ (unikalność kanonów, aliasy) liczy się na SUMIE
wszystkich rekordów, a GEOMETRIA (pozycja, rozmiar, typ, epoka) wyłącznie na celach. Wrzucenie
rekordu-nazwy do testu geometrii dałoby `KeyError` zamiast wyniku.

NAJWYŻSZA STAWKA: styk z osią OBIEKT. Kanon assetu powstaje TĄ SAMĄ funkcją co kanon resolvera
(`xref(catalog_canon(...))`), więc `Sh2-184` z katalogu i `NGC281` z archiwum to JEDEN cel.
Zerwanie tej reguły nie wywala niczego — po prostu sfotografowany obiekt zaczyna udawać
„nigdy nie fotografowany". Stąd `test_kanony_unikalne_w_sumie_plikow` i test aliasów.
"""
import json
import math
from importlib import resources

import pytest

from horreum import targets
from horreum.resolve import objects as ro
from horreum.resolve.catalog import catalog_canon, xref

LAYERS = ("core", "cirrus")

# Klasy typów dopuszczone do puli (mgławice/galaktyki/ciemne). Gromada bez mgławicy jest
# świadomie odrzucona, `Cl+N` świadomie zostawiona.
TYPES_OK = {"G", "GPair", "GTrpl", "GGroup",
            "Neb", "EmN", "HII", "RfN", "Cl+N", "SNR", "PN", "DrkN"}

FLOOR_ARCMIN, FLOOR_DARK_ARCMIN = 3.0, 8.0


def _load(name):
    """Warstwa → surowy asset. Pakiet bierzemy z mapy `targets._ASSET`, nie z literału: po E′
    plik człowieka mieszka w assetach RESOLVERA, a test, który zna własną ścieżkę, przestałby
    pilnować tego, co naprawdę czyta aplikacja."""
    package, filename = targets._ASSET[name]
    text = resources.files(package).joinpath(filename).read_text(encoding="utf-8")
    return json.loads(text)


@pytest.fixture(scope="module")
def assets():
    return {name: _load(name) for name in LAYERS}


@pytest.fixture(scope="module")
def wszystkie(assets):
    """Wszystkie rekordy z trzech plików — inwarianty TOŻSAMOŚCI liczą się na SUMIE, nie per plik:
    `LDN1174` i `NGC7023` to jeden obiekt (`catalog_xref.json`), a leżały w dwóch warstwach.
    Rekordy-nazwy SĄ tutaj: kanon `LMC` ma być unikalny wobec generowanych tak samo jak każdy inny."""
    out = [r for a in assets.values() for r in a["targets"]]
    return out + _load("curated")["targets"]


@pytest.fixture(scope="module")
def wszystkie_cele(wszystkie):
    """Podzbiór z kompletem pól celu — jedyna populacja, na której GEOMETRIA ma sens. Rekord-nazwa
    nie ma pozycji ani rozmiaru z definicji klasy, więc test geometrii dostałby na nim `KeyError`,
    czyli błąd narzędzia zamiast werdyktu o assecie."""
    return [r for r in wszystkie
            if targets.target_fields_present(r) == len(targets.TARGET_FIELDS)]


def _sep_arcmin(a, b):
    ra1, d1, ra2, d2 = map(math.radians, (a["r"], a["d"], b["r"], b["d"]))
    c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(ra1 - ra2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c)))) * 60


def _by_canon(rows):
    return {r["c"]: r for r in rows}


# ============================================================ schemat i rodowód

def test_asset_ma_meta_z_rodowodem_i_licencja(assets):
    """`_meta` to RODOWÓD: bez niego za pół roku nikt nie odtworzy, czym jest ten plik — a dane
    pochodne z OpenNGC niosą CC-BY-SA-4.0 i licencja musi jechać razem z nimi."""
    for name, a in assets.items():
        meta = a["_meta"]
        assert meta["layer"] == name
        assert meta["floor_arcmin"] == FLOOR_ARCMIN
        assert "CC-BY-SA-4.0" in meta["license"]
        assert {s["key"] for s in meta["sources"]} >= {"ngc", "sh2", "lbn", "ldn", "vdb", "green"}
        assert any("CC-BY-SA-4.0" == s["license"] for s in meta["sources"])


def test_rekordy_maja_pozycje_rozmiar_i_typ_z_dopuszczonej_klasy(wszystkie_cele):
    for r in wszystkie_cele:
        assert r["c"] and isinstance(r["c"], str)
        assert r["t"] in TYPES_OK, f"{r['c']} ma typ {r['t']} spoza klas planera"
        assert 0 <= r["r"] < 360 and -90 <= r["d"] <= 90, f"{r['c']} poza sferą"
        assert r["a"] > 0
        if "b" in r:
            assert 0 < r["b"] <= r["a"] + 1e-9, f"{r['c']}: oś mniejsza większa od większej"
        if "mb" in r:
            assert r["mb"] is True and "m" in r


def test_podloga_rozmiaru_trzyma_zapas_pod_suwakiem(assets):
    """Podłoga jest TECHNICZNA (3'/8'), nie „wykonalność" — najniższe położenie suwaka w T3 to
    4'/10', więc asset musi mieć pod nim zapas. Podłoga wyższa od suwaka cicho zwróciłaby pustkę."""
    for a in assets.values():
        for r in a["targets"]:
            floor = FLOOR_DARK_ARCMIN if r["t"] == "DrkN" else FLOOR_ARCMIN
            assert r["a"] >= floor - 1e-9, f"{r['c']} ({r['a']}') poniżej podłogi {floor}'"


def test_warstwa_cirrus_jest_osobnym_plikiem(assets):
    """D-0731-9: LBN/LDN są domyślnie wyłączone, więc nie ma powodu parsować ich przy starcie.
    Rozstrzyga ŹRÓDŁO ZWYCIĘZCY grupy — dlatego `LDN1174` jedzie w rdzeniu jako część `NGC7023`."""
    assert len(assets["core"]["targets"]) > 1000
    assert len(assets["cirrus"]["targets"]) > 1500
    core = _by_canon(assets["core"]["targets"])
    assert core["NGC7023"]["t"] == "Neb" and "LDN1174" in core["NGC7023"]["n"]
    # w cirrusie zwycięzcą grupy jest zawsze wpis Lyndsa — inaczej warstwa przestaje znaczyć
    # „obłoki, których domyślnie nie widać" i zaczyna ukrywać cele katalogowe
    assert all(r["c"].startswith(("LBN", "LDN")) for r in assets["cirrus"]["targets"])


# ============================================================ tożsamość (styk z osią OBIEKT)

def test_kanony_unikalne_w_sumie_plikow(wszystkie):
    """Inwariant liczony na SUMIE: kolizja po `xref` potrafi leżeć MIĘDZY warstwami
    (`LDN1174` w cirrusie vs `NGC7023` w rdzeniu), a kontrola per plik by jej nie zobaczyła."""
    seen = {}
    for r in wszystkie:
        assert r["c"] not in seen, f"kanon {r['c']} dwa razy"
        seen[r["c"]] = r


def test_kanon_powstaje_ta_sama_funkcja_co_w_resolverze(wszystkie):
    """Kanon rozpoznawalny gramatyką MUSI być formą po `xref` — inaczej `Sh2-184` z katalogu
    i `NGC281` z archiwum byłyby dwoma celami i jeden udawałby nigdy nie fotografowany."""
    for r in wszystkie:
        c = catalog_canon(r["c"])
        if c is not None:
            assert xref(c) == r["c"], f"{r['c']} nie jest formą kanoniczną (oczekiwane {xref(c)})"


def test_zaden_alias_nie_wskazuje_na_kanon_innego_rekordu(wszystkie):
    """Gdyby wskazywał, T3 policzyłby pokrycie tej samej klatki dwa razy — raz przy celu,
    raz przy jego aliasie żyjącym jako osobny rekord."""
    kanony = {r["c"] for r in wszystkie}
    for r in wszystkie:
        for a in r.get("n", ()):
            c = catalog_canon(a)
            if c and xref(c) in kanony:
                assert xref(c) == r["c"], f"alias {a} rekordu {r['c']} to cudzy kanon"


def test_przegrany_scalenia_zostaje_w_aliasach(wszystkie):
    """Scalanie nie ma prawa gubić oznaczeń: użytkownik szuka `Sh2-190`, a rekord nazywa się
    `IC1805`. Kotwice zmierzone na realnym materiale."""
    b = _by_canon(wszystkie)
    assert "Sh2-190" in b["IC1805"]["n"]           # klucz KANON (xref), mimo 150' vs 60'
    assert "Sh2-184" in b["NGC281"]["n"]           # klucz KANON — forma sprzed xref
    assert "LBN487" in b["NGC7023"]["n"]           # klucz ALIAS KATALOGU (OpenNGC Identifiers)
    assert "LBN807" in b["IC410"]["n"]             # ten kanon MA klatki w archiwum
    assert "G074.0-08.5" in b["NGC6960"]["n"]      # klucz POZYCJA — Green nie zna gramatyki


# ============================================================ kotwice merytoryczne

def test_ctb1_jest_w_assecie_z_katalogu_greena(wszystkie):
    """Największy projekt archiwum (60,4 h) nie ma numeru NGC/IC ani Sh2 — jest wyłącznie
    u Greena jako `G116.9+00.2`. Bez reguły „kanon z pola Names" wszedłby pod oznaczeniem
    galaktycznym i NIE skleiłby się z `object.canon`."""
    ctb = _by_canon(wszystkie)["CTB1"]
    assert ctb["t"] == "SNR" and abs(ctb["a"] - 34.0) < 0.5


def test_cel_wiekszy_od_kadru_zostaje_w_assecie(wszystkie):
    """D-0731-8: sufitu rozmiaru NIE MA. Veil 210' nie mieści się w żadnym zestawie parku,
    a jest realnym celem — kawałkowanie liczy `sky.framing`, asset nie ma prawa go ukryć."""
    b = _by_canon(wszystkie)
    assert b["NGC6960"]["a"] >= 200
    assert b["Sh2-131"]["a"] >= 150


def test_maly_cel_w_wielkim_oblokiem_zostaje_osobnym_celem(wszystkie):
    """BRAMKA PROPORCJI: `IC1396` (14') leży 0,4' od środka `Sh2-131` (170'). Bez bramki mniejszy
    zniknąłby wchłonięty — a to dwa różne zdjęcia, dwa różne kadrowania."""
    b = _by_canon(wszystkie)
    assert _sep_arcmin(b["IC1396"], b["Sh2-131"]) < 2.0
    assert b["IC1396"]["a"] < b["Sh2-131"]["a"] / 2


@pytest.mark.parametrize("a,b,tol,tor", [("Sh2-236", "IC410", 5.0, "B1900"),
                                         ("LBN654", "IC1805", 25.0, "B1950")])
def test_epoka_pozycji_jest_j2000_na_obu_torach(wszystkie, a, b, tol, tor):
    """Sh2 niesie B1900, LBN/LDN B1950 — surowe kolumny leżą w pliku źródłowym OBOK policzonych
    przez VizieR J2000. Pomyłka o jedną kolumnę to 0,5-1,2° i wygląda całkowicie normalnie.
    Kotwicą jest para sklejona WYŁĄCZNIE pozycją (nie przez `xref`), inaczej test byłby ślepy."""
    idx = _by_canon(wszystkie)
    rec_a = idx.get(a) or next(r for r in wszystkie if a in r.get("n", ()))
    rec_b = idx.get(b) or next(r for r in wszystkie if b in r.get("n", ()))
    if rec_a is rec_b:
        return                       # scalone w jeden rekord => tym bardziej blisko siebie
    assert _sep_arcmin(rec_a, rec_b) <= tol, f"tor {tor} rozjechany"


# ================================================ objects_own (plik człowieka, D-OW-1/E′)

def test_slownik_ma_uzasadnienie_i_proweniencje():
    """Wpis ręczny bez `why`/`provenance` jest nieodróżnialny od zgadywanki — a `size_source`
    mówi wprost, że rozmiar bywa oszacowaniem, nie pomiarem (SIN-UNSOURCED). `size_source` i `t`
    dotyczą WYŁĄCZNIE rekordów-celów: rekord-nazwa rozmiaru nie ma i mieć nie musi."""
    cur = _load("curated")["targets"]
    assert cur, "słownik nie może być pusty — WR134 jest dowodem, że klasa celów bez numeru istnieje"
    for r in cur:
        assert r["why"] and r["provenance"]
        if targets.target_fields_present(r) == len(targets.TARGET_FIELDS):
            assert r["size_source"] in ("catalog", "user")
            assert r["t"] in TYPES_OK


def test_slownik_ma_dokladnie_dwie_klasy_rekordow():
    """Rekord CZĘŚCIOWY (część pól celu) nie jest trzecią klasą, tylko błędem pliku: przeszedłby
    filtr loadera jako cel i wybuchł dopiero na koercji `_target`, daleko od przyczyny."""
    for r in _load("curated")["targets"]:
        n = targets.target_fields_present(r)
        assert n in (0, len(targets.TARGET_FIELDS)), \
            f"{r['c']}: {n} z {len(targets.TARGET_FIELDS)} pól celu — ani cel, ani nazwa"


def test_slownik_niesie_lmc_jako_rekord_nazwe():
    """Sztandarowy przypadek klasy: 36 klatek RAW, nagłówek EXIF milczy o obiekcie i o pozycji,
    a deklinacja −69,8° ze Szczecina nigdy nie wschodzi — więc kanon TAK, cel NIE."""
    lmc = _by_canon(_load("curated")["targets"])["LMC"]
    assert targets.target_fields_present(lmc) == 0
    assert "Large Magellanic Cloud" in lmc["n"]
    assert catalog_canon("LMC") is None, "gdyby gramatyka katalogowa go znała, wpis byłby zbędny"


def test_curated_niesie_wr134_bo_zaden_katalog_go_nie_ma(assets):
    """Bańka Wolfa-Rayeta nie ma numeru w ŻADNYM z sześciu źródeł; najbliższy wpis to `LBN182`
    (90') w 0,37° — czyli warstwa cirrus, domyślnie wyłączona."""
    wr = _by_canon(_load("curated")["targets"])["WR134"]
    assert wr["size_source"] == "user"
    assert not any("WR" in r["c"].upper() for a in assets.values() for r in a["targets"])


def test_nazwy_slownika_nie_kolidują_z_COMMON_ani_z_gramatyką():
    """Trzeci człon bramki §4/5, którego brakowało („unikalność NAZW `n` wobec aliasów i `_COMMON`").

    Nazwa, którą łapie wcześniejszy szczebel drabiny, czyni wpis słownika MARTWYM: `_common_canon`
    albo `catalog_canon` odpowie pierwszy, a wpis nigdy się nie odezwie — bez jednego sygnału.
    Gorzej: `sync_own_aliases` mimo to zasieje alias na swój obiekt albo zgłosi kolizję, więc jedno
    pytanie dostanie dwie odpowiedzi. Kolizję WEWNĄTRZ pliku łapie `_own_index`; ta jest o kolizji
    z KODEM."""
    for r in _load("curated")["targets"]:
        for nazwa in (r["c"], *(r.get("n") or ())):
            assert ro._common_canon(nazwa) is None, \
                f"{nazwa!r} (wpis {r['c']}) łapie _COMMON — szczebel słownika nigdy się nie odezwie"
            assert catalog_canon(nazwa) is None, \
                f"{nazwa!r} (wpis {r['c']}) jest oznaczeniem katalogowym — wpis w słowniku martwy"


def test_slownik_deklaruje_rodzaj_i_katalog_zgodne_z_osią():
    """`kind` i `catalog` lecą WPROST do `object` i wypływają do facetu, nazw plików
    (`naming.py`) oraz drzewa projekcji — więc kształt tych pól jest kontraktem, nie ozdobą."""
    from horreum.resolve.objects import OBJECT_KINDS
    for r in _load("curated")["targets"]:
        assert (r.get("kind") or "own") in OBJECT_KINDS, f"{r['c']}: rodzaj spoza OBJECT_KINDS"
        assert r.get("catalog") is None, \
            f"{r['c']}: obiekt spoza gramatyki katalogowej nie ma prawa deklarować katalogu"
