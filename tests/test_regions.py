"""Oś OBIEKT — kompleksy nieba po WSPÓŁRZĘDNYCH (zgłoszenie #5, paczka P3; `resolve.regions`).

Czyste testy `resolve_region(ra, dec)` (próg, sferyczność, brak-vs-zero, remis) + integracja
z `run_resolver`: KOLEJNOŚĆ DRABINY (zeznanie nagłówka bije współrzędne), brak aliasu na ścieżce
regionu, precedencja decyzji człowieka, idempotencja.

SEDNO: 547 klatek `OBJECT='NGC6992'` w realnym archiwum leży WEWNĄTRZ promienia regionu Veil —
chroni je wyłącznie to, że region jest OSTATNIM szczeblem. `test_zeznanie_naglowka_bije_region`
jest tu testem regresji o najwyższej stawce.
"""
import json

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, repo
from horreum.resolve import regions
from horreum.resolve.regions import angular_sep_deg, load_regions, resolve_region
from horreum.resolver import run_resolver
from horreum.scan import scan_tree

NOW = "2026-07-20T12:00:00"

# Region Veil z `data/regions.json` — kotwice testów (zmiana danych MA tu wybuchnąć).
VEIL_RA, VEIL_DEC, VEIL_R = 312.75, 30.67, 1.8
# Realne celowanie klatek `veil` (0,40° od środka) i klatek `NGC6992` (1,31° — WEWNĄTRZ promienia).
VEIL_FRAME = (312.87, 31.06)
NGC6992_FRAME = (314.0, 31.42)


# ============================================================ czysta funkcja

def test_asset_regions_json_ma_wymagane_klucze():
    regs = load_regions()
    assert len(regs) >= 1
    for reg in regs:
        assert set(reg) >= {"canon", "ra_deg", "dec_deg", "radius_deg"}
        assert isinstance(reg["canon"], str) and reg["canon"]
        assert -90 <= reg["dec_deg"] <= 90 and 0 <= reg["ra_deg"] < 360
        assert reg["radius_deg"] > 0
    assert {r["canon"] for r in regs} == {"Veil"}      # jeden kompleks — reszta świadomie w przeglądzie


def test_srodek_i_realne_klatki_trafiaja():
    for ra, dec in [(VEIL_RA, VEIL_DEC), VEIL_FRAME]:
        ident = resolve_region(ra, dec)
        assert ident is not None and ident.canon == "Veil"
        assert ident.catalog == "region" and ident.kind == "region" and ident.source == "region"
        assert ident.alias_norm is None               # region NIE aliasuje


def test_prog_promienia_wlacznie():
    """Brzeg należy do regionu (`<=`). Przesunięcie po DEC — bez skrótu `cos(dec)`."""
    assert resolve_region(VEIL_RA, VEIL_DEC + VEIL_R - 0.01) is not None
    assert resolve_region(VEIL_RA, VEIL_DEC + VEIL_R + 0.01) is None


def test_odleglosc_jest_sferyczna_nie_euklidesowa():
    """SEDNO F7 recenzji: stopnie RA kurczą się o `cos(dec)`. Punkt oddalony o 2,0° RA przy DEC 30,67°
    leży REALNIE 1,72° od środka, więc MIEŚCI się w promieniu 1,8° — naiwna różnica (2,0 > 1,8)
    odrzuciłaby go. Test przewróci się, gdy ktoś zamieni wzór na euklidesowy."""
    sep = angular_sep_deg(VEIL_RA, VEIL_DEC, VEIL_RA + 2.0, VEIL_DEC)
    assert 1.70 < sep < 1.74                          # 2,0 * cos(30,67) ≈ 1,72
    assert resolve_region(VEIL_RA + 2.0, VEIL_DEC) is not None

    # przy DEC 61° ten sam ruch o 2° RA to już tylko ~0,97° — skurcz 52%
    assert 0.96 < angular_sep_deg(0.0, 61.0, 2.0, 61.0) < 0.98


def test_odleglosc_symetryczna_i_zerowa():
    assert angular_sep_deg(10.0, 20.0, 10.0, 20.0) == 0.0
    a = angular_sep_deg(10.0, 20.0, 200.0, -70.0)
    b = angular_sep_deg(200.0, -70.0, 10.0, 20.0)
    assert a == pytest.approx(b) and a <= 180.0       # klamp asin: brak ValueError na antypodach


def test_brak_wspolrzednych_to_None_ale_zero_to_WARTOSC(monkeypatch):
    """`headers.py:38` deklaruje „0 = wartość": (0,0) to realny punkt nieba (Cetus), NIE brak danych.
    Warunek musi być `is None`, nie falsy — inaczej klatka celowana w (0,0) cicho wypadłaby z regionu."""
    monkeypatch.setattr(regions, "load_regions", lambda: (
        {"canon": "Zero", "ra_deg": 0.0, "dec_deg": 0.0, "radius_deg": 1.0},))
    assert resolve_region(0.0, 0.0) is not None and resolve_region(0.0, 0.0).canon == "Zero"
    assert resolve_region(None, 0.0) is None
    assert resolve_region(0.0, None) is None
    assert resolve_region(None, None) is None


def test_remis_rozstrzyga_canon_nie_kolejnosc_w_jsonie(monkeypatch):
    """Dwa regiony w tej samej odległości → wygrywa mniejszy `canon`, NIE pozycja w pliku danych
    (klucz `(dist, canon)` jak `observatory.nearest_site`). Odwrócenie kolejności nic nie zmienia."""
    beta = {"canon": "Beta", "ra_deg": 10.0, "dec_deg": 0.0, "radius_deg": 5.0}
    alfa = {"canon": "Alfa", "ra_deg": 10.0, "dec_deg": 0.0, "radius_deg": 5.0}
    monkeypatch.setattr(regions, "load_regions", lambda: (beta, alfa))
    assert resolve_region(10.0, 0.0).canon == "Alfa"
    monkeypatch.setattr(regions, "load_regions", lambda: (alfa, beta))
    assert resolve_region(10.0, 0.0).canon == "Alfa"


def test_blizszy_region_wygrywa_z_dalszym(monkeypatch):
    monkeypatch.setattr(regions, "load_regions", lambda: (
        {"canon": "Daleki", "ra_deg": 10.0, "dec_deg": 3.0, "radius_deg": 5.0},
        {"canon": "Bliski", "ra_deg": 10.0, "dec_deg": 0.5, "radius_deg": 5.0}))
    assert resolve_region(10.0, 0.0).canon == "Bliski"


# ============================================================ integracja z run_resolver

def _fits(path, cards, n=0):
    """`n` różnicuje PIKSELE — tożsamość to sha1_data, identyczne dane zlałyby klatki w jedną."""
    hdu = fits.PrimaryHDU(data=np.full((4, 4), n, np.uint16))
    for kw, val in cards:
        hdu.header[kw] = val
    fits.HDUList([hdu]).writeto(str(path))
    return path


CAM = [("INSTRUME", "ZWO ASI2600MC Pro"), ("XPIXSZ", 3.76)]


def _tree(tmp_path, frames):
    """`frames` = [(nazwa, dodatkowe_karty)] — buduje drzewo i skanuje. Zwraca połączenie."""
    con = db.open_db(str(tmp_path / "h.db"))
    tree = tmp_path / "t"; tree.mkdir()
    for i, (name, cards) in enumerate(frames, start=1):
        _fits(tree / f"{name}.fits", CAM + [("IMAGETYP", "LIGHT")] + cards, n=i)
    scan_tree(con, tree, now=NOW)
    return con


def _canon(con, path_like):
    row = con.execute(
        "SELECT o.canon AS canon, f.object_source AS src FROM frame f "
        "JOIN location l ON l.frame_id = f.id LEFT JOIN object o ON o.id = f.object_id "
        "WHERE l.path LIKE ?", (f"%{path_like}%",)).fetchone()
    return (row["canon"], row["src"])


def test_zeznanie_naglowka_bije_region(tmp_path):
    """NAJWYŻSZA STAWKA: klatka z `OBJECT='NGC6992'` celuje 1,31° od środka Veil, czyli WEWNĄTRZ
    promienia 1,8°. Musi zostać NGC6992 — w realnym archiwum wisi na tym 547 klatek. Test przewróci
    się, gdy ktoś przestawi region przed drabinę katalogową."""
    ra, dec = NGC6992_FRAME
    assert angular_sep_deg(ra, dec, VEIL_RA, VEIL_DEC) < VEIL_R      # NAPRAWDĘ w regionie
    con = _tree(tmp_path, [("wschodnia", [("OBJECT", "NGC6992"), ("RA", ra), ("DEC", dec)])])
    run_resolver(con, now=NOW)
    assert _canon(con, "wschodnia") == ("NGC6992", "header")
    con.close()


def test_nazwa_prywatna_w_regionie_dostaje_kompleks(tmp_path):
    """`veil` nie jest oznaczeniem katalogowym ani nazwą potoczną w `_COMMON` → drabina zwraca None,
    a współrzędne dają kompleks. Region NIE zapisuje aliasu, mimo że nazwa w nagłówku była."""
    ra, dec = VEIL_FRAME
    con = _tree(tmp_path, [("veil1", [("OBJECT", "veil"), ("RA", ra), ("DEC", dec)])])
    run_resolver(con, now=NOW)
    assert _canon(con, "veil1") == ("Veil", "region")
    assert con.execute("SELECT count(*) FROM object_alias").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM event WHERE verb='object.aliased'").fetchone()[0] == 0
    con.close()


def test_klatka_bez_nazwy_w_regionie_dostaje_kompleks(tmp_path):
    """83 realne klatki tej samej kampanii nie mają karty OBJECT — łapie je wyłącznie ścieżka
    współrzędnych. To jest zysk, dla którego wybrano tryb po współrzędnych zamiast po nazwie."""
    ra, dec = VEIL_FRAME
    con = _tree(tmp_path, [("bezimienna", [("RA", ra), ("DEC", dec)])])
    run_resolver(con, now=NOW)
    assert _canon(con, "bezimienna") == ("Veil", "region")
    assert con.execute("SELECT count(*) FROM object_alias").fetchone()[0] == 0
    con.close()


def test_poza_regionem_zostaje_w_przegladzie(tmp_path):
    """KONSERWATYWNIE (#5): klatka bez zeznania, celowana w pojedynczy obiekt poza kompleksem,
    NIE dostaje zgadywanego katalogu — zostaje nierozwiązana (25 realnych klatek NGC7635 itd.)."""
    con = _tree(tmp_path, [("daleka", [("RA", 350.2), ("DEC", 61.2)])])
    run_resolver(con, now=NOW)
    assert _canon(con, "daleka") == (None, None)
    con.close()


def test_decyzja_czlowieka_bije_inferencje(tmp_path):
    """F4 recenzji: gdy człowiek przypisze obiekt ręcznie (`object_source='user'`, przyszłe P4),
    kolejny przebieg resolvera NIE MOŻE nadpisać go współrzędnymi. Bez tego strażnika ręczna
    decyzja wracałaby do kompleksu przy każdym skanie — cicho, w kółko."""
    ra, dec = VEIL_FRAME
    con = _tree(tmp_path, [("recznie", [("RA", ra), ("DEC", dec)])])
    run_resolver(con, now=NOW)
    assert _canon(con, "recznie") == ("Veil", "region")

    fid = con.execute("SELECT id FROM frame").fetchone()["id"]
    oid, _ = repo.upsert_object(con, canon="NGC6960", catalog="NGC", kind="deep_sky", now=NOW)
    repo.assign_object(con, frame_id=fid, object_id=oid, object_source="user", now=NOW)

    run_resolver(con, now=NOW)                        # drugi przebieg NIE cofa decyzji
    assert _canon(con, "recznie") == ("NGC6960", "user")
    con.close()


def test_licznik_regionu_w_podsumowaniu(tmp_path):
    """`objects_by_region` = obserwowalność szczebla (semantyka ZAPISU, jak `objects_assigned`:
    drugi przebieg nic nie pisze, więc liczy zero)."""
    ra, dec = VEIL_FRAME
    con = _tree(tmp_path, [("v1", [("OBJECT", "veil"), ("RA", ra), ("DEC", dec)]),
                           ("v2", [("RA", ra), ("DEC", dec)]),
                           ("ngc", [("OBJECT", "NGC6992"), *[("RA", NGC6992_FRAME[0]),
                                                             ("DEC", NGC6992_FRAME[1])]])])
    s1 = run_resolver(con, now=NOW)
    assert (s1.objects_assigned, s1.objects_by_region) == (3, 2)
    s2 = run_resolver(con, now=NOW)
    assert (s2.objects_assigned, s2.objects_by_region) == (0, 0)
    con.close()


def test_region_idempotentny(tmp_path):
    """Drugi przebieg nie mnoży ANI obiektu, ANI przypisań regionu (werby regionu — `event`
    `config.review` mnoży się z założenia, zob. `test_resolver.py`)."""
    ra, dec = VEIL_FRAME
    con = _tree(tmp_path, [("v1", [("OBJECT", "veil"), ("RA", ra), ("DEC", dec)]),
                           ("v2", [("RA", ra), ("DEC", dec)])])
    run_resolver(con, now=NOW)
    snap = [con.execute("SELECT count(*) FROM object WHERE canon='Veil'").fetchone()[0],
            con.execute("SELECT count(*) FROM event WHERE verb='object.upserted'").fetchone()[0],
            con.execute("SELECT count(*) FROM event WHERE verb='object.assigned'").fetchone()[0],
            con.execute("SELECT count(*) FROM frame WHERE object_source='region'").fetchone()[0]]
    run_resolver(con, now=NOW)
    assert snap == [con.execute("SELECT count(*) FROM object WHERE canon='Veil'").fetchone()[0],
                    con.execute("SELECT count(*) FROM event WHERE verb='object.upserted'").fetchone()[0],
                    con.execute("SELECT count(*) FROM event WHERE verb='object.assigned'").fetchone()[0],
                    con.execute("SELECT count(*) FROM frame WHERE object_source='region'").fetchone()[0]]
    assert snap == [1, 1, 2, 2]
    con.close()


def test_kalibracja_nie_dostaje_regionu(tmp_path):
    """KIND-AWARE zostaje nietknięte: flat celowany w region ma `object_id=NULL` (kalibracja nie ma
    obiektu z definicji) — region jest wewnątrz gałęzi light/master_light."""
    ra, dec = VEIL_FRAME
    con = db.open_db(str(tmp_path / "h.db"))
    tree = tmp_path / "t"; tree.mkdir()
    _fits(tree / "flat.fits", CAM + [("IMAGETYP", "FLAT"), ("RA", ra), ("DEC", dec)], n=1)
    scan_tree(con, tree, now=NOW)
    run_resolver(con, now=NOW)
    assert con.execute("SELECT object_id FROM frame").fetchone()["object_id"] is None
    assert con.execute("SELECT count(*) FROM object WHERE canon='Veil'").fetchone()[0] == 0
    con.close()


def test_delta_nie_raportuje_juz_rozwiazanego_veila(tmp_path):
    """Po P3 `veil` znika z delty obiektu — zbiorczy `object.review_summary` nie może go nieść."""
    ra, dec = VEIL_FRAME
    con = _tree(tmp_path, [("v1", [("OBJECT", "veil"), ("RA", ra), ("DEC", dec)]),
                           ("obca", [("OBJECT", "Snapshot")])])
    run_resolver(con, now=NOW)
    summ = con.execute("SELECT payload FROM event WHERE verb='object.review_summary'").fetchall()
    items = {raw for raw, _ in json.loads(summ[0]["payload"])["items"]}
    assert items == {"Snapshot"}                      # `veil` rozwiązany, nie w delcie
    con.close()
