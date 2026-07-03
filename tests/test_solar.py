"""Oś OBIEKT — Układ Słoneczny i komety (krok 5a; `resolve.solar`).

Czyste testy `resolve_solar(object_raw)` — ciała EXACT, komety IAU/token, kanonizacja (token i desig
tej samej komety → JEDEN canon), bezpieczniki recenzji (F2 „Saturn Nebula"≠planeta, F5 lowercase).
Integracja z `run_resolver` (kind-aware, delta) w `test_resolver.py`.
"""
from horreum.resolve.objects import ObjectIdentity
from horreum.resolve.solar import resolve_solar


# ---- ciała US: dopasowanie EXACT ----

def test_ciala_bare_lapia():
    for raw, canon in [("Jupiter", "Jupiter"), ("ksiezyc", "Moon"), ("Księżyc", "Moon"),
                       ("saturn", "Saturn"), ("MARS", "Mars"), ("Slonce", "Sun"), ("Luna", "Moon")]:
        ident = resolve_solar(raw)
        assert ident is not None and ident.canon == canon, raw
        assert ident.catalog == "solar" and ident.kind == "solar_system" and ident.source == "solar"


def test_saturn_nebula_NIE_jest_planeta():
    """F2 (bezpiecznik): NGC7009 „Saturn Nebula" → None (spada do drabiny deep-sky), NIE planeta Saturn.
    Dopasowanie ciała jest EXACT — substring „Saturn" w „Saturn Nebula" NIE trafia."""
    assert resolve_solar("Saturn Nebula") is None
    assert resolve_solar("Sunflower Galaxy") is None      # „Sun" w środku — nie ciało
    assert resolve_solar("Marsh Nebula") is None          # „Mars" jako prefiks — nie ciało


# ---- komety: oznaczenie IAU ----

def test_kometa_iau():
    for raw in ["C/2023 A3", "C/2023 A3 (Tsuchinshan-ATLAS)", "P/2019 Y4"]:
        ident = resolve_solar(raw)
        assert ident is not None and ident.catalog == "comet" and ident.kind == "comet"
        assert ident.source == "comet"


def test_kometa_iau_lowercase():
    """F5: object_raw bywa lowercase — normalizacja do UPPER przed regexem IAU."""
    ident = resolve_solar("c/2023 a3")
    assert ident is not None and ident.canon == "C/2023 A3 (Tsuchinshan-ATLAS)"


def test_kometa_token():
    for raw, canon in [("Lemmon", "C/2025 A6 (Lemmon)"),
                       ("Comet Lemmon", "C/2025 A6 (Lemmon)"),
                       ("Tsuchinshan", "C/2023 A3 (Tsuchinshan-ATLAS)")]:
        ident = resolve_solar(raw)
        assert ident is not None and ident.canon == canon, raw
        assert ident.catalog == "comet"


def test_kometa_kanonizacja_JEDEN_canon():
    """F3 (tożsamość): token, desig i pełna forma tej samej komety → IDENTYCZNY `canon`
    (inaczej dwa/trzy wiersze `object` na jedną kometę — `object.canon UNIQUE`)."""
    canons = {resolve_solar(r).canon for r in
              ["C/2023 A3", "C/2023 A3 (Tsuchinshan-ATLAS)", "Tsuchinshan", "c/2023 a3"]}
    assert canons == {"C/2023 A3 (Tsuchinshan-ATLAS)"}


def test_kometa_nieznany_desig_zostaje_desig():
    """Nieznana kometa (spoza mapy) → canon = samo oznaczenie IAU (nie gubimy jej)."""
    ident = resolve_solar("C/2019 L3")
    assert ident is not None and ident.canon == "C/2019 L3" and ident.catalog == "comet"


# ---- brak kolizji z katalogiem / brak zeznania ----

def test_brak_kolizji_z_katalogiem():
    """Deep-sky oznaczenia NIE są solarem: M1 (Messier) nie Mars, C1 (Caldwell) nie kometa."""
    assert resolve_solar("M1") is None
    assert resolve_solar("C1") is None
    assert resolve_solar("NGC 7009") is None
    assert resolve_solar("Sh2-155") is None


def test_puste_i_none():
    assert resolve_solar(None) is None
    assert resolve_solar("") is None
    assert resolve_solar("   ") is None


def test_zwraca_object_identity():
    ident = resolve_solar("Jupiter")
    assert isinstance(ident, ObjectIdentity)
    assert ident.alias_norm == "JUPITER"       # norm_alnum(raw)


def test_idempotencja_czysta_funkcja():
    assert resolve_solar("Lemmon") == resolve_solar("Lemmon")
