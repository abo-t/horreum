"""Widżet mapy stanowisk (F8, PLAN_ux_redesign §9) — QPainter scatter kanonicznych stanowisk na tle
konturów Natural Earth. Warstwa widżetów (whitelist `test_gui_isolation`): cała matematyka rzutu/parser
żyje w Qt-wolnym `mapproj`, tu zostaje malowanie. GŁUPI malarz (NARROW, wzorzec `FacetRail`/
`SelectionBar`): dane wchodzą seterami, ZERO SQL/`repo`, zero orkiestracji zaznaczenia (to robi
`ObservatoryAxisView` — właściciel selekcji tabeli). Bez WebEngine/kafli (§0 FROZEN).

Motyw wzorcem F6 (`facets.use_theme`): modułowe `use_theme` czyta `theme.map_colors`, wołane z
`apply_theme` na starcie (auto-init pod pierwszy `paintEvent`) i przy przełączeniu; `refresh_theme()`
wymusza repaint. Pierścień klastra 4 km POZA v1 (F8 §9/F2, decyzja Zdzin 2026-07-18 — na fit-all
subpikselowy)."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from horreum.gui import mapproj, theme

_HIT_PX = 14.0             # próg kliku/hover — hojny (punkty małe: r_min=3), nearest wygrywa w klastrze
_CLUSTER_PX = 16.0         # promień dekolizji etykiet hover — nakładające się stanowiska stackowane
_LABEL_DX = 8.0            # odsunięcie etykiety w prawo od punktu

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

    siteClicked = Signal(object)     # oid klikniętego punktu (mapa→tabela, #10); właściciel selekcji = ObservatoryAxisView

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sites = []             # [(oid, name, lat, lon, frame_count)]
        self._selected = None
        self._hover = None           # oid punktu pod kursorem (etykieta hover + dekolizja, #10)
        self._xf = None              # mapproj.ViewTransform | None
        self._land_px = []           # cache pre-rzutowanych konturów [QPolygonF] per bieżący _xf (F3)
        self._max_count = 0
        self.setMinimumHeight(160)
        self.setMouseTracking(True)  # hover bez wciśniętego przycisku (etykiety pod kursorem)

    # -------------------------------------------------------------- setery danych
    def set_sites(self, rows):
        """Stanowiska do narysowania (kanoniczne z read-modelu). Wiersze bez lat/lon pominięte
        (defensywnie — schema NOT NULL, ale mapa nie zakłada)."""
        self._sites = [(r["id"], r["name"], r["lat"], r["lon"], r["frame_count"])
                       for r in rows if r["lat"] is not None and r["lon"] is not None]
        self._max_count = max((s[4] for s in self._sites), default=0)
        if self._hover is not None and all(s[0] != self._hover for s in self._sites):
            self._hover = None       # hoverowane stanowisko zniknęło z read-modelu
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

    # -------------------------------------------------------------- hit-test myszy (#10)
    def _sites_px(self):
        """Pozycje px wszystkich stanowisk (aligned z `self._sites`); [] gdy brak transformu."""
        if self._xf is None or self._xf.scale <= 0:
            return []
        return [self._xf.to_px(lat, lon) for _, _, lat, lon, _ in self._sites]

    def _hit(self, pos):
        """Indeks stanowiska pod (px) kursorem w progu `_HIT_PX`, albo None. Matematyka w `mapproj`
        (Qt-wolna, testowalna) — tu tylko rzut pozycji na listę punktów."""
        pts = self._sites_px()
        if not pts:
            return None
        return mapproj.nearest_point(pts, pos.x(), pos.y(), _HIT_PX)

    def mousePressEvent(self, ev):
        """Klik lewym w punkt → `siteClicked(oid)`; poza punktem = brak (nie kasujemy selekcji —
        tabela zostaje właścicielem, klik w tło mapy nie ma znaczenia jednoznacznego)."""
        if ev.button() == Qt.LeftButton:
            i = self._hit(ev.position())
            if i is not None:
                self.siteClicked.emit(self._sites[i][0])
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        i = self._hit(ev.position())
        oid = self._sites[i][0] if i is not None else None
        self.setCursor(Qt.PointingHandCursor if i is not None else Qt.ArrowCursor)
        if oid != self._hover:       # repaint tylko gdy hover realnie się zmienił
            self._hover = oid
            self.update()
        super().mouseMoveEvent(ev)

    def leaveEvent(self, ev):
        if self._hover is not None:  # kursor opuścił widżet → zgaś etykiety hover
            self._hover = None
            self.update()
        super().leaveEvent(ev)

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

        self._paint_labels(p, c, base_font)
        self._paint_scale_bar(p, c)

    def _paint_labels(self, p, c, base_font):
        """Etykiety punktów (#10). Zaznaczony ma etykietę ZAWSZE (kontekst wyboru; wiz F8 #2 —
        pełne nazwy niesie tabela, mapa nazywa wybrany). Hover pokazuje etykietę stanowiska pod
        kursorem ORAZ wszystkich w promieniu dekolizji (`_CLUSTER_PX`) — nakładające się w px
        (Dom+Będargowo 4 km) idą STACKIEM, nie jedno na drugim. Zaznaczony w klastrze hover NIE
        dublowany. Format krótszy niż tabela (.2f), inny kontekst prezentacji (F4)."""
        pts = self._sites_px()
        if not pts:
            return
        shown = set()
        if self._hover is not None:               # klaster wokół hoverowanego punktu → stack
            h = next((i for i, s in enumerate(self._sites) if s[0] == self._hover), None)
            if h is not None:
                cluster = mapproj.points_within(pts, pts[h][0], pts[h][1], _CLUSTER_PX)
                cluster.sort(key=lambda i: (-self._sites[i][4], self._sites[i][1] or ""))
                self._draw_label_stack(p, c, base_font, pts, cluster)
                shown.update(cluster)
        if self._selected is not None:            # zaznaczony — o ile nie pokazany już w hoverze
            s = next((i for i, si in enumerate(self._sites) if si[0] == self._selected), None)
            if s is not None and s not in shown:
                self._draw_label_stack(p, c, base_font, pts, [s])

    def _draw_label_stack(self, p, c, base_font, pts, indices):
        """Etykiety `indices` jako pionowy stack zakotwiczony przy pierwszym punkcie — dekolizja
        nakładających się stanowisk. Tło półprzezroczyste pod tekstem (czytelność na scatterze +
        konturach). Zaznaczony/hoverowany pogrubiony i w kolorze akcentu. Stack trzyma się w kadrze:
        pion klampowany (`mapproj.clamp_label_y0`, wiz #1), a gdy wyszedłby za prawą krawędź — rysowany
        po LEWEJ punktu (wiz #3). Odsunięcie od punktu świadome jego promienia (wiz #4 — tło nie nachodzi
        na dysk)."""
        if not indices:
            return
        fm = p.fontMetrics()
        lh = fm.height() + 2
        ax, ay = pts[indices[0]]
        labels = [(self._sites[i], self._sites[i][1]
                   or f"{self._sites[i][2]:.2f}, {self._sites[i][3]:.2f}") for i in indices]
        maxw = max(fm.horizontalAdvance(txt) for _, txt in labels)
        r_anchor = mapproj.point_radius(self._sites[indices[0]][4], self._max_count)
        if self._sites[indices[0]][0] == self._selected:
            r_anchor += 3                     # zaznaczony dysk jest większy (paintEvent: r+3)
        dx = _LABEL_DX + r_anchor             # #4: tło etykiety mija dysk punktu
        x = ax - dx - maxw if ax + dx + maxw + 3 > self.width() else ax + dx   # #3: flip przy prawej krawędzi
        y0 = mapproj.clamp_label_y0(ay, len(indices), fm.ascent(), lh, self.height())   # #1
        bg = QColor(c["bg"])
        bg.setAlpha(210)
        for k, (site, txt) in enumerate(labels):
            oid = site[0]
            ty = y0 + k * lh
            w = fm.horizontalAdvance(txt)
            p.fillRect(QRectF(x - 3, ty - fm.ascent() - 1, w + 6, lh), bg)
            p.setPen(QPen(c["site_selected"] if oid == self._selected else c["scale"]))
            f = QFont(base_font)
            f.setBold(oid == self._selected or oid == self._hover)
            p.setFont(f)
            p.drawText(QPointF(x, ty), txt)
        p.setFont(base_font)

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
