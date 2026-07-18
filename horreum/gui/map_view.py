"""Widżet mapy stanowisk (F8, PLAN_ux_redesign §9) — QPainter scatter kanonicznych stanowisk na tle
konturów Natural Earth. Warstwa widżetów (whitelist `test_gui_isolation`): cała matematyka rzutu/parser
żyje w Qt-wolnym `mapproj`, tu zostaje malowanie. GŁUPI malarz (NARROW, wzorzec `FacetRail`/
`SelectionBar`): dane wchodzą seterami, ZERO SQL/`repo`, zero orkiestracji zaznaczenia (to robi
`ObservatoryAxisView` — właściciel selekcji tabeli). Bez WebEngine/kafli (§0 FROZEN).

Motyw wzorcem F6 (`facets.use_theme`): modułowe `use_theme` czyta `theme.map_colors`, wołane z
`apply_theme` na starcie (auto-init pod pierwszy `paintEvent`) i przy przełączeniu; `refresh_theme()`
wymusza repaint. Pierścień klastra 4 km POZA v1 (F8 §9/F2, decyzja Zdzin 2026-07-18 — na fit-all
subpikselowy)."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from horreum.gui import mapproj, theme

# Kolory mapy z motywu (Qt-wolny `theme.map_colors`), wypalone w QColor. Zmiana motywu → `use_theme`
# (z `apply_theme`) + `refresh_theme()` na widżecie (QPainter nie repaintuje sam — jak grid viewport).
_MAP_COLORS: dict[str, QColor] = {}


def use_theme(name):
    """Przeładuj kolory mapy z motywu (klucze bg/land/site/site_selected/scale)."""
    _MAP_COLORS.update({k: QColor(v) for k, v in theme.map_colors(name).items()})


use_theme(theme.DEFAULT)         # auto-init pod pierwszy paintEvent (F8 F1 — inaczej pusty dict)


class SitesMapView(QWidget):
    """Scatter stanowisk (rozmiar punktu = f(frame_count)) na tle konturów, z wyróżnieniem zaznaczenia
    i paskiem skali. `set_sites(rows)` = wynik `active_observatories`; `set_selected(oid)` sprzęga
    z tabelą osi. Bez własnej noty pustego stanu (nota niesie tabela — `obs_empty`, F8 F12)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sites = []             # [(oid, name, lat, lon, frame_count)]
        self._selected = None
        self._xf = None              # mapproj.ViewTransform | None
        self._land_px = []           # cache pre-rzutowanych konturów [QPolygonF] per bieżący _xf (F3)
        self._max_count = 0
        self.setMinimumHeight(160)

    # -------------------------------------------------------------- setery danych
    def set_sites(self, rows):
        """Stanowiska do narysowania (kanoniczne z read-modelu). Wiersze bez lat/lon pominięte
        (defensywnie — schema NOT NULL, ale mapa nie zakłada)."""
        self._sites = [(r["id"], r["name"], r["lat"], r["lon"], r["frame_count"])
                       for r in rows if r["lat"] is not None and r["lon"] is not None]
        self._max_count = max((s[4] for s in self._sites), default=0)
        self._refit()
        self.update()

    def set_selected(self, oid):
        self._selected = oid
        self.update()                # bez re-fit — zmienia się tylko wyróżnienie

    def refresh_theme(self):
        self.update()

    def resizeEvent(self, ev):
        self._refit()                # transform i cache konturów zależą od rozmiaru widżetu
        super().resizeEvent(ev)

    # -------------------------------------------------------------- dopasowanie + cache konturów
    def _refit(self):
        if not self._sites:
            self._xf = None
            self._land_px = []
            return
        pts = [(lat, lon) for _, _, lat, lon, _ in self._sites]
        self._xf = mapproj.fit_view(pts, self.width(), self.height())
        self._land_px = []
        if self._xf.scale > 0:       # pre-rzutuj kontury RAZ per fit (F3 — nie w paintEvent)
            for line in mapproj.load_land_polylines():
                self._land_px.append(
                    QPolygonF([QPointF(*self._xf.to_px(lat, lon)) for lon, lat in line]))

    # -------------------------------------------------------------- malowanie
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        c = _MAP_COLORS
        p.fillRect(self.rect(), c["bg"])
        if self._xf is None or self._xf.scale <= 0:
            return                    # brak stanowisk / widżet bez rozmiaru — samo tło (nota w tabeli)

        pen = QPen(c["land"])         # kontury lądów/granic — tło pod scatterem
        pen.setWidthF(1.0)
        p.setPen(pen)
        for poly in self._land_px:
            p.drawPolyline(poly)

        base_font = p.font()
        sel = None                    # (px, py, r, name, lat, lon) zaznaczonego — rysowany NA WIERZCHU
        for oid, name, lat, lon, fc in self._sites:       # punkty niezaznaczone
            px, py = self._xf.to_px(lat, lon)
            r = mapproj.point_radius(fc, self._max_count)
            if oid == self._selected:
                sel = (px, py, r, name, lat, lon)
                continue
            p.setBrush(c["site"])
            outline = QPen(c["bg"])   # obwódka tłem odcina punkt od konturów
            outline.setWidthF(1.0)
            p.setPen(outline)
            p.drawEllipse(QPointF(px, py), r, r)

        if sel is not None:           # zaznaczony: większy dysk + KONTRASTOWY pierścień (wiz F8 #3 —
            px, py, r, name, lat, lon = sel   # obwódka-tłem była niewidzialna w light; ring z motywu)
            r += 3                    # wyróżnienie niezależne od rozmiaru punktu (9/11 ma ~minimum)
            p.setBrush(c["site_selected"])
            p.setPen(QPen(c["bg"], 1.0))
            p.drawEllipse(QPointF(px, py), r, r)
            p.setBrush(Qt.NoBrush)
            ring = QPen(c["sel_ring"])            # widoczny na OBU tłach — nie kolor tła
            ring.setWidthF(2.5)
            p.setPen(ring)
            p.drawEllipse(QPointF(px, py), r + 2, r + 2)
            # etykieta TYLKO zaznaczonego (wiz F8 #2 — wszystkie 11 zlewały się w blob; pełne nazwy
            # niesie tabela osi, mapa nazywa wybrany). Krótszy format niż tabela (.2f), inny kontekst (F4).
            p.setPen(QPen(c["scale"]))
            f = p.font()
            f.setBold(True)
            p.setFont(f)
            p.drawText(QPointF(px + r + 5, py + 4), name or f"{lat:.2f}, {lon:.2f}")
            p.setFont(base_font)

        self._paint_scale_bar(p, c)

    def _paint_scale_bar(self, p, c):
        bar_km = self._xf.scale_bar_km()
        bar_px = self._xf.km_to_px(bar_km)
        x0 = 12.0
        y0 = self.height() - 14.0
        pen = QPen(c["scale"])
        pen.setWidthF(2.0)
        p.setPen(pen)
        p.drawLine(QPointF(x0, y0), QPointF(x0 + bar_px, y0))
        for x in (x0, x0 + bar_px):
            p.drawLine(QPointF(x, y0 - 4), QPointF(x, y0 + 4))
        p.drawText(QPointF(x0, y0 - 8), f"{bar_km:g} km")
