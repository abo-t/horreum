"""Powierzchnia STANOWISKA Z RĘKI (0027) - okno „Wskaż stanowisko…" i jego wpięcie w widok osi
obserwatorium, sterowane realnym oknem Qt (offscreen).

Pilnujemy: (1) grupy okna są projekcją drążenia (suma klatek == lista), (2) okno nie zapisze bez
zaznaczenia ani bez celu i odbija współrzędne spoza zakresu TĄ SAMĄ regułą co klinga, (3) gest
z widoku idzie tą samą klingą co CLI, a komunikat niesie receptę odwrotu, (4) cofnięcie z tego
samego widoku oddaje klatki do kubełka. Współrzędne SYNTETYCZNE (repo publiczne).

`importorskip` na poziomie MODUŁU; `QT_QPA_PLATFORM=offscreen` PRZED importem Qt."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, repo
from horreum.gui import app as appmod
from horreum.gui import i18n, queries
from horreum.gui.app import ObservatoryAxisView
from horreum.gui.observatory_dialog import AssignObservatoryDialog

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel

NOW = "2026-10-04T12:00:00+00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def scena(qapp, tmp_path):
    """Stanowisko „dom" z jedną klatką z GPS + dwa foldery RAW-ów bez GPS (3 i 1 klatka)."""
    con = db.open_db(str(tmp_path / "h.db"))
    dom, _ = repo.propose_observatory(con, lat=53.4, lon=114.4, now=NOW)
    fid, _ = repo.upsert_frame(con, sha1_data="gps", kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    repo.assign_observatory(con, frame_id=fid, observatory_id=dom, now=NOW)
    bez = []
    for i, folder in enumerate(["LMC", "LMC", "LMC", "M42"]):
        f, _ = repo.upsert_frame(con, sha1_data=f"r{i}", kind="light", filetype="raw",
                                 camera_id=None, now=NOW)
        repo.add_location(con, frame_id=f, volume="V", path=f"X:\\A\\{folder}\\r{i}.dng", now=NOW)
        bez.append(f)
    w = ObservatoryAxisView(con, now_fn=lambda: NOW)
    yield w, con, dom, bez
    w.close()
    con.close()


def _zaznacz(dlg, folder_kon):
    for i in range(dlg.items.count()):
        it = dlg.items.item(i)
        if folder_kon in it.text():
            it.setCheckState(Qt.Checked)


# --- read-model ---

def test_grupy_sa_projekcja_listy_bez_stanowiska(scena):
    w, con, dom, bez = scena
    klatki = queries.observatory_review_frames(con)
    grupy = queries.observatory_review_groups(con)
    assert sorted(r["frame_id"] for r in klatki) == sorted(bez)
    assert sorted(f for g in grupy for f in g["frame_ids"]) == sorted(bez)
    lmc = next(g for g in grupy if g["folder"].endswith("LMC"))
    assert (lmc["n_frames"], lmc["kinds"]) == (3, [("light/raw", 3)])


# --- okno ---

def test_okno_wchodzi_odznaczone_i_nie_zapisze_bez_celu(scena):
    w, con, dom, bez = scena
    dlg = AssignObservatoryDialog(con, groups=queries.observatory_review_groups(con))
    assert dlg._zaznaczone() == []
    assert not dlg.accept_btn.isEnabled()
    _zaznacz(dlg, "LMC")
    assert dlg.radio_existing.isChecked()                 # lista niepusta - start na istniejących
    assert not dlg.accept_btn.isEnabled()                 # zaznaczone, ale cel niewskazany
    assert i18n.t("obshand.assign_btn", n=3) == dlg.accept_btn.text()
    dlg.close()


def test_okno_odbija_wspolrzedne_spoza_zakresu(scena):
    w, con, dom, bez = scena
    dlg = AssignObservatoryDialog(con, groups=queries.observatory_review_groups(con))
    _zaznacz(dlg, "LMC")
    dlg.radio_new.setChecked(True)
    dlg.lat.setText("95")
    dlg.lon.setText("170,7")
    assert dlg.accept_btn.isEnabled()
    dlg._validate_and_accept()
    assert dlg.selected is None and "-90..90" in dlg.error.text()
    dlg.lat.setText("-30,25")                             # przecinek dziesiętny z klawiatury PL
    dlg.name.setText("Wyjazd")
    dlg._validate_and_accept()
    assert dlg.selected["lat"] == -30.25 and dlg.selected["lon"] == 170.7
    assert dlg.selected["name"] == "Wyjazd" and len(dlg.selected["frame_ids"]) == 3


def test_okno_tryb_cofniecia_bez_wyboru_celu(scena):
    w, con, dom, bez = scena
    repo.user_assign_observatory(con, frame_ids=bez[:3], observatory_id=dom, now=NOW)
    grupy = queries.observatory_by_hand_groups(con)
    dlg = AssignObservatoryDialog(con, groups=grupy, mode="clear")
    assert dlg.combo is None
    assert "53.4000, 114.4000" in dlg.items.item(0).text()    # świadek: co dziś stoi
    _zaznacz(dlg, "LMC")
    assert dlg.accept_btn.isEnabled()
    dlg._validate_and_accept()
    assert sorted(dlg.selected["frame_ids"]) == sorted(bez[:3])


# --- wpięcie w widok osi ---

def test_gest_z_widoku_zapisuje_i_daje_recepte_odwrotu(scena, monkeypatch):
    """Pełna droga: przycisk → okno (seam) → klinga → lista stanowisk i komunikat."""
    w, con, dom, bez = scena

    class _Fake:
        def __init__(self, *a, **k):
            self.selected = {"frame_ids": bez[:3], "observatory_id": None, "lat": -30.25,
                             "lon": 170.7, "name": "Wyjazd", "elev": None, "label": "Wyjazd"}

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr("horreum.gui.app.AssignObservatoryDialog", _Fake)
    msgs = []
    w.status_message.connect(msgs.append)
    w.btn_hand_assign.click()
    nowe = con.execute("SELECT id FROM observatory WHERE name = 'Wyjazd'").fetchone()[0]
    assert all(tuple(con.execute("SELECT observatory_id, observatory_source FROM frame "
                                 "WHERE id = ?", (f,)).fetchone()) == (nowe, "user")
               for f in bez[:3])
    assert w.table.rowCount() == 2                        # nowe stanowisko na liście osi
    assert w._selected_observatory_id() == nowe           # cel gestu zaznaczony w tabeli
    assert w.map_view._selected == nowe                   # …i wyróżniony na mapie
    assert "Wyjazd" in msgs[-1] and "3" in msgs[-1]
    assert i18n.t("obshand.undo_hint").strip() in msgs[-1]
    assert sorted(f for g in queries.observatory_review_groups(con) for f in g["frame_ids"]) \
        == [bez[3]]                                       # klatki wypadły z kubełka


def test_cofniecie_z_widoku_oddaje_klatki_do_kubelka(scena, monkeypatch):
    w, con, dom, bez = scena
    repo.user_assign_observatory(con, frame_ids=bez[:3], observatory_id=dom, now=NOW)

    class _Fake:
        def __init__(self, *a, mode, **k):
            assert mode == "clear"
            self.selected = {"frame_ids": bez[:3]}

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr("horreum.gui.app.AssignObservatoryDialog", _Fake)
    msgs = []
    w.status_message.connect(msgs.append)
    w.btn_hand_clear.click()
    assert sorted(f for g in queries.observatory_review_groups(con) for f in g["frame_ids"]) \
        == sorted(bez)
    # bez zer, bez zdania o GPS (cofnięte klatki GPS nie mają); „dom" ma dalej klatkę z GPS,
    # więc zdania o pustym stanowisku nie ma
    i18n.set_lang("pl")
    assert msgs[-1] == ("Cofnięto wskazanie stanowiska: 3 z 3 klatek"
                        ". 3 klatki wróciły do „bez stanowiska”.")


def test_cofniecie_mowi_o_stanowisku_bez_klatek(scena):
    """Stanowisko z gestu ZOSTAJE (planer go potrzebuje) - zdanie mówi, że zostało puste."""
    w, con, dom, bez = scena
    i18n.set_lang("pl")
    g = repo.user_assign_observatory(con, frame_ids=bez[:1], lat=-30.25, lon=170.7,
                                     name="Wyjazd", now=NOW)
    c = repo.clear_observatory_assignment(con, frame_ids=bez[:2], now=NOW)
    zdanie = appmod.zdanie_stanowiska(con, "clear", c)
    assert zdanie == (f"Cofnięto wskazanie stanowiska: 1 z 2 klatek · 1 klatka bez stanowiska"
                      f". 1 klatka wróciła do „bez stanowiska”"
                      f". Stanowisko #{g.observatory_id} Wyjazd zostaje bez klatek.")
    assert con.execute("SELECT count(*) FROM observatory WHERE id = ?",
                       (g.observatory_id,)).fetchone()[0] == 1


def test_trafienie_w_istniejace_nazywa_faktyczne_stanowisko(scena):
    """Z12: współrzędne w promieniu „dom" → zdanie nazywa „#id"/nazwę kanonu, nie wpisany punkt;
    Z13: wysokość istniejącego zostaje i zdanie o tym mówi."""
    w, con, dom, bez = scena
    i18n.set_lang("pl")
    g = repo.user_assign_observatory(con, frame_ids=bez[:2], lat=53.401, lon=114.401, elev=100,
                                     now=NOW)
    assert (g.created, g.observatory_id, g.elev_set) == (False, dom, 100.0)
    zdanie = appmod.zdanie_stanowiska(con, "assign", g)
    assert zdanie.startswith(f"Stanowisko #{dom}: przypisano 2 z 2 klatek")
    assert "wysokość 100 m dopisana" in zdanie and "53.401" not in zdanie
    repo.label_observatory(con, observatory_id=dom, name="Dom", now=NOW)
    g2 = repo.user_assign_observatory(con, frame_ids=bez[2:], lat=53.401, lon=114.401, elev=250,
                                      now=NOW)
    zdanie2 = appmod.zdanie_stanowiska(con, "assign", g2)
    assert zdanie2.startswith("Stanowisko Dom: przypisano 2 z 2 klatek")
    assert "ma już wysokość 100 m - zostaje" in zdanie2


@pytest.mark.parametrize("n, pl, en", [
    (1, "1 klatka", "1 frame"), (2, "2 klatki", "2 frames"), (5, "5 klatek", "5 frames"),
    (12, "12 klatek", "12 frames"), (22, "22 klatki", "22 frames"),
])
def test_odmiana_wiersza_i_naglowka_obu_okien(scena, n, pl, en):
    """„1 folderów", „1 klatek" - odmiana przez `t_plural` w OBU oknach gestu ręki."""
    from horreum.gui.config_dialog import AssignConfigDialog
    w, con, dom, bez = scena
    grupa_obs = {"folder": "X:\\A\\LMC", "observatory_label": None, "n_frames": n,
                 "frame_ids": list(range(n)), "kinds": [("light/raw", n)]}
    grupa_cfg = {"folder": "X:\\A\\LMC", "camera_id": 1, "camera_model": "A7R3", "telescop": None,
                 "telescope_label": None, "n_frames": n, "frame_ids": list(range(n)),
                 "other_kinds": []}
    folder_pl = {1: "1 folder", 2: "2 foldery", 5: "5 folderów", 12: "12 folderów",
                 22: "22 foldery"}[n]
    grupa_pl = {1: "1 grupa", 2: "2 grupy", 5: "5 grup", 12: "12 grup", 22: "22 grupy"}[n]
    for lang, fraza in (("pl", pl), ("en", en)):
        i18n.set_lang(lang)
        d1 = AssignObservatoryDialog(con, groups=[grupa_obs] * n)
        d2 = AssignConfigDialog(con, groups=[grupa_cfg] * n)
        assert f"  ·  {fraza}  ·  " in d1.items.item(0).text()
        assert f"  ·  {fraza}" in d2.items.item(0).text()
        if lang == "pl":
            glowa = [l.text() for l in d1.findChildren(QLabel) if "bez stanowiska" in l.text()][0]
            assert glowa.startswith(f"{folder_pl} · ")
            glowa_cfg = [l.text() for l in d2.findChildren(QLabel) if "TELESKOP" in l.text()][0]
            assert glowa_cfg.startswith(f"{grupa_pl} · ")
        d1.close()
        d2.close()
    i18n.set_lang("pl")


def test_pusty_kubelek_mowi_komunikatem_bez_okna(scena, monkeypatch):
    w, con, dom, bez = scena
    monkeypatch.setattr("horreum.gui.app.AssignObservatoryDialog",
                        lambda *a, **k: pytest.fail("okno nie ma się otwierać"))
    msgs = []
    w.status_message.connect(msgs.append)
    w.btn_hand_change.click()                             # nikt jeszcze nie wskazał ręką
    assert msgs[-1] == i18n.t("obshand.nothing_hand")


def test_przyciski_gasna_w_biegu_etapu(scena):
    w, con, dom, bez = scena
    w.set_busy(True)
    assert not w.btn_hand_assign.isEnabled() and not w.btn_hand_clear.isEnabled()
    w.set_busy(False)
    assert w.btn_hand_assign.isEnabled()
