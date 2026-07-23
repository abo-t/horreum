"""Rzut i dane mapy stanowisk (F8, PLAN_ux_redesign §9) — logika Qt-WOLNA (jak `queries`/`facet_model`/
`portfolio`/`theme`): parser konturów GeoJSON, równokątny rzut lokalny lat/lon→km→px, URL OpenStreetMap,
promień punktu. Malowanie i `QDesktopServices` żyją w widżecie (`map_view.py`); ten plik zwraca krotki/
liczby, nigdy `QPointF` — przechodzi bramkę izolowanego clone'a bez PySide6.

Rzut = WŁASNA matematyka mapy (equirectangular lokalny), NIE reużywa haversine/THRESH resolvera — mapa
i `resolve.observatory` mają różne cele (rzut 2D vs dopasowanie punktu do stanowiska). Zakres realny:
astro deep-sky nie stawia sprzętu na biegunie; antymeridian obsłużony przez modulo-unwrap długości
(F8 F9), biegun `cos(lat)→0` świadomie poza (SIN-PRECRUFT, forward-guard jak sentinel (0,0) osi)."""
import json
import math
from importlib import resources

KM_PER_DEG = 111.195            # 2πR/360 dla R=6371 km (stopień szerokości ≈ stopień długości na równiku)
MIN_HALF_KM = 5.0              # minimalny półzakres osi widoku — degeneracja (1 punkt / stanowiska współliniowe)
_ASSET_PKG = "horreum.gui.assets"
_ASSET_NAME = "ne_110m_land.json"

_land_cache = None            # None = nie próbowano; list = załadowane (może [] przy braku assetu)


# ----------------------------------------------------------------------------- parser konturów GeoJSON

def _pts(coords):
    """Lista par [lon,lat] → lista krotek (lon,lat) float; elementy niepoprawne pominięte."""
    out = []
    for c in coords or []:
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            try:
                out.append((float(c[0]), float(c[1])))
            except (TypeError, ValueError):
                pass
    return out


def _line(out, coords):
    p = _pts(coords)
    if len(p) >= 2:                # polilinia < 2 punktów nie ma czego rysować
        out.append(p)


def _collect(node, out):
    """Rekurencyjnie zbierz polilinie z węzła GeoJSON. Polygon/MultiPolygon → ringi jako linie
    (obrys = granica lądowa + wybrzeże, nie wypełnienie). Nieznany typ pominięty (kontur = tło)."""
    if not isinstance(node, dict):
        return
    t = node.get("type")
    if t == "FeatureCollection":
        for f in node.get("features") or []:
            _collect(f, out)
    elif t == "Feature":
        _collect(node.get("geometry") or {}, out)
    elif t == "GeometryCollection":
        for g in node.get("geometries") or []:
            _collect(g, out)
    elif t == "LineString":
        _line(out, node.get("coordinates"))
    elif t in ("MultiLineString", "Polygon"):
        for ring in node.get("coordinates") or []:
            _line(out, ring)
    elif t == "MultiPolygon":
        for poly in node.get("coordinates") or []:
            for ring in poly or []:
                _line(out, ring)


def parse_geojson(text):
    """GeoJSON (dowolny kontener) → lista polilinii `[(lon,lat), …]`. Uszkodzony JSON → `[]`
    (kontur to tło kontekstowe, nigdy crash malowania)."""
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return []
    out = []
    _collect(obj, out)
    return out


def load_land_polylines():
    """Wbudowane kontury (odchudzony Natural Earth) → lista polilinii; cache modułowy (statyczne).
    Brak/uszkodzony asset → `[]` (F8 F11: scatter + OSM działają bez konturów; frozen-miss nie
    zabija widoku osi). Kolejne wywołania nie ponawiają próby (cache trzyma też pustkę)."""
    global _land_cache
    if _land_cache is None:
        try:
            text = resources.files(_ASSET_PKG).joinpath(_ASSET_NAME).read_text(encoding="utf-8")
            _land_cache = parse_geojson(text)
        except (FileNotFoundError, OSError, ModuleNotFoundError):
            _land_cache = []
    return _land_cache


# ----------------------------------------------------------------------------- rzut lokalny + dopasowanie

class LocalProjection:
    """Równokątny rzut lokalny wokół (lat0, lon0): (lat,lon)→(km na wschód, km na północ). Długość
    ścinana `cos(lat0)`; różnica długości brana modulo-360 (najkrótsza — obsługa antymeridianu, F9)."""

    def __init__(self, lat0, lon0):
        self.lat0 = lat0
        self.lon0 = lon0
        self._coslat = math.cos(math.radians(lat0))

    def project(self, lat, lon):
        dlon = (lon - self.lon0 + 180.0) % 360.0 - 180.0     # [-180,180] — najkrótsza różnica długości
        return (dlon * KM_PER_DEG * self._coslat, (lat - self.lat0) * KM_PER_DEG)


class ViewTransform:
    """Dopasowanie rzutu do prostokąta widżetu: `to_px(lat,lon)→(px,py)` (y w górę → piksel w dół),
    `km_to_px`, `scale_bar_km`. Skala JEDNOLITA px/km w obu osiach (koła pozostają kołami)."""

    def __init__(self, proj, scale, width, height, cx, cy):
        self.proj = proj
        self.scale = scale            # px na km
        self.w = width
        self.h = height
        self.cx = cx                  # środek widoku w km (bbox stanowisk)
        self.cy = cy

    def to_px(self, lat, lon):
        x, y = self.proj.project(lat, lon)
        return (self.w / 2 + (x - self.cx) * self.scale, self.h / 2 - (y - self.cy) * self.scale)

    def km_to_px(self, km):
        return km * self.scale

    def scale_bar_km(self):
        """Ładna długość paska skali (1/2/5·10ⁿ km) mieszcząca się ~1/5 szerokości widoku."""
        return _nice_km((self.w / 5) / self.scale) if self.scale > 0 else 1.0


def _nice_km(target):
    if target <= 0:
        return 1.0
    p = 10 ** math.floor(math.log10(target))
    for m in (5, 2, 1):
        if m * p <= target:
            return m * p
    return p


def fit_view(sites, width, height, margin_frac=0.08):
    """`sites` = [(lat,lon), …] (≥1) → `ViewTransform` dopasowany do prostokąta `width×height` px.
    Środek widoku = środek bbox stanowisk (km); półzakres KAŻDEJ osi klampowany do `MIN_HALF_KM`
    OSOBNO (F7 — stanowiska współliniowe/pojedynczy punkt nie dzielą przez 0). Długości rozwinięte
    względem 1. stanowiska (antymeridian, F9). `width`/`height` ≤ 0 → skala 0 (widżet jeszcze bez
    rozmiaru — nic nie maluje)."""
    lat0, lon0 = sites[0]
    ulons = [lon0 + ((lon - lon0 + 180.0) % 360.0 - 180.0) for _, lon in sites]
    lats = [lat for lat, _ in sites]
    clat = (min(lats) + max(lats)) / 2
    clon = (min(ulons) + max(ulons)) / 2
    proj = LocalProjection(clat, clon)

    xs, ys = [], []
    for lat, lon in sites:
        x, y = proj.project(lat, lon)
        xs.append(x)
        ys.append(y)
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    half_x = max((max(xs) - min(xs)) / 2, MIN_HALF_KM) * (1 + margin_frac)
    half_y = max((max(ys) - min(ys)) / 2, MIN_HALF_KM) * (1 + margin_frac)

    if width <= 0 or height <= 0:
        scale = 0.0
    else:
        scale = min(width / (2 * half_x), height / (2 * half_y))
    return ViewTransform(proj, scale, width, height, cx, cy)


def point_radius(frame_count, max_count, r_min=3.0, r_max=11.0):
    """Promień punktu stanowiska (px) rosnący z licznością klatek. Skala LOG (`log1p`) — pojedynczy
    outlier (np. 13 048 klatek vs mediana ~130) nie spłaszcza większości do minimum, jak robiłby `sqrt`
    (wizytator F8 #4). `frame_count=0` → `r_min` (stanowisko istnieje, choć bez klatek); `max_count≤0` → `r_min`."""
    if max_count <= 0 or frame_count <= 0:
        return r_min
    return r_min + (r_max - r_min) * math.log1p(min(frame_count, max_count)) / math.log1p(max_count)


# ----------------------------------------------------------------------------- hit-test (klik/hover, #10)

def nearest_point(points_px, x, y, max_px):
    """Indeks punktu NAJBLIŻSZEGO do (x,y) w progu `max_px` (euklides w px), albo None. Qt-wolny
    (widżet podaje `to_px` wyników) — logika hit-testu żyje tu (IZOLACJA-QT), nie w `paintEvent`.
    Remis → wygrywa późniejszy indeks (bez znaczenia dla selekcji pojedynczego punktu)."""
    best_i, best_d2 = None, float(max_px) ** 2
    for i, (px, py) in enumerate(points_px):
        d2 = (px - x) ** 2 + (py - y) ** 2
        if d2 <= best_d2:
            best_i, best_d2 = i, d2
    return best_i


def points_within(points_px, x, y, radius_px):
    """Indeksy WSZYSTKICH punktów w promieniu `radius_px` od (x,y) — dekolizja etykiet: stanowiska
    oddalone o kilka km zlewają się w px przy zasięgu kontynentalnym (Dom+Będargowo 4 km), a hover
    ma pokazać je wszystkie stackiem, nie jedno na drugim. Próg px → adaptuje się do skali widoku."""
    r2 = float(radius_px) ** 2
    return [i for i, (px, py) in enumerate(points_px)
            if (px - x) ** 2 + (py - y) ** 2 <= r2]


def clamp_label_y0(anchor_y, count, ascent, line_h, height, margin=2.0):
    """Górny baseline pionowego stacku `count` etykiet, wyśrodkowany na `anchor_y`, ale KLAMPOWANY
    tak, by stack nie ucinał się o krawędź widżetu (wiz #10 P2: klaster najbardziej na północ ląduje
    domyślnie u góry kadru — dokładnie tam, gdzie dekolizja jest najczęściej używana). Punkt u góry →
    stack rozwija się w dół; u dołu → w górę; stack wyższy niż widok → dosunięty do góry (`lo`)."""
    y0 = anchor_y + ascent / 2 - (count - 1) * line_h / 2
    lo = margin + ascent + 1
    hi = height - margin - count * line_h + ascent + 1
    return max(lo, min(y0, hi)) if hi >= lo else lo


# ----------------------------------------------------------------------------- link zewnętrzny

def osm_url(lat, lon, zoom=13):
    """URL OpenStreetMap z markerem i przybliżeniem na (lat, lon). Współrzędne `:.6f` (~0.1 m) —
    NIGDY notacja wykładnicza (F6: `f'{1e-05}'`→`'1e-05'` rozbiłoby URL dla punktu ~1 m od zera)."""
    la, lo = f"{lat:.6f}", f"{lon:.6f}"
    return f"https://www.openstreetmap.org/?mlat={la}&mlon={lo}#map={zoom}/{la}/{lo}"
