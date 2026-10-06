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


# ----------------------------------------------------------------- szew rzutu (antypołudnik środka)

# Publiczne punkty: obserwatorium Mt John nad jeziorem Tekapo i Warszawa (centrum miasta).
_TEKAPO = (-43.99, 170.46)
_WARSZAWA = (52.23, 21.01)


def _najdluzszy_odcinek_x(pieces):
    return max((abs(b[0] - a[0]) for p in pieces for a, b in zip(p, p[1:])), default=0.0)


def test_project_line_rozcina_odcinek_przez_szew():
    # Środek 0° - szew na ±180. Odcinek 179 → -179 (2° na wschód) nie może przejść przez cały świat.
    proj = mapproj.LocalProjection(0.0, 0.0)
    pieces = proj.project_line([(170.0, 0.0), (179.0, 10.0), (-179.0, 20.0), (-170.0, 30.0)])
    assert len(pieces) == 2
    kraw = 180.0 * KM
    assert math.isclose(pieces[0][-1][0], kraw) and math.isclose(pieces[1][0][0], -kraw)
    # szerokość na krawędzi interpolowana w połowie odcinka 10° → 20°
    assert math.isclose(pieces[0][-1][1], 15.0 * KM) and math.isclose(pieces[1][0][1], 15.0 * KM)
    assert _najdluzszy_odcinek_x(pieces) < 20 * KM


def test_project_line_bez_szwu_jeden_kawalek():
    proj = mapproj.LocalProjection(50.0, 20.0)
    linia = [(10.0, 40.0), (20.0, 45.0), (30.0, 50.0)]
    pieces = proj.project_line(linia)
    assert pieces == [[proj.project(lat, lon) for lon, lat in linia]]


def test_project_line_szew_poza_180_przy_srodku_przesunietym():
    # Środek widoku ~94° E (Warszawa + Tekapo) - szew na ~86° W, w środku obu Ameryk.
    proj = mapproj.LocalProjection(0.0, 94.0)
    pieces = proj.project_line([(-80.0, 0.0), (-90.0, 0.0)])
    assert len(pieces) == 2
    assert pieces[0][-1][0] * pieces[1][0][0] < 0          # krawędzie po przeciwnych stronach


def test_line_to_px_kontury_bez_kresek_przez_kadr():
    # Odtworzenie zgłoszenia: Warszawa + Tekapo, kadr 1000 × 400. Rzut punkt po punkcie dawał
    # odcinki przez cały kadr; kawałki rozcięte na szwie - żadnego dłuższego niż pół szerokości.
    w, h = 1000, 400
    xf = mapproj.fit_view([_WARSZAWA, _TEKAPO], w, h)
    linie = mapproj.load_land_polylines()
    naiwnie = [[xf.to_px(lat, lon) for lon, lat in l] for l in linie]
    assert _najdluzszy_odcinek_x(naiwnie) > w / 2           # defekt istniał na tym kadrze
    po = [p for l in linie for p in xf.line_to_px(l)]
    assert _najdluzszy_odcinek_x(po) < w / 2


def test_fit_view_margines_px_trzyma_punkt_z_dala_od_krawedzi():
    w, h, pad = 1000, 400, 24.0
    bez = mapproj.fit_view([_WARSZAWA, _TEKAPO], w, h)
    z = mapproj.fit_view([_WARSZAWA, _TEKAPO], w, h, pad_px=pad)
    _, y_bez = bez.to_px(*_TEKAPO)
    _, y_z = z.to_px(*_TEKAPO)
    assert h - y_bez < pad                                  # bez marginesu px - przy krawędzi
    for lat, lon in (_WARSZAWA, _TEKAPO):
        px, py = z.to_px(lat, lon)
        assert pad - 1e-6 <= px <= w - pad + 1e-6 and pad - 1e-6 <= py <= h - pad + 1e-6
    assert z.scale < bez.scale


def _odstep_od_krawedzi(xf, sites, w, h):
    """Najmniejszy odstęp punktów skrajnych od krawędzi kadru (px)."""
    return min(min(px, w - px, py, h - py) for px, py in (xf.to_px(*s) for s in sites))


def test_fit_view_margines_px_plynny_wokol_dawnego_progu():
    # Dwa punkty skrajne (W-E i N-S naraz). Dawny próg 4 × pad = 98 px zrzucał margines do zera:
    # 98 px → ~3,6 px od krawędzi, 99 px → ~26 px. Teraz odstęp rośnie z kadrem BEZ skoku.
    pad = 24.5
    sites = [(50.0, 20.0), (51.0, 22.0)]
    odstep = {d: _odstep_od_krawedzi(mapproj.fit_view(sites, d, d, pad_px=pad), sites, d, d)
              for d in (60, 97, 98, 99, 100, 140)}
    assert odstep[98] >= 98 / 4 - 1e-6                    # ćwierć wymiaru, nie ~3,6 px
    assert abs(odstep[99] - odstep[98]) < 1.0             # bez skoku na progu
    assert odstep[60] < odstep[97] <= odstep[98] <= odstep[99] <= odstep[100] <= odstep[140]
    assert odstep[140] >= pad - 1e-6                      # powyżej progu - pełny margines
    for d in (60, 98):
        assert mapproj.fit_view(sites, d, d, pad_px=pad).scale > 0   # margines nie zjada kadru
