"""NIEBO — pole widzenia, kadrowanie, widoczność i Księżyc (planer celów, segment T1).

Trzy pytania, na które moduł odpowiada liczbą: czym to sfotografuję (FOV zestawu), czy się zmieści
(kadrowanie i kawałkowanie), kiedy to widać (okno nocy) — plus czwarte, które rozstrzyga PALETĘ:
ile dziś kosztuje Księżyc.

POLE WIDZENIA IDZIE Z ZEZNANIA, NIE Z DEKLARACJI: `telescope.focal_nominal` jest zamrożony przy
pierwszym powołaniu osi (`repo.upsert_telescope`) i żyje per TELESKOP, a pole widzenia należy do
CONFIGU — ten sam ED120R z ASI294MC daje 56,9', a z ASI2600MM 68,4'. Dlatego czytamy `header`
i bierzemy MODĘ KROTKI `(focallen, xpixsz, naxis1, naxis2)`: moda, bo średnia po rozjeździe
wyprodukowałaby liczbę, której nie zeznała żadna klatka; krotki, bo inaczej złożylibyśmy ogniskową
z jednej optyki z geometrią z innej sesji. Wyłącznie `kind='light'` — `master_light` po integracji
jest PRZYCIĘTY i zaniżyłby NAXIS.

BRAK FAKTU NIE JEST ZEREM (lustro D-C-2): config bez ogniskowej, piksela albo geometrii dostaje
`fov_arcmin=None` i KOD powodu — nigdy „typowej" matrycy. NAXIS niosą wyłącznie FITS (XISF trzyma
geometrię w atrybucie `<Image>`, którego zeznanie nie przenosi; `exif.py` nie mapuje jej wcale).

CZAS MUSI BYĆ AWARE: `header.date_obs` jest w Horreum NAIWNY i bywa czasem lokalnym stanowiska
(`gui.queries.facet_nights`), więc nie wolno z niego dziedziczyć założenia o strefie. Naiwny
`datetime` na wejściu = `ValueError`, nie cicha interpretacja — to jedyne miejsce w module, gdzie
pomyłka o godzinę wygląda sensownie i nie zostałaby zauważona.

KSIĘŻYC = MODEL, NIE ILOCZYN (Krisciunas & Schaefer 1991, PASP 103, 1033): faza działa nieliniowo,
wysokość ma PRÓG (pod horyzontem = zero wpływu), a separacja jest niemonotoniczna — minimum tła
wypada ~90-100°, przy 150° rozpraszanie wsteczne znów je podnosi. Wynik podajemy jako KOSZT CZASU
(ile razy dłużej dla tego samego S/N), bo tym astrofotograf mierzy noc.

Qt-wolne, READ-ONLY (zero DML, zero eventów — moduł nie jest klingą), SELECT literałem.
"""
from __future__ import annotations       # `float | None` w ciele dataclassy wybucha na 3.9 (T3 §2)

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .gui.queries import active_observatories
from .resolve._coerce import _to_float, _to_int

# Podatność pasma na KONTINUUM księżycowe względem tła naturalnego w tym samym paśmie.
# HEURYSTYKA INŻYNIERSKA (szerokość pasma skorygowana o to, że tło naturalne w wąskim paśmie
# trzymają linie OH/OI, więc nie spada proporcjonalnie) — NIE pomiar. Parametr do kalibracji;
# archiwum go NIE dostarcza (rozkład faz opisuje pogodę, nie decyzję — sonda 2026-07-31).
BANDS = {"broadband": 1.00, "duoband": 0.25, "narrowband": 0.05}

# Domyślne niebo Będargowa (dominujące stanowisko). Argumenty, nie stałe: Bułgaria i Sardynia
# z tego samego archiwum mają inne tło (D-0731-10 dotyczy KAŻDEGO progu).
V_ZEN_DEFAULT = 20.5      # ciemne tło w zenicie [mag/arcsec^2]
K_EXT_DEFAULT = 0.20      # ekstynkcja [mag/masa powietrza]

_MODE_SHARE_MIN = 0.90    # poniżej => 'mixed_optics'; cicha większość przy dwóch optykach kłamie
_D2R = math.pi / 180.0


# ─────────────────────────────────────────────────────────────── zestaw (config × FOV)

@dataclass(frozen=True)
class Rig:
    """Zestaw = config (teleskop × kamera) z polem widzenia policzonym z zeznania klatek.

    `last_seen` jest AUDYTEM, nie kryterium parku — `rigs(only=...)` bierze jawną listę użytkownika,
    bo „aktualny" nie jest wyprowadzalny z danych (ED120R ma klatki nowsze niż aktualny 76EDPH)."""
    config_id: int
    telescope: str
    camera: str
    focal_mm: float | None
    pixel_um: float | None
    naxis: tuple[int, int] | None
    lights: int
    last_seen: str | None
    mode_share: float
    reason: str | None            # no_focal|no_pixel|no_naxis|mixed_optics

    @property
    def scale_arcsec_px(self):
        if self.focal_mm is None or self.pixel_um is None or self.reason:
            return None
        return 206.265 * self.pixel_um / self.focal_mm

    @property
    def fov_x_arcmin(self):
        """Dłuższy bok kadru."""
        s = self.scale_arcsec_px
        return None if s is None or self.naxis is None else max(self.naxis) * s / 60.0

    @property
    def fov_y_arcmin(self):
        """Krótszy bok kadru."""
        s = self.scale_arcsec_px
        return None if s is None or self.naxis is None else min(self.naxis) * s / 60.0

    @property
    def fov_arcmin(self):
        """Kanon planera: krótszy bok — to on rozstrzyga, czy cel „się mieści"."""
        return self.fov_y_arcmin


def park(con):
    """PARK AKTUALNY z bazy (`telescope.in_park = 1`) albo `None`, gdy nikt nic nie oznaczył.

    JEDYNY właściciel odczytu „co jest w parku" — powierzchnie wołają tę funkcję, nie własny SELECT.
    `None` (nie pusta krotka!) znaczy „park nieustawiony" i wołający ma wtedy liczyć WSZYSTKIE
    teleskopy — pusta krotka znaczyłaby „park pusty" i wygasiła planer do zera wierszy.

    Kanoniczność jak w `rigs`: teleskop scalony w inny odpada nawet oznaczony — park wskazywałby
    wtedy oś, której już nie ma. Kolejność deterministyczna (kanon), bo trafia do raportu."""
    rows = con.execute(
        "SELECT telescop_canon FROM telescope "
        "WHERE in_park = 1 AND merged_into IS NULL ORDER BY telescop_canon").fetchall()
    return tuple(r["telescop_canon"] for r in rows) or None


def rigs(con, only=None):
    """Zestawy z bazy; `only` = jawna lista `telescop_canon` (None => wszystkie, bez udawania,
    że moduł wie, co jest aktualne).

    Filtr idzie `json_each(?)` w STAŁYM literale (bramka AST); kanoniczność osi JAWNIE
    (`telescope_canonical` + `merged_into IS NULL`, wzorem `queries.active_telescopes`) — sam join
    przez widok nie odsiewa scalonych, a scalenie wariantu nazwy wyrzuciłoby zestaw z parku."""
    rows = con.execute(
        # Modę liczymy w Pythonie (SQLite nie ma mody) — SQL oddaje surowe krotki geometrii.
        # `json_extract` na NAXIS daje int (FITS) albo NULL (XISF/RAW); `_to_int` domyka wariant
        # stringowy. Filtr parku siedzi w TYM SAMYM literale (bramka AST zabrania składania SQL
        # ze stałych, nie tylko f-stringów): `?1 IS NULL` => brak filtru, inaczej `json_each`.
        "SELECT cf.id AS config_id, t.telescop_canon AS telescope, cam.model_canon AS camera, "
        "       h.focallen AS focal, h.xpixsz AS pixel, "
        "       json_extract(h.raw_json, '$.NAXIS1') AS nx, "
        "       json_extract(h.raw_json, '$.NAXIS2') AS ny, h.date_obs AS d "
        "FROM config cf "
        "JOIN telescope t ON t.id = cf.telescope_id "
        "JOIN camera cam ON cam.id = cf.camera_id "
        "LEFT JOIN telescope_canonical tc ON tc.canon_id = t.id "
        "JOIN frame f ON f.config_id = cf.id AND f.kind = 'light' "
        "JOIN header h ON h.frame_id = f.id "
        "WHERE t.merged_into IS NULL "
        "  AND (?1 IS NULL OR t.telescop_canon IN (SELECT value FROM json_each(?1))) "
        "ORDER BY cf.id",
        (None if only is None else json.dumps(list(only)),)
    ).fetchall()
    return [_rig_from_rows(cid, grp) for cid, grp in _group_by_config(rows)]


def _group_by_config(rows):
    out = {}
    for r in rows:
        out.setdefault(r["config_id"], []).append(r)
    return out.items()


def _rig_from_rows(config_id, rows):
    """Moda KROTKI `(focal, pixel, nx, ny)`; udział mody < 0,90 => `mixed_optics` i FOV nieznane.

    Modę liczymy WYŁĄCZNIE po krotkach KOMPLETNYCH, a niekompletne wypadają też z mianownika:
    klatka bez NAXIS (XISF, RAW) nie jest „inną optyką" tylko brakiem zeznania, a wliczona
    rozcieńczyłaby udział i wywołała `mixed_optics` na configu o jednej, spójnej optyce
    (zmierzone: RC8×ASI2600MC ma 202 XISF na 2733 klatki => udział spadał do 0,93)."""
    counts, last, complete = {}, None, 0
    missing = {"no_focal": 0, "no_pixel": 0, "no_naxis": 0}
    for r in rows:
        key = (_to_float(r["focal"]), _to_float(r["pixel"]), _to_int(r["nx"]), _to_int(r["ny"]))
        if r["d"] and (last is None or r["d"] > last):
            last = r["d"]
        if key[0] is None:
            missing["no_focal"] += 1
        elif key[1] is None:
            missing["no_pixel"] += 1
        elif key[2] is None or key[3] is None:
            missing["no_naxis"] += 1
        else:
            counts[key] = counts.get(key, 0) + 1
            complete += 1
    if not counts:
        # żadna klatka nie zeznała kompletu — powód bierzemy z NAJCZĘSTSZEGO braku (uczciwy komunikat)
        return Rig(config_id=config_id, telescope=rows[0]["telescope"], camera=rows[0]["camera"],
                   focal_mm=None, pixel_um=None, naxis=None, lights=len(rows), last_seen=last,
                   mode_share=0.0, reason=max(missing, key=lambda k: missing[k]))
    # remis rozstrzyga krotka „większa" — deterministycznie i jawnie, nie kolejnością wierszy
    best = max(sorted(counts, reverse=True), key=lambda k: counts[k])
    focal, pixel, nx, ny = best
    share = counts[best] / complete
    reason = "mixed_optics" if share < _MODE_SHARE_MIN else None
    return Rig(config_id=config_id, telescope=rows[0]["telescope"], camera=rows[0]["camera"],
               focal_mm=focal, pixel_um=pixel,
               naxis=(nx, ny), lights=len(rows), last_seen=last, mode_share=share, reason=reason)


# ─────────────────────────────────────────────────────────────── kadrowanie

@dataclass(frozen=True)
class Framing:
    """`panels == 1` znaczy „jeden kadr". Sufitu rozmiaru NIE MA (D-0731-8): cel większy od kadru
    dostaje liczbę paneli, nie znika z wyników.

    DWIE MIARY WYPEŁNIENIA, KAŻDA Z JEDNYM ZADANIEM:
    - `fill` = rozmiar / KRÓTSZY bok kadru, bez cięcia: klucz porządku „po soczewce” i remisu
      mozaik przy wyborze `best_rig` (sam wybór idzie po `frame_fill`, PL-3 (2), decyzja Zdzinia
      2026-10-05). Przy `panels == 1` potrafi przekroczyć 1 (cel 90' na
      kadrze 103'x69' ma `fill` 1,30 i mieści się w jednym kadrze), dlatego NIE jest miarą dla
      człowieka ani progu.
    - `frame_fill` = WYPEŁNIENIE KADRU (PL-1), 0..1: większy z ilorazów `oś dłuższa / dłuższy bok`
      i `oś krótsza / krótszy bok` - cel leży dłuższą osią wzdłuż dłuższego boku, DOKŁADNIE tak,
      jak liczy panele `framing`. Przy `panels == 1` miara jest z definicji ≤ 1; cięcie do 1 dotyczy
      wyłącznie mozaiki (każdy panel jest wypełniony w całości). To ją pokazuje kolumna
      „Wypełnienie" i ją tnie próg `min_fill` - jedno źródło dla planera, CLI i ekranu (SPOT)."""
    fill: float
    panels_x: int
    panels_y: int
    panels: int
    overlap: float
    frame_fill: float


def _panels_axis(size, fov, overlap):
    """POKRYCIE, nie dzielenie: pierwszy panel daje CAŁE `fov`, każdy następny dokłada
    `fov*(1-overlap)`. Naiwne `ceil(size/(fov*(1-overlap)))` policzyłoby zakładkę także od
    pierwszego kadru i dało 2 panele dla celu równego kadrowi."""
    if size <= fov:
        return 1
    return math.ceil((size - fov) / (fov * (1 - overlap))) + 1


def framing(size_arcmin, rig, *, overlap=0.10, minor_arcmin=None):
    """Kadrowanie celu w zestawie. `minor_arcmin` (oś mniejsza) użyta, gdy podana — cel wydłużony
    (NGC4565: 16,8'×1,9') nie ma powodu dostawać mozaiki liczonej z dłuższej osi także w poprzek."""
    fov_x, fov_y = rig.fov_x_arcmin, rig.fov_y_arcmin
    if fov_x is None or fov_y is None:
        return None
    across = size_arcmin if minor_arcmin is None else minor_arcmin
    px = _panels_axis(size_arcmin, fov_x, overlap)
    py = _panels_axis(across, fov_y, overlap)
    return Framing(fill=size_arcmin / fov_y, panels_x=px, panels_y=py, panels=px * py,
                   overlap=overlap,
                   frame_fill=min(1.0, max(size_arcmin / fov_x, across / fov_y)))


# ─────────────────────────────────────────────────────────────── stanowisko

@dataclass(frozen=True)
class Site:
    observatory_id: int
    name: str | None
    lat_deg: float
    lon_deg: float
    frames: int


def default_site(con):
    """Stanowisko o NAJWIĘKSZEJ liczbie klatek (nie najnowszej — wyjazdy do Bułgarii są nowsze
    od domowych sesji, a planer ma domyślnie planować z domu). Reużywa
    `queries.active_observatories` (SPOT: kanoniczność i licznik już tam mieszkają)."""
    best = None
    for r in active_observatories(con):
        if r["lat"] is None or r["lon"] is None:
            continue
        if best is None or r["frame_count"] > best["frame_count"]:
            best = r
    if best is None:
        return None
    return Site(observatory_id=best["id"], name=best["name"], lat_deg=best["lat"],
                lon_deg=best["lon"], frames=best["frame_count"])


# ─────────────────────────────────────────────────────────────── arytmetyka nieba

def _require_aware(when):
    if when.tzinfo is None or when.tzinfo.utcoffset(when) is None:
        raise ValueError("sky: `when` musi być datetime AWARE (np. datetime.now(timezone.utc)) — "
                         "naiwny czas przesunąłby okno widoczności o godziny bez śladu")
    return when.astimezone(timezone.utc)


def _jd(when):
    """Dzień juliański z chwili AWARE (konwersja do UTC w `_require_aware`)."""
    u = _require_aware(when)
    y, m = u.year, u.month
    if m <= 2:
        y, m = y - 1, m + 12
    a = y // 100
    b = 2 - a + a // 4
    day = u.day + (u.hour + u.minute / 60 + (u.second + u.microsecond / 1e6) / 3600) / 24
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + day + b - 1524.5


def _gmst_deg(jd):
    t = (jd - 2451545.0) / 36525.0
    return (280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t * t) % 360


def _precess_from_j2000(ra_deg, dec_deg, jd):
    """J2000 → układ DATY (Meeus 21.1, niskiej dokładności).

    Bez tego kroku model miesza dwa układy: współrzędne celu przychodzą w J2000 (tak zeznaje
    `header.ra_deg` i tak są katalogi), a Słońce i Księżyc liczymy na datę — rozjazd rośnie
    ~0,014°/rok i w 2026 wynosi już 0,37°, co ZMIERZYŁ arbiter astropy. `tan(dec)` przy biegunie
    wybucha, więc deklinację clampujemy: przy |dec| → 90° rektascensja i tak przestaje wpływać
    na wysokość."""
    y = (jd - 2451545.0) / 365.25
    ra, dec = ra_deg * _D2R, max(-89.5, min(89.5, dec_deg)) * _D2R
    d_ra = (3.07496 + 1.33621 * math.sin(ra) * math.tan(dec)) * y * 15 / 3600
    d_dec = 20.0431 * math.cos(ra) * y / 3600
    return (ra_deg + d_ra) % 360, dec_deg + d_dec


def _alt_from_jd(ra_deg, dec_deg, lat_deg, lon_deg, jd, *, precess=True):
    """Wysokość geometryczna (bez refrakcji — `observatory.elev` jest NULL na wszystkich 11
    stanowiskach, a horyzont lokalny i tak jest poza modelem). `precess=False` dla ciał, które
    już policzyliśmy na datę (Słońce, Księżyc)."""
    if precess:
        ra_deg, dec_deg = _precess_from_j2000(ra_deg, dec_deg, jd)
    h = ((_gmst_deg(jd) + lon_deg - ra_deg) % 360) * _D2R
    dec, lat = dec_deg * _D2R, lat_deg * _D2R
    s = math.sin(dec) * math.sin(lat) + math.cos(dec) * math.cos(lat) * math.cos(h)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def altitude(ra_deg, dec_deg, lat_deg, lon_deg, when):
    """Wysokość celu nad horyzontem [°]. `when` MUSI być aware (patrz nagłówek modułu)."""
    return _alt_from_jd(ra_deg, dec_deg, lat_deg, lon_deg, _jd(when))


def _sun_radec(jd):
    n = jd - 2451545.0
    L = (280.460 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.0000004 * n)
    ra = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) % 360
    return ra, math.degrees(math.asin(math.sin(eps) * math.sin(lam)))


def _moon_radec(jd):
    """Meeus skrócony (główne człony) — < 0,5° na pozycji, co dla kary księżycowej jest o rząd
    wielkości więcej niż potrzeba. Pełna ELP2000 kosztowałaby import astropy.coordinates,
    a ten wymusiłby zmianę `hiddenimports` w spec onefile."""
    t = (jd - 2451545.0) / 36525.0
    Lp = (218.316 + 481267.8813 * t) % 360
    M = math.radians((357.529 + 35999.0503 * t) % 360)
    Mp = math.radians((134.963 + 477198.8676 * t) % 360)
    D = math.radians((297.850 + 445267.1115 * t) % 360)
    F = math.radians((93.272 + 483202.0175 * t) % 360)
    lam = (Lp + 6.289 * math.sin(Mp) + 1.274 * math.sin(2 * D - Mp) + 0.658 * math.sin(2 * D)
           + 0.214 * math.sin(2 * Mp) - 0.186 * math.sin(M) - 0.114 * math.sin(2 * F))
    beta = (5.128 * math.sin(F) + 0.281 * math.sin(Mp + F) - 0.278 * math.sin(F - Mp)
            - 0.173 * math.sin(2 * D - F))
    lam, beta = math.radians(lam % 360), math.radians(beta)
    eps = math.radians(23.439 - 0.0000004 * (jd - 2451545.0))
    ra = math.degrees(math.atan2(math.sin(lam) * math.cos(eps) - math.tan(beta) * math.sin(eps),
                                 math.cos(lam))) % 360
    dec = math.degrees(math.asin(math.sin(beta) * math.cos(eps)
                                 + math.cos(beta) * math.sin(eps) * math.sin(lam)))
    return ra, dec


def moon_position(when):
    """RA, Dec Księżyca [°] dla chwili aware."""
    return _moon_radec(_jd(when))


def separation(ra1, dec1, ra2, dec2):
    """Odległość kątowa [°] między dwoma kierunkami."""
    a, b = dec1 * _D2R, dec2 * _D2R
    c = math.sin(a) * math.sin(b) + math.cos(a) * math.cos(b) * math.cos((ra1 - ra2) * _D2R)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


# ─────────────────────────────────────────────────────────────── Księżyc (K&S 1991)

def _nanolambert(v_mag):
    """mag/arcsec^2 → nanolamberty (K&S wzór 27)."""
    return 34.08 * math.exp(20.7233 - 0.92104 * v_mag)


def _airmass(alt_deg):
    """Masa powietrza wg K&S (3); poniżej horyzontu bez sensu — wołający sprawdza `alt > 0`."""
    z = math.radians(min(90.0 - alt_deg, 90.0))
    return (1 - 0.96 * math.sin(z) ** 2) ** -0.5


@dataclass(frozen=True)
class MoonState:
    """Trzy zmienne (faza × wysokość × separacja) i ich skutek. `delta_mag` jest miarą
    SZEROKOPASMOWĄ do pokazania; decyzję niesie `cost()` — ta sama noc kosztuje 6,5× w LRGB
    i 1,3× w wąskim paśmie."""
    illumination: float
    alt_deg: float
    separation_deg: float
    delta_mag: float
    _sky_nl: float
    _natural_nl: float

    def cost(self, band=1.0):
        """Ile razy dłużej trzeba eksponować dla tego samego S/N. 1,0 = Księżyc nie przeszkadza.
        `band` = `BANDS[...]` albo własna liczba (podatność pasma, §4a briefu)."""
        return 1.0 + (self._sky_nl / self._natural_nl) * band


def moon_state(ra_deg, dec_deg, site, when, *, v_zen=V_ZEN_DEFAULT, k_ext=K_EXT_DEFAULT):
    """Stan Księżyca względem celu. Księżyc pod horyzontem => `cost()==1.0` dla każdej palety —
    to PRÓG, nie zanik; naiwny iloczyn faza×wysokość dałby tu wartość różną od 1."""
    jd = _jd(when)
    m_ra, m_dec = _moon_radec(jd)
    s_ra, s_dec = _sun_radec(jd)
    elong = separation(m_ra, m_dec, s_ra, s_dec)
    k = (1 - math.cos(math.radians(elong))) / 2          # ułamek oświetlonej tarczy
    m_alt = _alt_from_jd(m_ra, m_dec, site.lat_deg, site.lon_deg, jd, precess=False)
    t_alt = _alt_from_jd(ra_deg, dec_deg, site.lat_deg, site.lon_deg, jd)
    sep = separation(*_precess_from_j2000(ra_deg, dec_deg, jd), m_ra, m_dec)
    natural = _nanolambert(v_zen)
    sky = 0.0
    if m_alt > 0 and t_alt > 0:
        alpha = math.degrees(math.acos(max(-1.0, min(1.0, 2 * k - 1))))   # 0° = pełnia
        i_star = 10 ** (-0.4 * (3.84 + 0.026 * abs(alpha) + 4e-9 * alpha ** 4))
        rho = math.radians(sep)
        f_rho = 10 ** 5.36 * (1.06 + math.cos(rho) ** 2) + 10 ** (6.15 - sep / 40)
        sky = (f_rho * i_star * 10 ** (-0.4 * k_ext * _airmass(m_alt))
               * (1 - 10 ** (-0.4 * k_ext * _airmass(t_alt))))
    return MoonState(illumination=k, alt_deg=m_alt, separation_deg=sep,
                     delta_mag=0.0 if sky <= 0 else 2.5 * math.log10(1 + sky / natural),
                     _sky_nl=sky, _natural_nl=natural)


# ─────────────────────────────────────────────────────────────── okno widoczności

@dataclass(frozen=True)
class Window:
    """`night_date` to data WIECZORU — doba przesunięta o −12 h, tak samo jak facet Noc
    (`queries.facet_nights`); planer i grid muszą znaczyć tym słowem to samo.

    `dark_start`/`dark_end` to granice NOCY ŻEGLARSKIEJ (☉ ≤ −12°) i to ONA jest zakresem
    rozważań; `astro_start`/`astro_end` opisują twardą ciemność (≤ −18°) i bywają `None` —
    na 53° N nie istnieje od ~połowy maja do ~końca lipca."""
    night_date: date
    dark_start: datetime | None
    dark_end: datetime | None
    astro_start: datetime | None
    astro_end: datetime | None
    darkness: str                 # astronomical|nautical|none
    max_alt_deg: float            # MAKSIMUM w nocy żeglarskiej — miara widoczności
    hours_above: float
    min_alt_deg: float
    moon: MoonState | None
    reason: str | None            # never_rises|no_astro_night|circumpolar|no_night

    @property
    def visible(self):
        """Czy cel jest tej nocy dostępny: maksimum nocy żeglarskiej ≥ próg (suwak `min_alt`).
        Poza nocą żeglarską wysokości NIE LICZYMY — cel wysoki o zmierzchu cywilnym nie jest
        celem (decyzja Zdzinia 2026-07-31)."""
        return self.max_alt_deg >= self.min_alt_deg


@dataclass(frozen=True)
class NightWindow:
    """Ciemność nocy dla STANOWISKA — fakt niezależny od celu. Wydzielony, bo planer liczy setki
    celów tej samej nocy, a Słońce ma jedną trajektorię (T3 §4a: 289 próbek × N celów to ten sam
    rachunek N razy). Niesie też próbki i JD, żeby wysokość celu liczyć bez powtarzania siatki."""
    night_date: date
    samples: list
    jds: list
    dark_idx: list
    astro_idx: list
    darkness: str                 # astronomical|nautical|none
    step_min: int

    @property
    def dark_start(self):
        return self.samples[self.dark_idx[0]] if self.dark_idx else None

    @property
    def dark_end(self):
        return self.samples[self.dark_idx[-1]] if self.dark_idx else None

    @property
    def astro_start(self):
        return self.samples[self.astro_idx[0]] if self.astro_idx else None

    @property
    def astro_end(self):
        return self.samples[self.astro_idx[-1]] if self.astro_idx else None


def night_window(site, night_date, *, step_min=5):
    """Granice ciemności nocy `night_date` na stanowisku `site` (bez celu).

    Ciemność liczymy PRÓBKOWANIEM (`step_min`, domyślnie 5 min) od południa UTC przez 24 h;
    `night_date` to data WIECZORU. NOC ŻEGLARSKA (☉ ≤ −12°) jest zakresem rozważań, astronomiczna
    (≤ −18°) opisuje jakość nieba i bywa pusta (na 53° N nie istnieje od ~połowy maja do ~końca
    lipca)."""
    start = datetime(night_date.year, night_date.month, night_date.day, 12, tzinfo=timezone.utc)
    steps = int(24 * 60 / step_min) + 1
    samples = [start + timedelta(minutes=step_min * i) for i in range(steps)]
    jds = [_jd(t) for t in samples]
    sun_alt = [_alt_from_jd(*_sun_radec(j), site.lat_deg, site.lon_deg, j, precess=False)
               for j in jds]
    dark_idx = [i for i, a in enumerate(sun_alt) if a <= -12.0]
    astro_idx = [i for i, a in enumerate(sun_alt) if a <= -18.0]
    darkness = "none" if not dark_idx else ("astronomical" if astro_idx else "nautical")
    return NightWindow(night_date=night_date, samples=samples, jds=jds, dark_idx=dark_idx,
                       astro_idx=astro_idx, darkness=darkness, step_min=step_min)


def visibility_window(ra_deg, dec_deg, site, night_date, *, min_alt=30.0, step_min=5,
                      v_zen=V_ZEN_DEFAULT, k_ext=K_EXT_DEFAULT, night=None):
    """Okno nocy dla celu: jak wysoko wejdzie, ile godzin utrzyma próg i jak drogi jest Księżyc.

    ZAKRESEM ROZWAŻAŃ JEST NOC ŻEGLARSKA (☉ ≤ −12°) — zawsze, nie tylko latem jako awaryjny
    zamiennik. Miarą widoczności jest MAKSYMALNA wysokość osiągnięta w tym oknie (`max_alt_deg`),
    a `min_alt` jest progiem-suwakiem, nie stałą. Noc astronomiczna zostaje raportowana osobno
    (`astro_*`, `darkness`, `no_astro_night`), bo mówi o jakości nieba, a nie o dostępności celu.

    `night` = gotowy `NightWindow` (SPOT: ta sama siatka dla wielu celów jednej nocy); None =
    policz na miejscu. `moon` opisuje chwilę KULMINACJI celu w oknie — najlepszy moment nocy,
    więc i uczciwą wycenę."""
    nw = night if night is not None else night_window(site, night_date, step_min=step_min)
    samples, jds, dark_idx, astro_idx = nw.samples, nw.jds, nw.dark_idx, nw.astro_idx
    darkness = "astronomical" if astro_idx else "nautical"
    reason = None if astro_idx else "no_astro_night"
    if not dark_idx:
        return Window(night_date=night_date, dark_start=None, dark_end=None, astro_start=None,
                      astro_end=None, darkness="none", max_alt_deg=-90.0, hours_above=0.0,
                      min_alt_deg=min_alt, moon=None, reason="no_night")

    alts = [(i, _alt_from_jd(ra_deg, dec_deg, site.lat_deg, site.lon_deg, jds[i])) for i in dark_idx]
    best_i, max_alt = max(alts, key=lambda p: p[1])
    # krok bierzemy Z SIATKI, nie z argumentu — przy podanym `night` argument `step_min` opisuje
    # zamówienie wołającego, a godziny liczy siatka, którą realnie dostał
    hours = sum(1 for _, a in alts if a >= min_alt) * nw.step_min / 60.0

    if max_alt <= 0:
        reason = "never_rises"
    elif reason is None and min(a for _, a in alts) > 0:
        reason = "circumpolar"
    return Window(night_date=night_date, dark_start=samples[dark_idx[0]],
                  dark_end=samples[dark_idx[-1]],
                  astro_start=samples[astro_idx[0]] if astro_idx else None,
                  astro_end=samples[astro_idx[-1]] if astro_idx else None,
                  darkness=darkness, max_alt_deg=max_alt, hours_above=hours, min_alt_deg=min_alt,
                  moon=moon_state(ra_deg, dec_deg, site, samples[best_i], v_zen=v_zen, k_ext=k_ext),
                  reason=reason)


def best_month(ra_deg):
    """Miesiąc, w którym cel kulminuje o północy (= „sezon"). Zależy WYŁĄCZNIE od RA — deklinacja
    i szerokość rozstrzygają, CZY cel w ogóle wschodzi, a to mówi `visibility_window`."""
    best, best_d = 1, 400.0
    for m in range(1, 13):
        jd = _jd(datetime(2000, m, 15, 0, tzinfo=timezone.utc))
        opp = (_sun_radec(jd)[0] + 180) % 360
        d = abs((opp - ra_deg + 180) % 360 - 180)
        if d < best_d:
            best, best_d = m, d
    return best
