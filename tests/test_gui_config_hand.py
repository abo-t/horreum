"""Powierzchnia osi SPRZĘTU wskazanej ręką (R1, #DR2) — kubełek „bez zestawu" + okno „Przypisz
zestaw…", sterowane realnym oknem Qt (offscreen) na bazie §8.

Do R1 ten kubełek był POŁOWĄ wiersza informacyjnego z notą „rozwiązywanie w przygotowaniu": ekran
zapowiadał userowi drogę, której nie było. Testy pilnują trzech rzeczy, których brak sprawiłby, że
powierzchnia znów obiecuje więcej, niż dowozi: (1) licznik == długość drążenia, (2) gest zapisuje
TĄ SAMĄ klingą co rdzeń i licznik po nim spada, (3) okno nie pozwala zapisać bez celu i bez
teleskopu.

`importorskip` na poziomie MODUŁU (PLAN_gui §4); `QT_QPA_PLATFORM=offscreen` PRZED importem Qt."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, repo, resolver
from horreum.gui import i18n, queries
from horreum.gui.app import ObjectAxisView
from horreum.gui.config_dialog import AssignConfigDialog

from fixture_s8 import seed_object_axis

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

UROLE = 0x0100   # Qt.UserRole
NOW = "2026-08-08T10:00:00+00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def view(qapp, tmp_path):
    con = db.open_db(str(tmp_path / "s8_cfg.db"))
    ids = seed_object_axis(con)
    v = ObjectAxisView(con)
    yield v, con, ids
    v.close()
    con.close()


def _wiersz_kubelka(v):
    for r in range(v.review.count()):
        if v.review.item(r).data(UROLE) == "config_review":
            return r, v.review.item(r)
    raise AssertionError("kolejka nie ma kubełka osi sprzętu")


# --- read-model: licznik i lista mówią JEDNO ---

def test_licznik_kubelka_jest_dlugoscia_drazenia(view):
    """Ta równość jest tu bramką, nie ozdobą: kubełek, którego lista pokazuje inną liczbę niż
    wiersz, na którym user kliknął, kłamie o zakresie gestu. Predykat ma dwóch nosicieli
    (`resolver.review_state` po stronie rdzenia, read-model po stronie widoku) i to jest świadome —
    ale wtedy równość musi być PINOWANA (ta sama figura, co kotwica `nameless_raw_lights`)."""
    v, con, ids = view
    assert len(queries.config_review_frames(con)) == resolver.review_state(con).no_config


def test_grupy_sa_projekcja_tej_samej_listy(view):
    """Grupy to PROJEKCJA drążenia (folder × kamera), nie drugi predykat — suma klatek w grupach
    musi się równać liście, inaczej okno pokazuje inny świat niż panel pod nim."""
    v, con, ids = view
    klatki = queries.config_review_frames(con)
    grupy = queries.config_review_groups(con)
    assert sum(g["n_frames"] for g in grupy) == len(klatki)
    assert sorted(fid for g in grupy for fid in g["frame_ids"]) == \
        sorted(r["frame_id"] for r in klatki)


def test_kamera_jest_czescia_klucza_grupy(view):
    """D-DR-3: dwa korpusy w JEDNYM folderze to DWA zestawy, bo `config` niesie dokładnie jedną
    kamerę (`UNIQUE(telescope_id, camera_id)`). Grupa po samym folderze obiecywałaby jeden gest
    tam, gdzie muszą powstać dwa — zmierzone na archiwum: 2 z 36 folderów mają dwa korpusy."""
    v, con, ids = view
    folder = r"R:\ASTRO_\LIGHTS\NGC5194\portable"
    for sha, cam in (("sha-korpus-1", ids["cam1"]), ("sha-korpus-2", ids["cam2"])):
        fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="light", filetype="raw",
                                   camera_id=cam, now=NOW)
        repo.record_header(con, frame_id=fid, raw_json="{}", now=NOW)
        repo.add_location(con, frame_id=fid, volume="TESTVOL",
                          path=os.path.join(folder, f"{sha}.dng"), now=NOW)

    w_folderze = [g for g in queries.config_review_groups(con) if g["folder"] == folder]
    assert len(w_folderze) == 2
    assert {g["camera_id"] for g in w_folderze} == {ids["cam1"], ids["cam2"]}
    assert all(g["n_frames"] == 1 for g in w_folderze)


# --- powierzchnia: wiersz prowadzi, przycisk tłumaczy się sam ---

def test_kubelek_drazy_do_klatek(view):
    v, con, ids = view
    r, _ = _wiersz_kubelka(v)
    v.review.setCurrentRow(r)
    assert v.frames.rowCount() == len(queries.config_review_frames(con))
    assert i18n.t("object.frames_config_review", n=v.frames.rowCount()) == v.frames_label.text()


def test_przycisk_zestawu_zapala_sie_TYLKO_na_swoim_kubelku(view):
    """Szczery disabled: UI nie kłamie. Przycisk osi SPRZĘTU nad kubełkiem osi OBIEKTU byłby
    obietnicą zapisu, którego ta akcja nie zrobi."""
    v, con, ids = view
    r, _ = _wiersz_kubelka(v)
    v.review.setCurrentRow(r)
    assert v.set_config_btn.isEnabled()
    assert v.set_config_btn.toolTip() == i18n.t("object.set_config_tip")

    v.review.clearSelection()
    v._sync_assign_enabled()
    assert not v.set_config_btn.isEnabled()
    assert v.set_config_btn.toolTip() == i18n.t("object.set_config_tip_pick")


def test_pusty_kubelek_nie_prowadzi_nigdzie(view, tmp_path):
    """Jedna reguła dla wszystkich kubełków (wiz T2 N6): zero nie ma dokąd prowadzić, więc wiersz
    jest informacyjny i mówi, KIEDY się zapali."""
    v, con, ids = view
    tel = con.execute("SELECT id FROM telescope LIMIT 1").fetchone()[0]
    repo.user_assign_config(con, frame_ids=[r["frame_id"] for r in queries.config_review_frames(con)
                                            if r["camera_id"] is not None],
                            telescope_id=tel, now="2026-08-08T10:00:00+00:00")
    v.refresh()

    wiersze = [(v.review.item(i).text(), v.review.item(i).data(UROLE))
               for i in range(v.review.count())]
    puste = [(t, tag) for t, tag in wiersze if t.startswith("— bez zestawu")]
    assert puste and all(tag is None for _, tag in puste)


# --- okno: dwa jawne wybory, zero zapisu bez nich ---

def test_okno_wymaga_celu_i_teleskopu(view):
    v, con, ids = view
    dlg = AssignConfigDialog(con, groups=queries.config_review_groups(con))
    assert not dlg.accept_btn.isEnabled(), "bez teleskopu akcja nie ma prawa być klikalna"

    dlg.combo.setCurrentIndex(1)                     # jawne wskazanie teleskopu
    assert dlg.accept_btn.isEnabled()
    for i in range(dlg.items.count()):               # …a teraz odbierz cel
        dlg.items.item(i).setCheckState(Qt.Unchecked)
    assert not dlg.accept_btn.isEnabled()
    dlg.close()


def test_etykieta_mowi_ile_klatek_gest_RUSZY(view):
    """Liczba na przycisku to klatki, które gest REALNIE ruszy — nie długość listy. Grupa bez
    kamery wchodzi ODZNACZONA, bo klinga i tak ją odmówi (inwariant DDL §1)."""
    v, con, ids = view
    grupy = queries.config_review_groups(con)
    dlg = AssignConfigDialog(con, groups=grupy)
    ruszalne = sum(g["n_frames"] for g in grupy if g["camera_id"] is not None)
    assert dlg.accept_btn.text() == i18n.t("cfg.assign_btn", n=ruszalne)
    dlg.close()


def test_gest_zapisuje_i_licznik_spada(view, monkeypatch):
    """Pełna droga: kubełek → okno → klinga → licznik. Dialog podmieniony seamem (wzorzec testów
    „Przypisz obiekt…"), bo sprawdzamy GLUE, nie modalność Qt."""
    v, con, ids = view
    r, _ = _wiersz_kubelka(v)
    v.review.setCurrentRow(r)
    przed = resolver.review_state(con).no_config
    tel = con.execute("SELECT id, telescop_canon FROM telescope LIMIT 1").fetchone()
    cel = [g["frame_ids"] for g in queries.config_review_groups(con)
           if g["camera_id"] is not None][0]

    class _Fake:
        def __init__(self, *a, **k):
            self.selected = (tel["id"], tel["telescop_canon"], cel)

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr("horreum.gui.app.AssignConfigDialog", _Fake)
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_set_config()

    assert resolver.review_state(con).no_config == przed - len(cel)
    for fid in cel:
        row = con.execute("SELECT config_id, config_source FROM frame WHERE id=?",
                          (fid,)).fetchone()
        assert row["config_id"] is not None and row["config_source"] == "user"
    assert msgs and str(len(cel)) in msgs[-1] and tel["telescop_canon"] in msgs[-1]


def test_gest_bez_grup_nie_otwiera_okna(view, monkeypatch):
    """Pusty kubełek → zdanie w pasku, ZERO okna. Cisza po kliknięciu byłaby nieodróżnialna
    od zapisu (F-2)."""
    v, con, ids = view
    tel = con.execute("SELECT id FROM telescope LIMIT 1").fetchone()[0]
    repo.user_assign_config(con, frame_ids=[r["frame_id"] for r in queries.config_review_frames(con)
                                            if r["camera_id"] is not None],
                            telescope_id=tel, now="2026-08-08T10:00:00+00:00")

    otwarte = []
    monkeypatch.setattr("horreum.gui.app.AssignConfigDialog",
                        lambda *a, **k: otwarte.append(1))
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_set_config()
    assert not otwarte and msgs[-1] == i18n.t("cfg.err_nothing")
