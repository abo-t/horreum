"""Optyka teleskopu w oknie (offscreen, AR-128 `O4`, AR-129 `O5`, D-1012-2): f/ i Ogniskowa
edytowalne na Osi teleskopu, „Przywróć z plików", panel „Zestawy", kubełek ogniskowej z oknem
„Przypisz zestaw…" w trybie ogniskowej („Dopisz nowy…"), wiersze Porządków i gest „Popraw f/
w plikach…" w perspektywie Zbiorów. Każdy test nazywa mutanta, który go czerwieni.

`importorskip` na poziomie modułu - bez PySide6 plik się pomija."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, grouper, repo, resolver, writeback
from horreum.gui import i18n, queries
from horreum.gui import config_dialog as cfg_mod
from horreum.gui.app import COL_FOCAL, COL_FRATIO, COL_ID, ObjectAxisView, TelescopeAxisView

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

NOW = "2026-10-12T10:00:00+00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _kamera(con, model="ASI2600MM"):
    cid, _ = repo.upsert_camera(con, model_canon=model, pixel_um=3.76, is_mono=1,
                                is_mono_source="header", raw_instrume=model, now=NOW)
    return cid


def _klatka(con, sha, *, telescop, focal, f_ratio=None, camera_id, path=None, kind="light"):
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind=kind, filetype="fits",
                               camera_id=camera_id, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json=json.dumps({"NAXIS1": 6248, "NAXIS2": 4176}),
                       now=NOW, telescop=telescop, focallen=focal, focratio_raw=f_ratio,
                       xpixsz=3.76)
    if path is not None:
        with con:
            con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                        (fid, path))
    return fid


def _baza(tmp_path):
    """RC8 1600/f8 (park), A140R 784/f5.6, ED120R 789, N800 800; dwie klatki RC8 z 800 mm
    (kubełek ogniskowej) w jednym folderze."""
    con = db.open_db(str(tmp_path / "o.db"))
    cam = _kamera(con)
    for canon, f, fr in (("RC8", 1600, 8.0), ("A140R", 784, 5.6), ("ED120R", 789, 6.6),
                         ("N800", 800, None)):
        for i in range(3):
            _klatka(con, f"{canon}{i}", telescop=canon, focal=f, f_ratio=fr, camera_id=cam,
                    path=f"X:\\archiwum\\X\\{canon}{i}.fits")
    obce = [_klatka(con, f"o{i}", telescop="RC8", focal=800, f_ratio=8.0, camera_id=cam,
                    path=f"X:\\archiwum\\M64\\o{i}.fits") for i in range(2)]
    grouper.run_grouper(con, NOW)
    rc8 = con.execute("SELECT id FROM telescope WHERE telescop_canon = 'RC8'").fetchone()[0]
    repo.set_telescope_park(con, telescope_id=rc8, in_park=1, now=NOW)
    return con, obce, rc8


def _wiersz(view, tid):
    for r in range(view.table.rowCount()):
        if view.table.item(r, COL_ID).data(Qt.UserRole) == tid:
            return r
    raise AssertionError(tid)


# ------------------------------------------------------------ Oś teleskopu

def test_os_f_i_ogniskowa_edytowalne_reka_wygrywa_i_cofniecie(qapp, tmp_path):
    """Dwuklik w Ogniskowej → ręka (zdarzenie, znacznik, tooltip z plikami); pusty wpis → cofnięcie;
    nie-liczba → komunikat, zero zdarzeń; „Przywróć z plików" aktywny tylko przy ręce.
    Mutant: kolumny optyki bez `ItemIsEditable` albo `_on_item_changed` filtrujące samą etykietę."""
    con, _obce, rc8 = _baza(tmp_path)
    v = TelescopeAxisView(con, now_fn=lambda: NOW)
    msgs = []
    v.status_message.connect(msgs.append)
    r = _wiersz(v, rc8)
    for c in (COL_FOCAL, COL_FRATIO):
        assert v.table.item(r, c).flags() & Qt.ItemIsEditable
    assert v.table.item(r, COL_FRATIO).text() == "8"
    assert "pliki: 1600 mm (3 kl.)" in v.table.item(r, COL_FOCAL).toolTip()
    v.table.selectRow(r)
    assert not v.btn_restore_optics.isEnabled()
    v.table.item(r, COL_FOCAL).setText("1580")
    assert con.execute("SELECT focal_user FROM telescope WHERE id = ?", (rc8,)).fetchone()[0] == 1580.0
    r = _wiersz(v, rc8)
    assert v.table.item(r, COL_FOCAL).text() == f"{queries.CLEARED_MARK} 1580"
    assert "pliki: 1600 mm" in v.table.item(r, COL_FOCAL).toolTip()
    v.table.selectRow(r)
    assert v.btn_restore_optics.isEnabled()
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    v.table.item(r, COL_FRATIO).setText("abc")
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed and "abc" in msgs[-1]
    v.table.item(_wiersz(v, rc8), COL_FRATIO).setText("200")
    assert con.execute("SELECT f_ratio_user FROM telescope WHERE id = ?", (rc8,)).fetchone()[0] is None
    v.table.item(_wiersz(v, rc8), COL_FOCAL).setText("")
    assert con.execute("SELECT focal_user FROM telescope WHERE id = ?", (rc8,)).fetchone()[0] is None
    con.close()


def test_przywroc_z_plikow_zdejmuje_obie_reki(qapp, tmp_path):
    """„Przywróć z plików" zdejmuje rękę ogniskowej i f/ jednym kliknięciem, dwa zdarzenia.
    Mutant: przycisk czyszczący tylko jedno pole."""
    con, _obce, rc8 = _baza(tmp_path)
    repo.set_telescope_focal(con, telescope_id=rc8, focal_mm=1580, now=NOW)
    repo.set_telescope_f_ratio(con, telescope_id=rc8, f_ratio=7.9, now=NOW)
    v = TelescopeAxisView(con, now_fn=lambda: NOW)
    v.table.selectRow(_wiersz(v, rc8))
    v.btn_restore_optics.click()
    assert tuple(con.execute("SELECT focal_user, f_ratio_user FROM telescope WHERE id = ?",
                             (rc8,)).fetchone()) == (None, None)
    assert con.execute("SELECT count(*) FROM event WHERE verb LIKE 'telescope.%_user_cleared'"
                       ).fetchone()[0] == 2
    v.set_busy(True)
    assert not v.btn_restore_optics.isEnabled()
    con.close()


def test_panel_zestawy_srednica_i_bin2(qapp, tmp_path):
    """Panel „Zestawy": średnica = ogniskowa / f/ (200 mm dla RC8 1600/8), wiersz zestawu ze skalą
    bin 1 i bin 2 (2 ×) z planera; teleskop bez f/ - zdanie o braku.
    Mutanty: średnica liczona ogniskowa × f/; bin 2 = skala bin 1."""
    con, _obce, rc8 = _baza(tmp_path)
    v = TelescopeAxisView(con, now_fn=lambda: NOW)
    v.table.selectRow(_wiersz(v, rc8))
    assert v.aperture.text() == i18n.t("axis.tel.aperture", d="200", focal="1600", f="8")
    linia = v.rigs.item(0).text()
    s1 = 206.265 * 3.76 / 1600
    assert f"{s1:.2f}″/px" in linia and f"bin 2: {2 * s1:.2f}″/px" in linia
    n800 = con.execute("SELECT id FROM telescope WHERE telescop_canon = 'N800'").fetchone()[0]
    v.table.selectRow(_wiersz(v, n800))
    assert v.aperture.text() == i18n.t("axis.tel.aperture_unknown")
    con.close()


# ------------------------------------------------------------ kubełek ogniskowej + okno

def test_kubelek_ogniskowej_w_kolejce_i_drazenie(qapp, tmp_path):
    """Kolejka przeglądu ma wiersz „ogniskowa niezgodna" z tagiem `config_focal`, drążenie = lista
    predykatu, gest „Przypisz zestaw…" aktywny. Mutant: wiersz bez tagu (informacyjny)."""
    con, obce, _ = _baza(tmp_path)
    v = ObjectAxisView(con, now_fn=lambda: NOW)
    tagi = [v.review.item(i).data(Qt.UserRole) for i in range(v.review.count())]
    assert "config_focal" in tagi
    v.review.setCurrentRow(tagi.index("config_focal"))
    assert v.set_config_btn.isEnabled()
    assert v.set_config_btn.toolTip() == i18n.t("object.set_config_tip_focal")
    assert {r["frame_id"] for r in queries.focal_mismatch_frames(con)} == set(obce)
    con.close()


def test_okno_ogniskowej_lista_w_tolerancji_i_dopisz_nowy(qapp, tmp_path):
    """Tryb ogniskowej: lista = A140R, ED120R, N800 (w 5 % od 800) + „Dopisz nowy…"; RC8 (źródło,
    1600) poza; pola nowego teleskopu startują ogniskową grupy i parkiem źródła (w parku).
    Mutanty: lista bez filtra; park nowego teleskopu bez wartości źródła."""
    con, _obce, _ = _baza(tmp_path)
    dlg = cfg_mod.AssignConfigDialog(con, groups=queries.focal_mismatch_groups(con), focal=True)
    nazwy = [dlg.combo.itemData(i) for i in range(dlg.combo.count())]
    etykiety = {d[1] for d in nazwy if isinstance(d, tuple)}
    assert etykiety == {"A140R", "ED120R", "N800"}
    assert nazwy[-1] == cfg_mod.NEW_TELESCOPE
    dlg.combo.setCurrentIndex(dlg.combo.count() - 1)
    assert not dlg.new_form.isHidden()
    assert dlg.new_focal.text() == "800" and dlg.new_park.currentData() == 1
    dlg.new_name.setText("RC8 0.5x")
    dlg.new_f_ratio.setText("4")
    dlg._validate_and_accept()
    assert dlg.result() == QDialog.Accepted
    assert dlg.new_telescope == {"name": "RC8 0.5x", "focal_mm": 800.0, "f_ratio": 4.0,
                                 "in_park": 1, "source_telescope_id": _obce_src(con)}
    con.close()


def _obce_src(con):
    return con.execute("SELECT id FROM telescope WHERE telescop_canon = 'RC8'").fetchone()[0]


def test_okno_ogniskowej_odrzuca_f200_i_zajeta_nazwe(qapp, tmp_path):
    """[S6] Okno pyta TE SAME walidatory co klinga: f/200 i nazwa zajęta → błąd na etykiecie, okno
    zostaje otwarte. Mutant: okno z własną (luźniejszą) walidacją."""
    con, _obce, _ = _baza(tmp_path)
    dlg = cfg_mod.AssignConfigDialog(con, groups=queries.focal_mismatch_groups(con), focal=True)
    dlg.combo.setCurrentIndex(dlg.combo.count() - 1)
    dlg.new_name.setText("rc8")
    dlg._validate_and_accept()
    assert dlg.new_telescope is None and "zajęta" in dlg.error.text()
    dlg.new_name.setText("Nowy")
    dlg.new_f_ratio.setText("200")
    dlg._validate_and_accept()
    assert dlg.new_telescope is None and "f/" in dlg.error.text()
    con.close()


def test_gest_okna_tworzy_teleskop_i_kubelek_pustoszeje(qapp, tmp_path, monkeypatch):
    """Ścieżka gestu w przeglądzie: okno zwraca „Dopisz nowy…" → jedna klinga zakłada teleskop
    i przypina klatki ręką; kubełek ogniskowej pusty; wybór z listy przepina z nadpisaniem.
    Mutant: zapis wyboru z listy bez `overwrite` (klatki z zestawem automatu „zajęte")."""
    con, obce, rc8 = _baza(tmp_path)
    v = ObjectAxisView(con, now_fn=lambda: NOW)
    tagi = [v.review.item(i).data(Qt.UserRole) for i in range(v.review.count())]
    v.review.setCurrentRow(tagi.index("config_focal"))
    a140 = con.execute("SELECT id FROM telescope WHERE telescop_canon = 'A140R'").fetchone()[0]

    class _Fake:
        def __init__(self, con, *, groups, change=False, focal=False, parent=None):
            assert focal and not change
            self.selected = (a140, "A140R", [fid for g in groups for fid in g["frame_ids"]])
            self.new_telescope = None

        def exec(self):
            return QDialog.Accepted
    import horreum.gui.app as app_mod
    monkeypatch.setattr(app_mod, "AssignConfigDialog", _Fake)
    v._on_set_config()
    assert {r[0] for r in con.execute("SELECT config_source FROM frame WHERE id IN (?, ?)",
                                      obce)} == {"user"}
    assert resolver.optics_mismatch_frame_ids(con, "focal") == set()
    con.close()


# ------------------------------------------------------------ Porządki i perspektywa f/

def test_wiersze_porzadkow_optyki_licza_predykat(qapp, tmp_path):
    """Liczby wierszy „Ogniskowa niezgodna" i „f/ niezgodna" = długości zbiorów właściciela
    predykatu. Mutant: wiersz z własnym SELECT-em."""
    from horreum.gui import tasks as tasks_mod
    con, obce, rc8 = _baza(tmp_path)
    _klatka(con, "f200", telescop="RC8", focal=1600, f_ratio=200.0, camera_id=_kamera(con),
            path="X:\\archiwum\\X\\f200.fits")
    grouper.run_grouper(con, NOW)
    licz = tasks_mod._liczniki_osi(con)
    assert licz["focal_mismatch_frames"] == len(resolver.optics_mismatch_frame_ids(con, "focal")) == 2
    assert licz["f_ratio_mismatch_frames"] == len(queries.f_ratio_mismatch_frame_ids(con)) == 1
    klucze = [k for k, _, _ in tasks_mod._TASKS]
    assert "focal_mismatch_frames" in klucze and "f_ratio_mismatch_frames" in klucze
    con.close()


@pytest.fixture
def widok_f(qapp, tmp_path):
    """FramesView nad realnymi plikami FITS: trzy RC8 f/8 i jeden RC8 f/200 (wzorzec `wb_view`)."""
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    from horreum.gui.grid import FramesView
    con = db.open_db(str(tmp_path / "f.db"))
    for i, fr in enumerate((8.0, 8.0, 8.0, 200.0)):
        p = tmp_path / f"f{i}.fits"
        hdu = fits.PrimaryHDU(data=np.full((4, 4), i, dtype=np.int16))
        for k, val in (("TELESCOP", "RC8"), ("IMAGETYP", "Light"), ("FOCALLEN", 1600.0),
                       ("FOCRATIO", fr), ("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76)):
            hdu.header[k] = val
        hdu.writeto(str(p), overwrite=True)
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW,
                           summary=scan.ScanSummary())
    grouper.run_grouper(con, NOW)
    v = FramesView(con, now_fn=lambda: NOW)
    v._writeback_async = False
    yield v, con
    con.close()


def test_perspektywa_f_i_gest_naprawy_przez_szuflade(widok_f):
    """Perspektywa „f/ niezgodna z teleskopem" pokazuje tylko klatkę f/200; gest „Popraw f/
    w plikach…" stawia w szufladzie JEDEN wpis FOCRATIO 200 → 8 (f/ teleskopu), pliku nie rusza
    przed zapisem szuflady. Mutanty: gest zapisujący wprost (z pominięciem stagingu); cel z f/
    pliku zamiast teleskopu."""
    from horreum.gui import grid as grid_mod
    v, con = widok_f
    v.apply_perspective(grid_mod.PRESET_F_RATIO_MISMATCH)
    assert [r["frame_id"] for r in v.model._rows if "_group" not in r] == sorted(
        queries.f_ratio_mismatch_frame_ids(con))
    v.table.selectRow(0)
    v._on_fix_optics()
    wpisy = writeback.pending_for_run(con, v._run_id)
    assert [(w["keyword"], w["old_value"], w["new_value"], w["status"]) for w in wpisy] == [
        ("FOCRATIO", "200.0", "8.0", "pending")]
    karta = con.execute("SELECT value_num FROM cards WHERE keyword = 'FOCRATIO' AND frame_id = ?",
                        (v.model._rows[0]["frame_id"],)).fetchone()[0]
    assert karta == 200.0                                       # baza i plik bez zmian do „Zapisz"

# ------------------------------------------------------------ bramka kodu T24 (N2..N22)

def _komunikaty(widok):
    out = []
    widok.status_message.connect(out.append)
    return out


def test_n19_n15_n18_perspektywa_mowi_cel_i_powody(widok_f):
    """N19: wejście w perspektywę dokłada kolumnę FOCRATIO i receptę „RC8 200 → 8 (1 kl.)";
    N15/N18: zdanie gestu odmienia liczbę wpisów i podaje powód odmowy (strażnik większości).
    Mutanty: recepta bez celu; zdanie bez powodów odmów."""
    from horreum.gui import grid as grid_mod
    v, con = widok_f
    recepty = []
    v.status_recipe.connect(recepty.append)
    v._all_keywords = ["FOCRATIO", "TELESCOP"]
    v.apply_perspective(grid_mod.PRESET_F_RATIO_MISMATCH)
    QApplication.processEvents()
    assert "FOCRATIO" in v._columns
    tekst = " ".join(repr(r) for r in recepty)
    assert "RC8 200 → 8 (1 kl.)" in tekst
    msgs = _komunikaty(v)
    tid = con.execute("SELECT id FROM telescope WHERE telescop_canon = 'RC8'").fetchone()[0]
    with con:
        con.execute("UPDATE telescope SET f_ratio_nominal = 200.0 WHERE id = ?", (tid,))
    v.table.selectRow(0)
    v._on_fix_optics()
    assert v._run_id is None or not writeback.pending_for_run(con, v._run_id)
    assert "W szufladzie: 0 wpisów f/." in msgs[-1] and "większością" in msgs[-1]


def _baza_dwie_grupy(tmp_path):
    """Kubełek ogniskowej z dwiema grupami: 800 mm (folder M64) i 122 mm (folder L)."""
    con, obce, rc8 = _baza(tmp_path)
    cam = con.execute("SELECT id FROM camera").fetchone()[0]
    for i in range(2):
        _klatka(con, f"l{i}", telescop="RC8", focal=122, f_ratio=8.0, camera_id=cam,
                path=f"X:\\archiwum\\L\\l{i}.fits")
    grouper.run_grouper(con, NOW)
    return con


def _etykiety(dlg):
    return {dlg.combo.itemData(i)[1] for i in range(dlg.combo.count())
            if isinstance(dlg.combo.itemData(i), tuple)}


def _grupa(dlg, folder_konczy):
    return next(dlg.items.item(i) for i in range(dlg.items.count())
                if (dlg.items.item(i).data(cfg_mod.GROUP_ROLE)["folder"] or "").endswith(folder_konczy))


def test_n3_lista_sledzi_zaznacz_wszystkie_filtr_i_weryfikuje_przy_zapisie(qapp, tmp_path):
    """N3: odznaczenie grupy 122 → lista A140R/ED120R/N800; „zaznacz wszystkie" przebudowuje listę
    (przecięcie puste - wybór znika); filtr chowający grupę 122 oddaje listę 800; zapis z wyborem,
    którego lista nie nadążyła, odmawia z nazwą odstającej grupy.
    Mutanty: „zaznacz wszystkie" bez przebudowy; filtr bez przebudowy; zapis bez ponownej weryfikacji."""
    con = _baza_dwie_grupy(tmp_path)
    dlg = cfg_mod.AssignConfigDialog(con, groups=queries.focal_mismatch_groups(con), focal=True)
    assert _etykiety(dlg) == set()                       # 800 i 122 naraz - nic nie pasuje
    _grupa(dlg, "L").setCheckState(Qt.Unchecked)
    assert _etykiety(dlg) == {"A140R", "ED120R", "N800"}
    dlg.combo.setCurrentIndex(1)
    dlg.check_all.setCheckState(Qt.Checked)
    dlg._on_check_all()
    assert _etykiety(dlg) == set() and dlg.combo.currentData() is None
    _grupa(dlg, "L").setCheckState(Qt.Unchecked)
    _grupa(dlg, "L").setCheckState(Qt.Checked)
    dlg.filter.setText("M64")
    assert _etykiety(dlg) == {"A140R", "ED120R", "N800"}
    dlg.filter.setText("")
    _grupa(dlg, "L").setCheckState(Qt.Unchecked)
    dlg.combo.setCurrentIndex(1)
    dlg.items.blockSignals(True)                        # lista nie nadąża (zmiana bez sygnału)
    _grupa(dlg, "L").setCheckState(Qt.Checked)
    dlg.items.blockSignals(False)
    dlg._validate_and_accept()
    assert dlg.selected is None and "122" in dlg.error.text()
    con.close()


def test_n6_n7_dopisz_nowy_bramka_ogniskowej_i_wybor_parku_zostaje(qapp, tmp_path):
    """N6: nowy teleskop 800 przy zaznaczonej grupie 122 → odmowa z nazwą grupy; ogniskowa startowa
    idzie za zbiorem, dopóki user jej nie dotknął. N7: wybór parku usera przeżywa zmianę zbioru
    grup o tym samym źródle.
    Mutanty: „Dopisz nowy…" bez bramki; park przebudowywany przy każdej zmianie zbioru."""
    con = _baza_dwie_grupy(tmp_path)
    dlg = cfg_mod.AssignConfigDialog(con, groups=queries.focal_mismatch_groups(con), focal=True)
    dlg.combo.setCurrentIndex(dlg.combo.count() - 1)
    dlg.new_name.setText("Nowy")
    dlg.new_focal.setText("800")
    dlg._on_focal_edited("800")
    dlg._validate_and_accept()
    assert dlg.new_telescope is None and "122" in dlg.error.text()
    historyczny = next(i for i in range(dlg.new_park.count()) if dlg.new_park.itemData(i) == 0)
    dlg.new_park.setCurrentIndex(historyczny)
    _grupa(dlg, "L").setCheckState(Qt.Unchecked)        # to samo źródło - park usera zostaje
    assert dlg.new_park.currentData() == 0 and dlg.new_focal.text() == "800"
    dlg._validate_and_accept()
    assert dlg.new_telescope is not None and dlg.new_telescope["in_park"] == 0
    con.close()


def test_n6_ogniskowa_startowa_idzie_za_zbiorem(qapp, tmp_path):
    """N6: dopóki user nie dotknął pola, ogniskowa nowego teleskopu to ogniskowa zaznaczonych grup.
    Mutant: ogniskowa wpisywana raz, przy pierwszym pokazaniu."""
    con = _baza_dwie_grupy(tmp_path)
    dlg = cfg_mod.AssignConfigDialog(con, groups=queries.focal_mismatch_groups(con), focal=True)
    dlg.combo.setCurrentIndex(dlg.combo.count() - 1)
    _grupa(dlg, "M64").setCheckState(Qt.Unchecked)
    assert dlg.new_focal.text() == "122"
    _grupa(dlg, "M64").setCheckState(Qt.Checked)
    _grupa(dlg, "L").setCheckState(Qt.Unchecked)
    assert dlg.new_focal.text() == "800"
    con.close()


def test_n21_okno_podaje_dzisiejsza_ogniskowa_zrodla(qapp, tmp_path):
    """N21: wiersz grupy mówi ogniskową teleskopu źródłowego („dziś: RC8 1600 mm").
    Mutant: wiersz bez ogniskowej źródła."""
    con, _obce, _ = _baza(tmp_path)
    dlg = cfg_mod.AssignConfigDialog(con, groups=queries.focal_mismatch_groups(con), focal=True)
    assert "RC8 1600 mm" in dlg.items.item(0).text()
    con.close()


def test_n16_odmowa_klingi_wraca_do_okna_z_polami_i_recepta_cofniecia(qapp, tmp_path, monkeypatch):
    """N16: klinga odmawia (nazwa zajęta) → okno wraca z powodem, drugi przebieg zapisuje; po geście
    pada recepta „Cofnij dopisanie” (AR-133) zamiast zdania o scaleniu - klik wraca klatki do zestawu
    sprzed gestu i zdejmuje teleskop z Osi, zdanie wyniku mówi, ile klatek wróciło. N4: gest
    odświeża Oś teleskopu sygnałem.
    Mutanty: odmowa kończy gest; brak recepty; recepta bez wykonawcy; brak sygnału odświeżenia
    Osi."""
    from horreum.gui import tasks as tasks_mod
    con, obce, rc8 = _baza(tmp_path)
    tv = tasks_mod.TasksView(con, now_fn=lambda: NOW)
    v = tv.object_view
    tagi = [v.review.item(i).data(Qt.UserRole) for i in range(v.review.count())]
    v.review.setCurrentRow(tagi.index("config_focal"))
    odmowy = []

    class _Fake:
        przebieg = 0

        def __init__(self, con, *, groups, change=False, focal=False, parent=None):
            self.ids = [fid for g in groups for fid in g["frame_ids"]]
            self.selected = None

        def exec(self):
            _Fake.przebieg += 1
            nazwa = "rc8" if _Fake.przebieg == 1 else "RC8 0.5x"
            self.new_telescope = {"name": nazwa, "focal_mm": 800.0, "f_ratio": None, "in_park": 1,
                                  "source_telescope_id": rc8}
            self.selected = (None, nazwa, self.ids)
            return QDialog.Accepted

        def pokaz_odmowe(self, powod):
            odmowy.append(powod)
    import horreum.gui.app as app_mod
    monkeypatch.setattr(app_mod, "AssignConfigDialog", _Fake)
    przed = {f: tuple(con.execute("SELECT config_id, config_source FROM frame WHERE id = ?",
                                  (f,)).fetchone()) for f in obce}
    msgs = _komunikaty(v)
    recepty = []
    v.status_recipe.connect(recepty.append)
    v._on_set_config()
    assert len(odmowy) == 1 and "zajęta" in odmowy[0]
    assert not any("Scal" in m for m in msgs)
    [recepta] = recepty
    assert recepta == i18n.t("object.config_undo_add", telescope="RC8 0.5x")
    nowy = con.execute("SELECT id FROM telescope WHERE telescop_canon = 'RC8 0.5x'").fetchone()[0]
    def os_ids():
        return {tv.axis_view.table.item(r, COL_ID).data(Qt.UserRole)
                for r in range(tv.axis_view.table.rowCount())}
    assert nowy in os_ids()
    recepta.czlony[0].wykonaj()
    assert (i18n.t_plural("object.config_undo_add.done", 2, telescope="RC8 0.5x")
            + i18n.t("object.config_undo_add.retired", telescope="RC8 0.5x")) in msgs
    assert {f: tuple(con.execute("SELECT config_id, config_source FROM frame WHERE id = ?",
                                 (f,)).fetchone()) for f in obce} == przed
    assert nowy not in os_ids()
    con.close()


def test_gospodarz_pokazuje_recepte_osi_w_porzadkach(qapp, tmp_path):
    """Recepta gestu osi („Cofnij dopisanie”) staje na pasku gospodarza, gdy Porządki są widoczne -
    klik paska wykonuje jej człon; poza Porządkami pasek jej nie bierze (mówi o innym ekranie).
    Mutant: brak podpięcia `status_recipe` w `MainWindow` albo recepta na pasku z każdej strony."""
    from horreum.gui.app import NAV_PORZADKI, NAV_ZBIORY, MainWindow
    from horreum.gui.grid_model import CzlonRecepty, Recepta
    con, _obce, _ = _baza(tmp_path)
    con.close()
    win = MainWindow(str(tmp_path / "o.db"))
    try:
        klik = []
        recepta = Recepta([CzlonRecepty("Cofnij dopisanie „X”", lambda: klik.append(1))])
        win._show_view(NAV_ZBIORY)
        win.object_view.status_recipe.emit(recepta)
        assert win._czlony_recepty != recepta.czlony
        win._show_view(NAV_PORZADKI)
        win.object_view.status_recipe.emit(recepta)
        assert win._czlony_recepty == recepta.czlony
        win._wykonaj_recepte()
        assert klik == [1]
    finally:
        win.close()


def test_os_teleskopu_cofa_dopisanie_po_restarcie_prawdziwym_klikiem(qapp, tmp_path):
    """Trwała droga powrotu (AR-133, bramka `kimi` Z1): gest „Dopisz nowy…” zrobiony PRZED otwarciem
    okna (recepta paska nie istnieje - restart), w Porządkach na Osi teleskopu wiersz tego teleskopu
    ma czynny „Cofnij dopisanie”, wiersz teleskopu skanu - wygaszony; klik przycisku wraca klatki,
    zdejmuje teleskop z listy i mówi zdaniem wyniku. Przeskok przez inną stronę nie gasi gestu.
    Mutant: gest tylko na recepcie paska (po restarcie brak drogi powrotu); przycisk czynny dla
    każdego wiersza."""
    from horreum.gui.app import NAV_PORZADKI, NAV_ZBIORY, MainWindow
    con, obce, rc8 = _baza(tmp_path)
    przed = {f: tuple(con.execute("SELECT config_id, config_source FROM frame WHERE id = ?",
                                  (f,)).fetchone()) for f in obce}
    tid, _g = repo.user_assign_config_new_telescope(
        con, frame_ids=obce, name="RC8 0.5x", focal_mm=800.0, in_park=1, source_telescope_id=rc8,
        now=NOW)
    con.close()
    win = MainWindow(str(tmp_path / "o.db"))
    try:
        win._show_view(NAV_PORZADKI)
        win._show_view(NAV_ZBIORY)
        win._show_view(NAV_PORZADKI)
        v = win.axis_view
        msgs = _komunikaty(v)
        v.table.selectRow(_wiersz(v, rc8))
        assert not v.btn_undo_add.isEnabled()
        v.table.selectRow(_wiersz(v, tid))
        assert v.btn_undo_add.isEnabled()
        v.btn_undo_add.click()
        assert (i18n.t_plural("object.config_undo_add.done", 2, telescope="RC8 0.5x")
                + i18n.t("object.config_undo_add.retired", telescope="RC8 0.5x")) in msgs
        assert tid not in {v.table.item(r, COL_ID).data(Qt.UserRole)
                           for r in range(v.table.rowCount())}
        assert {f: tuple(win.con.execute("SELECT config_id, config_source FROM frame WHERE id = ?",
                                         (f,)).fetchone()) for f in obce} == przed
    finally:
        win.close()


def test_zdanie_cofniecia_gdy_zadna_klatka_nie_wrocila(qapp, tmp_path):
    """Wszystkie klatki gestu przepięte ręką po geście: cofnięcie nic nie wraca - zdanie nie mówi
    „Cofnięto dopisanie: 0 klatek wróciło”, tylko „żadna klatka nie wróciła”, a dalej ile zostało
    i że teleskop (bez klatek) zszedł z osi (bramka `kimi` Z3).
    Mutant: zdanie `done` z liczbą 0."""
    con, obce, rc8 = _baza(tmp_path)
    tid, _g = repo.user_assign_config_new_telescope(
        con, frame_ids=obce, name="RC8 0.5x", focal_mm=800.0, in_park=1, source_telescope_id=rc8,
        now=NOW)
    repo.user_assign_config(con, frame_ids=obce, telescope_id=rc8, now=NOW, overwrite=True)
    v = TelescopeAxisView(con, now_fn=lambda: NOW)
    msgs = _komunikaty(v)
    v.table.selectRow(_wiersz(v, tid))
    v.btn_undo_add.click()
    assert msgs[0] == (i18n.t("object.config_undo_add.nothing", telescope="RC8 0.5x")
                       + i18n.t_plural("object.config_undo_add.kept", 2)
                       + i18n.t("object.config_undo_add.retired", telescope="RC8 0.5x"))
    assert "Cofnięto" not in msgs[0]
    con.close()


def test_cofniecie_dopisania_w_biegu_dostawy_czeka_i_oddaje_recepte(qapp, tmp_path):
    """Klik „Cofnij dopisanie” w trakcie etapu Dostawy: zero zapisu, zdanie o czekaniu, a recepta
    wraca (raport ją zgasił) - droga powrotu nie przepada razem z odmową.
    Mutant: brak bramki `_busy` (zapis w trakcie etapu) albo odmowa bez ponownej recepty."""
    con, obce, rc8 = _baza(tmp_path)
    tid, _g = repo.user_assign_config_new_telescope(
        con, frame_ids=obce, name="RC8 0.5x", focal_mm=800.0, in_park=1,
        source_telescope_id=rc8, now=NOW)
    v = ObjectAxisView(con, now_fn=lambda: NOW)
    msgs, recepty = _komunikaty(v), []
    v.status_recipe.connect(recepty.append)
    v.set_busy(True)
    n = con.execute("SELECT count(*) FROM event").fetchone()[0]
    v._recepta_cofniecia_dopisania(tid, "RC8 0.5x").czlony[0].wykonaj()
    assert msgs == [i18n.t("object.config_undo_add.busy")] and len(recepty) == 1
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == n
    v.set_busy(False)
    recepty[0].czlony[0].wykonaj()
    assert con.execute("SELECT retired_at FROM telescope WHERE id = ?", (tid,)).fetchone()[0] == NOW
    con.close()


def test_n4_wejscie_na_os_teleskopu_odswieza_ja(qapp, tmp_path):
    """N4: wiersz Porządków prowadzący na Oś teleskopu przeładowuje ją z bazy.
    Mutant: wejście bez `axis_view.refresh()`."""
    from horreum.gui import tasks as tasks_mod
    con, _obce, _ = _baza(tmp_path)
    tv = tasks_mod.TasksView(con, now_fn=lambda: NOW)
    repo.propose_telescope(con, telescop_canon="Nowy", focal_nominal=500, now=NOW)
    it = next(tv.tasks.item(i) for i in range(tv.tasks.count())
              if tv.tasks.item(i).data(Qt.UserRole) == "telescopes_unlabeled")
    tv._on_task_clicked(it)
    assert "Nowy" in {tv.axis_view.table.item(r, 1).text()
                      for r in range(tv.axis_view.table.rowCount())}
    con.close()


def test_n5_potwierdzenie_wartosci_rownej_plikom_zapisuje_reke(qapp, tmp_path):
    """N5: edytor delegata zatwierdza „1600" w komórce pokazującej 1600 z plików → ręka 1600
    i komunikat; pusty wpis bez ręki → „bez zmian" (pasek nie zostawia starego komunikatu).
    Mutant: porównanie z tekstem komórki zamiast ze stanem ręki."""
    from PySide6.QtWidgets import QLineEdit
    con, _obce, rc8 = _baza(tmp_path)
    v = TelescopeAxisView(con, now_fn=lambda: NOW)
    msgs = _komunikaty(v)
    idx = v.table.model().index(_wiersz(v, rc8), COL_FOCAL)
    ed = QLineEdit()
    v._optyka_delegat.setEditorData(ed, idx)
    assert ed.text() == "1600"
    v._optyka_delegat.setModelData(ed, v.table.model(), idx)
    QApplication.processEvents()
    assert con.execute("SELECT focal_user FROM telescope WHERE id = ?", (rc8,)).fetchone()[0] == 1600.0
    assert msgs[-1] == i18n.t("axis.tel.optics_saved")
    n800 = con.execute("SELECT id FROM telescope WHERE telescop_canon = 'N800'").fetchone()[0]
    v._on_optics_edited(_wiersz(v, n800), COL_FRATIO, "")
    assert msgs[-1] == i18n.t("axis.tel.optics_unchanged")
    con.close()


def test_n8_zajetosc_osi_odmawia_zapisu_optyki(qapp, tmp_path):
    """N8: w trakcie etapu edycja optyki i „Przywróć z plików" odmawiają z komunikatem, a zmiana
    zaznaczenia nie zapala przycisku. Mutant: brak flagi `_busy` w handlerach."""
    con, _obce, rc8 = _baza(tmp_path)
    repo.set_telescope_focal(con, telescope_id=rc8, focal_mm=1580, now=NOW)
    v = TelescopeAxisView(con, now_fn=lambda: NOW)
    msgs = _komunikaty(v)
    v.set_busy(True)
    v.table.selectRow(_wiersz(v, rc8))
    assert not v.btn_restore_optics.isEnabled()
    v._on_optics_edited(_wiersz(v, rc8), COL_FOCAL, "1500")
    v._on_restore_optics()
    assert con.execute("SELECT focal_user FROM telescope WHERE id = ?", (rc8,)).fetchone()[0] == 1580.0
    assert msgs[-1] == i18n.t("axis.tel.optics_busy")
    con.close()


def test_n2_n5_komorka_mowi_nieaktualne_i_wczesniej_zapisane(qapp, tmp_path):
    """N2: kolumna automatu różna od mody plików → tooltip „Nieaktualne - Dostawa przeliczy";
    N5: pliki milczą, kolumna niesie wartość → „zapisano ją wcześniej"; „Przywróć z plików" mówi
    przed zapisem, co zostanie. Mutant: komórka podpisana „z plików" mimo rozjazdu."""
    con, _obce, rc8 = _baza(tmp_path)
    with con:
        con.execute("UPDATE telescope SET f_ratio_nominal = 9.0 WHERE id = ?", (rc8,))
    pusty, _ = repo.propose_telescope(con, telescop_canon="RC8R", focal_nominal=1200, now=NOW)
    repo.set_telescope_focal(con, telescope_id=pusty, focal_mm=1200, now=NOW)
    v = TelescopeAxisView(con, now_fn=lambda: NOW)
    assert v.table.item(_wiersz(v, rc8), COL_FRATIO).toolTip().startswith("Nieaktualne")
    v.table.selectRow(_wiersz(v, pusty))
    assert "zostanie 1200 mm zapisane wcześniej" in v.btn_restore_optics.toolTip()
    v.btn_restore_optics.click()
    assert "zapisano ją wcześniej" in v.table.item(_wiersz(v, pusty), COL_FOCAL).toolTip()
    con.close()


def test_n20_n22_wiersz_ogniskowej_przy_zerze_i_blok_optyki(qapp, tmp_path):
    """N20: przy pustym kubełku ogniskowej wiersz zostaje informacyjny ze zdaniem o sobie;
    N22: średnica i „Przywróć z plików" stoją nad listą Zestawów.
    Mutanty: wiersz znika przy zerze; blok optyki pod listą zestawów."""
    con, obce, rc8 = _baza(tmp_path)
    repo.user_assign_config(con, frame_ids=obce, telescope_id=rc8, now=NOW, overwrite=True)
    v = ObjectAxisView(con, now_fn=lambda: NOW)
    teksty = [v.review.item(i).text() for i in range(v.review.count())]
    assert i18n.t("object.config_focal_line") in teksty
    assert v.review.item(teksty.index(i18n.t("object.config_focal_line"))).data(Qt.UserRole) is None
    t = TelescopeAxisView(con, now_fn=lambda: NOW)
    lay = t.rigs.parentWidget().layout()
    pozycja = {lay.itemAt(i).widget(): i for i in range(lay.count()) if lay.itemAt(i).widget()}
    assert pozycja[t.aperture] < pozycja[t.btn_restore_optics] < pozycja[t.rigs]
    con.close()
