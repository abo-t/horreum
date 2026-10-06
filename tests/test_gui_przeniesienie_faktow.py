"""Gest „Przenieś fakty ręki na następczynię" w perspektywie „Zastąpione" (AR-41) - test łatki
`grid.py` (menu tabeli + slot `_on_transfer_facts`), dokładany razem z nią."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, repo
from horreum.gui import grid as grid_mod

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

NOW = "2026-10-06T10:00:00+00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _para(con, sha, kind_nowej, oid):
    a = repo.upsert_frame(con, sha1_data=sha + "-a", kind="light", filetype="fits",
                          camera_id=None, now=NOW)[0]
    b = repo.upsert_frame(con, sha1_data=sha + "-b", kind=kind_nowej, filetype="fits",
                          camera_id=None, now=NOW)[0]
    repo.assign_object(con, frame_id=a, object_id=oid, object_source="user", now=NOW)
    lid = repo.add_location(con, frame_id=a, volume="V", path=f"/z/{sha}.fits", now=NOW)[0]
    repo.rebind_location(con, location_id=lid, frame_after=b, now=NOW)
    repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW)
    return a, b


def test_gest_w_perspektywie_zastapionych_przenosi_i_mowi_o_zatrzymanym(qapp, tmp_path):
    """Zaznaczenie dwóch zastąpionych: light→light przenosi obiekt, light→flat zatrzymuje werdykt
    na zastąpionej - jedno zdanie mówi oba fakty, plakietka Porządków dostaje sygnał."""
    con = db.open_db(str(tmp_path / "z.db"))
    oid = repo.upsert_object(con, canon="IC443", catalog="IC", kind=None, now=NOW)[0]
    a, b = _para(con, "p1", "light", oid)
    c, d = _para(con, "p2", "flat", oid)
    v = grid_mod.FramesView(con, now_fn=lambda: NOW)
    try:
        v.apply_perspective(grid_mod.PRESET_SUPERSEDED)
        assert set(v._frame_ids) == {a, c}
        v.table.selectAll()
        v._on_table_menu(QPoint(1, 1))
        assert v.act_transfer_facts.isVisible() and v.act_transfer_facts.isEnabled()
        v._menu_tabeli.hide()
        msg, plakietka = [], []
        v.status_message.connect(msg.append)
        v.stan_porzadkow_changed.connect(lambda: plakietka.append(1))
        v._on_transfer_facts()
        assert msg[-1].startswith("Przeniesienie faktów ręki: 1 z 2 klatek (obiekt: 1)")
        assert "1 werdykt obiektu został na klatce zastąpionej" in msg[-1]
        assert plakietka == [1]
        assert con.execute("SELECT object_id FROM frame WHERE id=?", (b,)).fetchone()[0] == oid
        assert con.execute("SELECT object_id FROM frame WHERE id=?", (d,)).fetchone()[0] is None
        assert con.execute("SELECT object_id FROM frame WHERE id=?", (c,)).fetchone()[0] == oid
    finally:
        v.close()
        con.close()


def _widok_dwoch_par(qapp, tmp_path):
    con = db.open_db(str(tmp_path / "z.db"))
    oid = repo.upsert_object(con, canon="IC443", catalog="IC", kind=None, now=NOW)[0]
    a, b = _para(con, "p1", "light", oid)
    c, d = _para(con, "p2", "light", oid)
    v = grid_mod.FramesView(con, now_fn=lambda: NOW)
    v.apply_perspective(grid_mod.PRESET_SUPERSEDED)
    v.table.selectAll()
    return con, v, (a, b, c, d)


def test_ogniwo_zgaszone_w_trakcie_gestu_to_powod_a_widok_sie_odswieza(qapp, tmp_path,
                                                                       monkeypatch):
    """Skan gasi ogniwo drugiej klatki między odczytem a klingą: gest kończy się zdaniem z powodem,
    perspektywa odświeżona (klatka, której plik wrócił, z niej wypada), osie dostają sygnał."""
    from horreum import supersede
    con, v, (a, b, c, d) = _widok_dwoch_par(qapp, tmp_path)
    prawdziwa = repo.transfer_human_facts

    def _skan_w_trakcie(con_, *, frame_id, now, actor):
        if frame_id == c:
            repo.clear_superseded(con_, frame_id=c, now=now)
        return prawdziwa(con_, frame_id=frame_id, now=now, actor=actor)
    monkeypatch.setattr(supersede.repo, "transfer_human_facts", _skan_w_trakcie)
    msg, osie = [], []
    v.status_message.connect(msg.append)
    v.object_axis_changed.connect(lambda: osie.append(1))
    try:
        v._on_transfer_facts()
        assert "przestała być zastąpiona w trakcie gestu" in msg[-1]
        assert v._frame_ids == [a], "perspektywa odświeżona po geście"
        assert osie == [1]
    finally:
        v.close()
        con.close()


def test_blad_klingi_w_polowie_odswieza_i_mowi(qapp, tmp_path, monkeypatch):
    """Błąd klingi na drugiej klatce: pierwsza jest zapisana - widok się odświeża, pasek mówi raport
    częściowy, okno ostrzeżenia podaje powód (wzorzec gestów osi obiektu)."""
    from horreum import supersede
    con, v, (a, b, c, d) = _widok_dwoch_par(qapp, tmp_path)
    prawdziwa = repo.transfer_human_facts

    def _pada(con_, *, frame_id, now, actor):
        if frame_id == c:
            raise ValueError("frame:999 (następczyni) nie istnieje")
        return prawdziwa(con_, frame_id=frame_id, now=now, actor=actor)
    monkeypatch.setattr(supersede.repo, "transfer_human_facts", _pada)
    okna, msg = [], []
    monkeypatch.setattr(grid_mod.QMessageBox, "warning", lambda *a: okna.append(a[2]))
    v.status_message.connect(msg.append)
    try:
        v._on_transfer_facts()
        assert msg[-1].startswith("Przeniesienie faktów ręki: 1 z 2 klatek")
        assert okna and "następczyni" in okna[0]
        assert con.execute("SELECT object_id FROM frame WHERE id=?", (b,)).fetchone()[0] is not None
    finally:
        v.close()
        con.close()


def test_poza_perspektywa_zastapionych_pozycji_nie_ma(qapp, tmp_path):
    con = db.open_db(str(tmp_path / "z.db"))
    oid = repo.upsert_object(con, canon="IC443", catalog="IC", kind=None, now=NOW)[0]
    _para(con, "p1", "light", oid)
    v = grid_mod.FramesView(con, now_fn=lambda: NOW)
    try:
        v._on_table_menu(QPoint(1, 1))                 # zwykła perspektywa - menu milczy
        assert not v._menu_tabeli.isVisible()
    finally:
        v.close()
        con.close()
