"""Rzut i dane mapy stanowisk (`horreum.gui.mapproj`, F8) — testy Qt-WOLNE (bez `importorskip`, jak
`test_theme`/`test_grid_core`): parser GeoJSON, equirectangular lokalny, dopasowanie z degeneracjami,
URL OSM, promień punktu. Wyjątek malowania łapie się TU (nie w połykającym paintEvent — F8 F10)."""
import math

from horreum.gui import mapproj

KM = mapproj.KM_PER_DEG


# ----------------------------------------------------------------- parser GeoJSON

def test_parse_linestring():
    lines = mapproj.parse_geojson('{"type":"LineString","coordinates":[[0,0],[1,1],[2,2]]}')
    assert lines == [[(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]]


def test_parse_multilinestring():
    lines = mapproj.parse_geojson('{"type":"MultiLineString","coordinates":[[[0,0],[1,0]],[[2,2],[3,3]]]}')
    assert len(lines) == 2


def test_parse_polygon_ring_jako_linia():
    lines = mapproj.parse_geojson('{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,0]]]}')
    assert lines == [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 0.0)]]


def test_parse_multipolygon_wszystkie_ringi():
    txt = ('{"type":"MultiPolygon","coordinates":'
           '[[[[0,0],[1,0],[0,0]]],[[[2,2],[3,2],[2,2]],[[4,4],[5,4],[4,4]]]]}')
    assert len(mapproj.parse_geojson(txt)) == 3            # 1 + 2 ringi


def test_parse_feature_i_geometrycollection():
    fc = ('{"type":"FeatureCollection","features":[{"type":"Feature","geometry":'
          '{"type":"LineString","coordinates":[[0,0],[1,1]]}}]}')
    assert len(mapproj.parse_geojson(fc)) == 1
    gc = ('{"type":"GeometryCollection","geometries":[{"type":"LineString",'
          '"coordinates":[[0,0],[1,1]]},{"type":"LineString","coordinates":[[2,2],[3,3]]}]}')
    assert len(mapproj.parse_geojson(gc)) == 2


def test_parse_nieznany_typ_i_smiec():
    assert mapproj.parse_geojson('{"type":"Point","coordinates":[0,0]}') == []   # nie-linia pominięta
    assert mapproj.parse_geojson("to nie json") == []                            # uszkodzone → []
    assert mapproj.parse_geojson('{"type":"LineString","coordinates":[[0,0]]}') == []  # <2 pkt


# ----------------------------------------------------------------- rzut lokalny

def test_project_center_zero():
    assert mapproj.LocalProjection(50, 20).project(50, 20) == (0.0, 0.0)


def test_project_stopien_szerokosci():
    _, y = mapproj.LocalProjection(50, 20).project(51, 20)
    assert math.isclose(y, KM, rel_tol=1e-9)              # +1° lat ≈ 111 km na północ


def test_project_stopien_dlugosci_na_rowniku():
    x, _ = mapproj.LocalProjection(0, 0).project(0, 1)
    assert math.isclose(x, KM, rel_tol=1e-9)              # +1° lon na równiku ≈ 111 km


def test_project_cos_szerokosci_scina_dlugosc():
    x, _ = mapproj.LocalProjection(50, 20).project(50, 21)
    assert math.isclose(x, KM * math.cos(math.radians(50)), rel_tol=1e-9)


def test_project_antymeridian_modulo():
    x, _ = mapproj.LocalProjection(0, 180).project(0, -179)
    assert math.isclose(x, KM, rel_tol=1e-9)              # -179° to 1° NA WSCHÓD od 180°, nie -359°


# ----------------------------------------------------------------- dopasowanie widoku

def test_fit_view_punkty_w_granicach():
    xf = mapproj.fit_view([(50.0, 20.0), (51.0, 22.0)], 400, 300)
    assert xf.scale > 0
    for lat, lon in [(50.0, 20.0), (51.0, 22.0)]:
        px, py = xf.to_px(lat, lon)
        assert 0 <= px <= 400 and 0 <= py <= 300


def test_fit_view_degeneracja_jeden_punkt():
    xf = mapproj.fit_view([(50.0, 20.0)], 200, 200)      # bez dzielenia przez 0
    assert xf.scale > 0
    px, py = xf.to_px(50.0, 20.0)
    assert math.isclose(px, 100.0, abs_tol=1e-6) and math.isclose(py, 100.0, abs_tol=1e-6)


def test_fit_view_wspolliniowe_ew_nie_dziel_przez_zero():
    # F7: dom↔praca na TEJ SAMEJ szerokości (span_y≈0, span_x>0) — klamp osi Y osobno.
    xf = mapproj.fit_view([(50.0, 20.0), (50.0, 20.1)], 400, 200)
    assert xf.scale > 0
    (p1x, p1y), (p2x, p2y) = xf.to_px(50.0, 20.0), xf.to_px(50.0, 20.1)
    assert math.isclose(p1y, p2y, abs_tol=1e-6)          # ta sama szerokość → ten sam piksel Y
    assert 0 <= p1x <= 400 and 0 <= p2x <= 400


def test_fit_view_antymeridian_unwrap():
    # F9: stanowiska po obu stronach ±180 mają realny span ~2°, nie ~358°.
    xf = mapproj.fit_view([(0.0, 179.0), (0.0, -179.0)], 200, 200)
    p1, p2 = xf.to_px(0.0, 179.0), xf.to_px(0.0, -179.0)
    for px, py in (p1, p2):
        assert 0 <= px <= 200 and 0 <= py <= 200
    assert abs(p1[0] - p2[0]) < 200                       # blisko siebie, nie na przeciwnych krańcach


def test_fit_view_zerowy_rozmiar_skala_zero():
    assert mapproj.fit_view([(50.0, 20.0)], 0, 0).scale == 0.0


def test_scale_bar_km_ladna_wartosc():
    xf = mapproj.fit_view([(50.0, 20.0), (50.5, 20.0)], 500, 500)
    bar = xf.scale_bar_km()
    mantysa = bar / (10 ** math.floor(math.log10(bar)))
    assert round(mantysa, 6) in (1.0, 2.0, 5.0)          # 1/2/5·10ⁿ


# ----------------------------------------------------------------- promień punktu

def test_point_radius_skrajne():
    assert mapproj.point_radius(0, 10) == 3.0             # brak klatek → r_min
    assert mapproj.point_radius(10, 10) == 11.0           # maksimum → r_max
    assert mapproj.point_radius(5, 0) == 3.0              # max_count≤0 → r_min


def test_point_radius_monotoniczny():
    assert 3.0 < mapproj.point_radius(3, 10) < mapproj.point_radius(8, 10) < 11.0


# ----------------------------------------------------------------- URL OSM

def test_osm_url_format():
    url = mapproj.osm_url(50.1, 20.2)
    assert "mlat=50.100000" in url and "mlon=20.200000" in url and "#map=13/" in url


def test_osm_url_bez_notacji_wykladniczej():
    # F6: współrzędna ~1 m od zera nie może wpaść w `1e-05` (rozbija URL).
    url = mapproj.osm_url(0.000001, -0.00001)
    assert "e" not in url.split("#")[0].split("?")[1]     # w części query brak wykładnika


# ----------------------------------------------------------------- hit-test (klik/hover, #10)

_PTS = [(100.0, 100.0), (105.0, 103.0), (200.0, 50.0)]   # dwa blisko (klaster), jeden daleko


def test_nearest_point_w_progu():
    assert mapproj.nearest_point(_PTS, 101.0, 99.0, 14.0) == 0     # najbliżej #0
    assert mapproj.nearest_point(_PTS, 198.0, 52.0, 14.0) == 2     # najbliżej #2


def test_nearest_point_poza_progiem_none():
    assert mapproj.nearest_point(_PTS, 150.0, 150.0, 14.0) is None  # nic w promieniu 14 px
    assert mapproj.nearest_point([], 0.0, 0.0, 14.0) is None        # pusta lista


def test_nearest_point_wybiera_blizszy_z_klastra():
    # kursor między dwoma bliskimi punktami, minimalnie bliżej #1
    assert mapproj.nearest_point(_PTS, 104.0, 102.0, 20.0) == 1


def test_points_within_klaster_dekolizji():
    # próg 16 px łapie #0 i #1 (odległe ~5.8 px), NIE #2 (setki px)
    assert set(mapproj.points_within(_PTS, 100.0, 100.0, 16.0)) == {0, 1}
    assert mapproj.points_within(_PTS, 200.0, 50.0, 16.0) == [2]     # daleki sam


def test_clamp_label_y0_trzyma_stack_w_kadrze():
    asc, lh, h = 12.0, 16.0, 300.0
    # punkt u GÓRY (anchor 3) → stack zsunięty w dół, górna etykieta nie ucięta (top ≥ 0)
    y0_top = mapproj.clamp_label_y0(3.0, 2, asc, lh, h)
    assert y0_top - asc - 1 >= 0
    # punkt u DOŁU (anchor 297) → dolna etykieta nie wyłazi pod spód (bottom ≤ h)
    y0_bot = mapproj.clamp_label_y0(297.0, 2, asc, lh, h)
    assert y0_bot + 2 * lh - asc - 1 <= h
    # punkt w ŚRODKU → wyśrodkowany bez klampu
    assert abs(mapproj.clamp_label_y0(150.0, 1, asc, lh, h) - (150.0 + asc / 2)) < 1e-9


# ----------------------------------------------------------------- wbudowany asset

def test_load_land_polylines_asset():
    lines = mapproj.load_land_polylines()
    assert len(lines) > 100                               # odchudzony NE 110m ≈ 288 polilinii
    assert all(len(p) >= 2 for p in lines)
