"""Oś TELESKOP: normalize_focratio (§3.3) + cluster_signatures (§3.4/§Etap 5).
Kryteria §5.4/§5.5: A140R (f/5.6) ODDZIELNIE od ED120 (f/6.4) mimo nakładających się ogniskowych;
warianty tego samego teleskopu sklejone; FOCRATIO>16 (apertura) odzyskany z ogniskowej."""
import pytest

from horreum.resolve.telescopes import cluster_signatures, normalize_focratio


# --- normalize_focratio (§3.3) ---

@pytest.mark.parametrize("raw, focallen, expected", [
    (5.6, 784, (5.6, "ok")),                 # realny stosunek w zakresie 2..16
    (6.4, 768, (6.4, "ok")),
    (16.0, 1000, (16.0, "ok")),              # brzeg górny
    (2.0, 100, (2.0, "ok")),                 # brzeg dolny
])
def test_normalize_focratio_ok(raw, focallen, expected):
    assert normalize_focratio(raw, focallen) == expected


def test_normalize_focratio_recovered_z_apertury():
    """FOCRATIO>16 bywa APERTURĄ (mm) — odzysk stosunku z ogniskowej (firsthand: 120/150/200)."""
    norm, src = normalize_focratio(200.0, 1624.0)   # RC8: ogniskowa/apertura
    assert src == "recovered" and norm == pytest.approx(8.12, abs=0.01)


@pytest.mark.parametrize("raw, focallen", [
    (None, 784),       # brak FOCRATIO (master XISF) → review, nie crash (W4)
    (200.0, None),     # >16 bez ogniskowej → nie ma z czego odzyskać
    (1.5, 784),        # f < 2 → nierealne
    (0.0, 784),        # zero → review
])
def test_normalize_focratio_review(raw, focallen):
    assert normalize_focratio(raw, focallen) == (None, "review")


# --- cluster_signatures (§3.4): f/ pierwszorzędny, ogniskowa wtórna ---

def test_cluster_a140r_oddzielnie_od_ed120():
    """SEDNO §5.4: różne f/ (5.6 vs 6.4, Δ0.8>0.3) → DWA teleskopy, mimo nakładających się
    ogniskowych (784 vs 768)."""
    clusters = cluster_signatures([(5.6, 784.0), (6.4, 768.0)])
    assert len(clusters) == 2
    assert {c["f_ratio_nominal"] for c in clusters} == {5.6, 6.4}


def test_cluster_warianty_tego_samego_sklejone():
    """Ten sam f/ i bliska ogniskowa (Δf/ 0.05≤0.3, Δfocal 2≤15) → JEDEN teleskop (centroid)."""
    clusters = cluster_signatures([(8.0, 1624.0), (8.05, 1626.0)])
    assert len(clusters) == 1
    assert clusters[0]["f_ratio_nominal"] == pytest.approx(8.02, abs=0.01)
    assert clusters[0]["focal_nominal"] == 1625
    assert clusters[0]["suspect"] is False


def test_cluster_ten_sam_f_rozna_ogniskowa_rozdzielone():
    """Ten sam f/ (5.6), ale ogniskowa daleko (700 vs 800, Δ100>15) → DWA teleskopy
    (ogniskowa rozdziela w obrębie tego samego f/)."""
    clusters = cluster_signatures([(5.6, 700.0), (5.6, 800.0)])
    assert len(clusters) == 2


def test_cluster_suspect_chaining():
    """Single-linkage chaining: 780–790–800 połączone (sąsiedzi ≤15), ale rozpiętość 20>15 →
    JEDEN klaster oznaczony suspect (do review)."""
    clusters = cluster_signatures([(5.6, 780.0), (5.6, 790.0), (5.6, 800.0)])
    assert len(clusters) == 1
    assert clusters[0]["suspect"] is True


def test_cluster_pojedyncza_i_pusta():
    assert cluster_signatures([(5.6, 784.0)]) == [
        {"f_ratio_nominal": 5.6, "focal_nominal": 784, "members": [(5.6, 784.0)], "suspect": False}]
    assert cluster_signatures([]) == []
