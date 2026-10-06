"""Widżet mapy stanowisk (`horreum.gui.map_view`) - wpięcie rozcinania konturów i marginesu
dopasowania. Matematykę pilnuje Qt-wolny `test_mapproj`; tu tylko to, że widżet jej UŻYWA.

Punkty PUBLICZNE (Mt John nad Tekapo, centrum Warszawy) - repo publiczne.
`importorskip` na poziomie MODUŁU; `QT_QPA_PLATFORM=offscreen` PRZED importem Qt."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from horreum.gui import map_view

_SITES = [{"id": 1, "name": "Warszawa", "lat": 52.23, "lon": 21.01, "frame_count": 40},
          {"id": 2, "name": "Tekapo", "lat": -43.99, "lon": 170.46, "frame_count": 3}]


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def mapa(qapp):
    m = map_view.SitesMapView()
    m.resize(1000, 400)
    m.set_sites(_SITES)
    yield m
    m.close()


def test_kontury_bez_odcinka_przez_caly_kadr(mapa):
    najdluzszy = max(abs(poly[i + 1].x() - poly[i].x())
                     for poly in mapa._land_px for i in range(poly.size() - 1))
    assert najdluzszy < mapa.width() / 2


def test_punkty_skrajne_z_marginesem_od_krawedzi(mapa):
    """Tekapo leżało na dolnej krawędzi; zaznaczony dysk z pierścieniem ma się zmieścić w kadrze."""
    zasieg = map_view._FIT_PAD_PX - 6.0                    # promień rysunku zaznaczonego punktu
    for s in _SITES:
        px, py = mapa._xf.to_px(s["lat"], s["lon"])
        assert zasieg <= px <= mapa.width() - zasieg
        assert zasieg <= py <= mapa.height() - zasieg


def test_render_z_zaznaczeniem_nie_pada(mapa):
    mapa.set_selected(2)
    img = mapa.grab().toImage()
    assert not img.isNull()
