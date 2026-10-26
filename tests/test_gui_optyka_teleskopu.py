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
        win.tasks_view.otworz_os_teleskopu()      # wejście z Porządków czyta oś (montaż leniwy, AR-175)
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
    """AR-310: klik recepty „Cofnij dopisanie” w trakcie etapu Dostawy - zero zapisu, zdanie odroczenia
    kanałem wyniku osi (`wynik_cofniecia`) BEZ recepty, bo teraz nic nie zadziała; koniec etapu
    (`set_busy(False)`) podaje zdanie gotowości z receptą, a jej wykonanie zdejmuje teleskop.
    Mutanty: odmowa z natychmiastową receptą (raporty odświeżenia po przebiegu ją gasiły, a zdanie
    obiecywało czekanie); `set_busy` bez podania odłożonych; brak bramki `_busy`."""
    con, obce, rc8 = _baza(tmp_path)
    tid, _g = repo.user_assign_config_new_telescope(
        con, frame_ids=obce, name="RC8 0.5x", focal_mm=800.0, in_park=1,
        source_telescope_id=rc8, now=NOW)
    v = ObjectAxisView(con, now_fn=lambda: NOW)
    msgs, recepty, wyniki = _komunikaty(v), [], []
    v.status_recipe.connect(recepty.append)
    v.wynik_cofniecia.connect(lambda zdanie, recepta: wyniki.append((zdanie, recepta)))
    v.set_busy(True)
    n = con.execute("SELECT count(*) FROM event").fetchone()[0]
    v._recepta_cofniecia_dopisania(tid, "RC8 0.5x").czlony[0].wykonaj()
    assert wyniki == [(i18n.t("object.config_undo_add.deferred", telescope="RC8 0.5x"), None)]
    assert msgs == [] and recepty == []
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == n
    v.set_busy(False)
    [(zdanie, recepta)] = wyniki[1:]
    assert zdanie == i18n.t("object.config_undo_add.ready", telescope="RC8 0.5x"), zdanie
    recepta.czlony[0].wykonaj()
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
    from PySide6.QtWidgets import QStyleOptionViewItem
    con, _obce, rc8 = _baza(tmp_path)
    v = TelescopeAxisView(con, now_fn=lambda: NOW)
    msgs = _komunikaty(v)
    idx = v.table.model().index(_wiersz(v, rc8), COL_FOCAL)
    ed = v._optyka_delegat.createEditor(v.table.viewport(), QStyleOptionViewItem(), idx)
    v._optyka_delegat.setEditorData(ed, idx)
    assert ed.text() == "1600"
    v._optyka_delegat.setModelData(ed, v.table.model(), idx)
    QApplication.processEvents()
    assert con.execute("SELECT focal_user FROM telescope WHERE id = ?", (rc8,)).fetchone()[0] == 1600.0
    assert msgs[-1] == i18n.t("axis.tel.optics_saved")
    n800 = con.execute("SELECT id FROM telescope WHERE telescop_canon = 'N800'").fetchone()[0]
    v._on_optics_edited(n800, COL_FRATIO, "")
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
    v._on_optics_edited(rc8, COL_FOCAL, "1500")
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


# ------------------------------------------------------------ AR-277: recepta perspektywy f/ trwa

import threading  # noqa: E402
import time  # noqa: E402

from PySide6.QtCore import QCoreApplication, QEventLoop  # noqa: E402

_BEZPIECZNIK_S = 60


def _czekaj(warunek, opis):
    """Pętla zdarzeń do warunku - `processEvents` + `sleep` (oddaje GIL wątkom tła), z bezpiecznikiem."""
    koniec = time.monotonic() + _BEZPIECZNIK_S
    while not warunek():
        if time.monotonic() > koniec:
            raise AssertionError(f"bezpiecznik {_BEZPIECZNIK_S} s: {opis}")
        QCoreApplication.processEvents(QEventLoop.AllEvents, 50)
        time.sleep(0.005)


def _bezczynny(g):
    return (g._pola is not None and g._pola_thread is None and g._zbior_thread is None
            and not g._zbior_w_drodze())


def _baza_f_w_pliku(tmp_path):
    """Baza w pliku nad prawdziwymi FITS jak `widok_f` (3× RC8 f/8, 1× f/200) z pięcioma keywordami,
    które przy równym pokryciu idą przed FOCRATIO alfabetycznie - kolumny domyślne pierwszego wyniku
    Pól (6 najczęstszych) FOCRATIO nie obejmują, więc wejście w perspektywę musi ją dołożyć."""
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    path = tmp_path / "f.db"
    con = db.open_db(str(path))
    for i, fr in enumerate((8.0, 8.0, 8.0, 200.0)):
        p = tmp_path / f"f{i}.fits"
        hdu = fits.PrimaryHDU(data=np.full((4, 4), i, dtype=np.int16))
        for k, val in (("TELESCOP", "RC8"), ("IMAGETYP", "Light"), ("FOCALLEN", 1600.0),
                       ("FOCRATIO", fr), ("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76),
                       ("AIRMASS", 1.2), ("CCD-TEMP", -10.0), ("DATE-OBS", f"2024-03-1{i}T21:00:00"),
                       ("EXPTIME", 300.0), ("FILTER", "Ha")):
            hdu.header[k] = val
        hdu.writeto(str(p), overwrite=True)
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW,
                           summary=scan.ScanSummary())
    grouper.run_grouper(con, NOW)
    con.close()
    return str(path)


def _recepta_na_pasku(win):
    return win.recipe_label.text() if win.recipe_label.isVisible() else ""


def test_recepta_optyki_przezywa_przeladowanie_z_kolumna_i_powrot_do_zbiorow(qapp, tmp_path):
    """AR-277, prawdziwa kolejność w oknie gospodarza (skład zbioru i Pola w wątkach tła): wejście
    drogą Porządków dokłada FOCRATIO, przeładowanie z kolumną kończy się raportem „Grid: N klatek…”,
    a recepta „RC8 200 → 8 (1 kl.)” stoi PO nim; po wyjściu na Dom i powrocie do Zbiorów wraca.
    Falsyfikator: `ponow_recepte` bez recepty perspektywy - raport przeładowania z kolumną ją gasi
    (natywnie: widoczna 0,42-0,85 s), a po powrocie do Zbiorów nie wraca."""
    from horreum.gui.app import NAV_DOM, NAV_ZBIORY, MainWindow
    from horreum.gui.grid_model import PRESET_F_RATIO_MISMATCH
    win = MainWindow(_baza_f_w_pliku(tmp_path))
    try:
        win.resize(1600, 900)
        win.show()
        g = win.grid_view
        _czekaj(lambda: _bezczynny(g), "wątki tła po otwarciu bazy")
        assert "FOCRATIO" not in g._columns and "FOCRATIO" in g._all_keywords
        win._on_open_collection(PRESET_F_RATIO_MISMATCH)
        _czekaj(lambda: _bezczynny(g) and "FOCRATIO" in g._columns, "przeładowanie z kolumną")
        assert win._pelny_komunikat.startswith("Grid:"), win._pelny_komunikat
        assert "RC8 200 → 8 (1 kl.)" in _recepta_na_pasku(win), _recepta_na_pasku(win)
        win._show_view(NAV_DOM)
        assert _recepta_na_pasku(win) == ""
        win._show_view(NAV_ZBIORY)
        assert "RC8 200 → 8 (1 kl.)" in _recepta_na_pasku(win), _recepta_na_pasku(win)
    finally:
        win.close()


def test_recepta_optyki_stoi_w_trakcie_przeladowania_z_kolumna(qapp, tmp_path, monkeypatch):
    """AR-277: przeładowanie z dołożoną kolumną FOCRATIO trzymane bramą w wątku tła (pivot kart
    z FOCRATIO) - przez cały skład pasek mówi „Czytam klatki…” RAZEM z receptą, a po przyłożeniu
    recepta zostaje. Falsyfikator: ogon wejścia bez recepty po zleceniu przeładowania (raport
    „Czytam klatki…” gasi receptę przyłożenia zbioru perspektywy, pasek bez niej do końca składu)."""
    from horreum.gui.app import MainWindow
    from horreum.gui.grid_model import PRESET_F_RATIO_MISMATCH
    brama, wszedl = threading.Event(), threading.Event()
    prawdziwe = queries.cards_pivot

    def _cp(con, ids, kws):
        if "FOCRATIO" in kws:
            wszedl.set()
            brama.wait(_BEZPIECZNIK_S)
        return prawdziwe(con, ids, kws)
    win = MainWindow(_baza_f_w_pliku(tmp_path))
    try:
        win.resize(1600, 900)
        win.show()
        g = win.grid_view
        _czekaj(lambda: _bezczynny(g), "wątki tła po otwarciu bazy")
        monkeypatch.setattr(queries, "cards_pivot", _cp)
        win._on_open_collection(PRESET_F_RATIO_MISMATCH)
        _czekaj(lambda: wszedl.is_set(), "skład z kolumną FOCRATIO w drodze")
        QApplication.processEvents()
        assert g._zbior_w_drodze() and win._pelny_komunikat == i18n.t("busy.read_frames")
        assert "RC8 200 → 8 (1 kl.)" in _recepta_na_pasku(win), _recepta_na_pasku(win)
        brama.set()
        _czekaj(lambda: _bezczynny(g), "przyłożenie przeładowania z kolumną")
        assert "RC8 200 → 8 (1 kl.)" in _recepta_na_pasku(win), _recepta_na_pasku(win)
    finally:
        brama.set()
        win.close()


def test_wejscie_przed_wynikiem_pol_doklada_focratio_i_recepte(qapp, tmp_path, monkeypatch):
    """AR-277: wejście w perspektywę, zanim pierwszy wynik Pól doszedł (brama na pokryciu w wątku tła):
    `_all_keywords` puste, kolumny brak. Wynik Pól dokłada FOCRATIO do kolumn domyślnych, przeładowanie
    po nim kończy się raportem, a recepta stoi po nim. Falsyfikatory: `_zastosuj_pola` bez kolumny
    perspektywy (FOCRATIO nie dochodzi); `ponow_recepte` bez recepty perspektywy (raport ją gasi)."""
    from horreum.gui.app import MainWindow
    from horreum.gui.grid_model import PRESET_F_RATIO_MISMATCH
    brama = threading.Event()
    prawdziwe = queries.keyword_facets

    def _kf(con):
        brama.wait(_BEZPIECZNIK_S)
        return prawdziwe(con)
    monkeypatch.setattr(queries, "keyword_facets", _kf)
    win = MainWindow(_baza_f_w_pliku(tmp_path))
    try:
        win.resize(1600, 900)
        win.show()
        g = win.grid_view
        _czekaj(lambda: g._zbior_thread is None and not g._zbior_w_drodze(), "zbiór startu")
        assert g._pola is None and not (getattr(g, "_all_keywords", None) or [])
        win._on_open_collection(PRESET_F_RATIO_MISMATCH)
        _czekaj(lambda: g._zbior_thread is None and not g._zbior_w_drodze(), "zbiór perspektywy")
        assert "FOCRATIO" not in g._columns
        brama.set()
        _czekaj(lambda: _bezczynny(g) and "FOCRATIO" in g.model._keywords, "wynik Pól i przeładowanie")
        assert "FOCRATIO" in g._columns and len(g._columns) == 7, g._columns
        assert win._pelny_komunikat.startswith("Grid:"), win._pelny_komunikat
        assert "RC8 200 → 8 (1 kl.)" in _recepta_na_pasku(win), _recepta_na_pasku(win)
    finally:
        brama.set()
        win.close()


def test_recepta_optyki_stoi_w_trakcie_przeladowania_po_wyniku_pol(qapp, tmp_path, monkeypatch):
    """AR-277: wejście przed pierwszym wynikiem Pól; wynik Pól dokłada FOCRATIO i przeładowuje zbiór,
    a skład z kolumną trzymany bramą (pivot kart z FOCRATIO) - przez cały skład pasek mówi „Czytam
    klatki…” RAZEM z receptą, bez przerwy, i po przyłożeniu recepta zostaje. Falsyfikator: wynik Pól
    przeładowuje bez recepty (raport „Czytam klatki…” gasi ją do końca składu - natywnie 0,67 s)."""
    from horreum.gui.app import MainWindow
    from horreum.gui.grid_model import PRESET_F_RATIO_MISMATCH
    pola, sklad, wszedl = threading.Event(), threading.Event(), threading.Event()
    prawdziwe_kf, prawdziwe_cp = queries.keyword_facets, queries.cards_pivot

    def _kf(con):
        pola.wait(_BEZPIECZNIK_S)
        return prawdziwe_kf(con)

    def _cp(con, ids, kws):
        if "FOCRATIO" in kws:
            wszedl.set()
            sklad.wait(_BEZPIECZNIK_S)
        return prawdziwe_cp(con, ids, kws)
    monkeypatch.setattr(queries, "keyword_facets", _kf)
    monkeypatch.setattr(queries, "cards_pivot", _cp)
    win = MainWindow(_baza_f_w_pliku(tmp_path))
    try:
        win.resize(1600, 900)
        win.show()
        g = win.grid_view
        _czekaj(lambda: g._zbior_thread is None and not g._zbior_w_drodze(), "zbiór startu")
        win._on_open_collection(PRESET_F_RATIO_MISMATCH)
        _czekaj(lambda: g._zbior_thread is None and not g._zbior_w_drodze(), "zbiór perspektywy")
        assert g._pola is None and "RC8 200 → 8 (1 kl.)" in _recepta_na_pasku(win)
        pola.set()
        _czekaj(lambda: wszedl.is_set(), "skład z kolumną FOCRATIO po wyniku Pól")
        QApplication.processEvents()
        assert g._zbior_w_drodze() and win._pelny_komunikat == i18n.t("busy.read_frames")
        assert "RC8 200 → 8 (1 kl.)" in _recepta_na_pasku(win), _recepta_na_pasku(win)
        sklad.set()
        _czekaj(lambda: _bezczynny(g) and "FOCRATIO" in g.model._keywords, "przyłożenie składu")
        assert "RC8 200 → 8 (1 kl.)" in _recepta_na_pasku(win), _recepta_na_pasku(win)
    finally:
        pola.set()
        sklad.set()
        win.close()


def test_zuzyta_recepta_gestu_oddaje_miejsce_recepcie_optyki(widok_f, monkeypatch):
    """AR-277: w perspektywie f/ gest uwag zostawia receptę „Cofnij uwagi”, potem inna uwaga ręką
    przykrywa cel gestu (recepta gestu przestaje być prawdą) i PRAWDZIWE przeładowanie składa recepty
    ze stanu - wraca recepta perspektywy, nie pusta. Falsyfikator: `ponow_recepte` kończy się pustą
    receptą zużytego gestu."""
    from horreum.gui import grid as grid_mod
    from horreum.gui.note_dialog import NoteIntent
    v, con = widok_f

    class _Okno:
        def __init__(self, *, current, frame_count, parent=None):
            self.intent = NoteIntent("set", "chmury")

        def exec(self):
            return 1
    monkeypatch.setattr(grid_mod, "NoteDialog", _Okno)
    recepty = []
    v.status_recipe.connect(recepty.append)
    v.apply_perspective(grid_mod.PRESET_F_RATIO_MISMATCH)
    fid = v.model._rows[0]["frame_id"]
    v._przywroc_zaznaczenie([fid])
    v._on_notes()
    assert recepty[-1].czlony and "200 → 8" not in str(recepty[-1]), recepty[-1]   # recepta gestu
    repo.set_frame_note(con, frame_ids=[fid], body="inna", now=NOW)
    recepty.clear()
    v.refresh()
    assert recepty and "RC8 200 → 8 (1 kl.)" in str(recepty[-1]), recepty


def test_recepta_optyki_nie_wraca_po_gescie_w_szufladzie_i_gasnie_poza_perspektywa(widok_f):
    """AR-277: „Popraw f/ w plikach…” stawia wpis w szufladzie (plik i `header.focratio_raw` bez zmian
    do „Zatwierdź”) - następne przeładowanie NIE wskrzesza recepty każącej wykonać ten gest. Zejście do
    innej perspektywy - przeładowania recepty f/ już nie podają. Falsyfikatory: recepta liczona z samego
    zbioru (bez stagingu); recepta perspektywy bez warunku flagi."""
    from horreum.gui import grid as grid_mod
    v, _con = widok_f
    recepty = []
    v.status_recipe.connect(recepty.append)
    v.apply_perspective(grid_mod.PRESET_F_RATIO_MISMATCH)
    assert any("RC8 200 → 8 (1 kl.)" in str(r) for r in recepty), recepty
    v.table.selectRow(0)
    v._on_fix_optics()
    assert v._pending_count() == 1
    recepty.clear()
    v.refresh()
    assert not any("200 → 8" in str(r) for r in recepty), recepty
    v.apply_perspective(grid_mod._PRESET_CZYSTY)            # wszystkie klatki, także f/8 RC8
    assert len(v._frame_ids) == 4
    recepty.clear()
    v.refresh()
    assert not any("→ f/" in str(r) for r in recepty), recepty


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_podpowiedzi_optyki_nazywaja_przycisk_szuflady(lang):
    """AR-277: podpowiedź gestu i opis wiersza Porządków mówią słowem przycisku szuflady
    (`grid.action.commit`), nie „Zapisz”/“Save”, którego w szufladzie nie ma.
    Falsyfikator: stare słowo w którymkolwiek z dwóch tekstów."""
    i18n.set_lang(lang)
    try:
        przycisk = i18n.t("grid.action.commit")
        stare = {"pl": "Zapisz", "en": "Save"}[lang]
        for tekst in (i18n.t("grid.optics.fix_tip"),
                      i18n.t("tasks.f_ratio_mismatch_tip", fix=i18n.t("grid.optics.fix_action"))):
            assert przycisk in tekst and stare not in tekst, tekst
    finally:
        i18n.set_lang("pl")


# ------------------------------------------------------------ AR-326: zapis optyki tylko ze zmiany tekstu

def _zdarzenia_reki(con):
    return con.execute("SELECT count(*) FROM event WHERE verb LIKE 'telescope.%_user_%'").fetchone()[0]


def test_przemalowanie_komorki_optyki_poza_straza_nie_zapisuje_reki(qapp, tmp_path):
    """AR-326: kolor, podpowiedź, font, tło i role danych komórek f/ i Ogniskowej ustawione POZA `_loading`
    (`itemChanged` strzela przy każdym `setData`) nie zapisują werdyktu ręki - filtr ról `_on_data_changed`.
    Falsyfikatory: podpięcie `itemChanged` zamiast `dataChanged`; filtr przepuszczający każdą rolę."""
    from PySide6.QtGui import QBrush, QColor
    from horreum.gui.app import ROLA_RODZAJU_KOLORU, _ROLA_WARTOSCI_EDYTORA
    con, _obce, rc8 = _baza(tmp_path)
    v = TelescopeAxisView(con, now_fn=lambda: NOW)
    przed = _zdarzenia_reki(con)
    r = _wiersz(v, rc8)
    assert not v._loading
    for c in (COL_FOCAL, COL_FRATIO):
        item = v.table.item(r, c)
        item.setForeground(QBrush(QColor("#f0b040")))
        item.setToolTip("podpowiedź spoza odświeżenia")
        item.setFont(item.font())
        item.setBackground(QBrush(QColor("#000000")))
        item.setData(ROLA_RODZAJU_KOLORU, "werdykt")
        item.setData(_ROLA_WARTOSCI_EDYTORA, "999")
    QApplication.processEvents()
    assert _zdarzenia_reki(con) == przed
    assert tuple(con.execute("SELECT focal_user, f_ratio_user FROM telescope WHERE id = ?",
                             (rc8,)).fetchone()) == (None, None)
    con.close()


def test_zmiana_tekstu_przez_model_rola_edycji_zapisuje_reke(qapp, tmp_path):
    """AR-326: zmiana tekstu komórki optyki przez MODEL (`setData(..., Qt.EditRole)` - droga domyślnego edytora
    i kodu) przechodzi przez `dataChanged` z rolą edycji i zapisuje rękę. Delegat optyki omija model
    (`_OptykaEdycja.setModelData`), więc tylko ten test obciąża filtr ról. Falsyfikator: filtr odcinający
    `EditRole` (albo każdą rolę tekstu)."""
    con, _obce, rc8 = _baza(tmp_path)
    v = TelescopeAxisView(con, now_fn=lambda: NOW)
    przed = _zdarzenia_reki(con)
    idx = v.table.model().index(_wiersz(v, rc8), COL_FOCAL)
    assert v.table.model().setData(idx, "1580", Qt.EditRole)
    assert con.execute("SELECT focal_user FROM telescope WHERE id = ?", (rc8,)).fetchone()[0] == 1580.0
    assert _zdarzenia_reki(con) == przed + 1
    con.close()


# ------------------------------------------------------------ AR-321: kolejka odłożeń u gospodarza, straż recepty

def _baza_z_dopisanymi(tmp_path, ile=1):
    """Baza `_baza` z `ile` teleskopami „Dopisz nowy…” (po jednej obcej klatce) - ścieżka i lista
    `(teleskop, etykieta)`. Połączenie zamknięte: okno otwiera własne."""
    con, obce, rc8 = _baza(tmp_path)
    dopisane = []
    for i in range(ile):
        etykieta = f"RC8 0.{i + 5}x"
        tid, _g = repo.user_assign_config_new_telescope(
            con, frame_ids=[obce[i]], name=etykieta, focal_mm=800.0 + i, in_park=1,
            source_telescope_id=rc8, now=NOW)
        dopisane.append((tid, etykieta))
    con.close()
    return str(tmp_path / "o.db"), dopisane


def _okno(sciezka, monkeypatch):
    from horreum.gui.app import MainWindow
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    return MainWindow(sciezka)


def _odloz_dopisanie(win, tid, etykieta):
    """Klik recepty „Cofnij dopisanie” w biegu blokady osi - wpis do kolejki odłożeń okna."""
    win.object_view._recepta_cofniecia_dopisania(tid, etykieta).czlony[0].wykonaj()
    assert str(win._pelny_komunikat) == i18n.t("object.config_undo_add.deferred", telescope=etykieta)


def _wycofany(win, tid):
    """Czy teleskop zszedł z osi nagrobkiem (okno liczy czas zegarem, nie `NOW` testu)."""
    return win.con.execute("SELECT retired_at FROM telescope WHERE id = ?", (tid,)).fetchone()[0] is not None


def test_kolejka_odlozen_wraca_z_powrotem_do_bazy(qapp, tmp_path, monkeypatch):
    """AR-321: recepta osi odłożona w bazie A przeżywa przełączenie A → B → A: na B nie ma jej zdania ani
    recepty (B ma własną, pustą kolejkę), powrót do A podaje zdanie gotowości z receptą od razu po otwarciu,
    a wykonanie recepty działa na osi NOWEGO montażu (teleskop A zdjęty nagrobkiem).
    Falsyfikatory: kolejka w widoku (ginie z demontażem, stan sprzed AR-321); wpis jako domknięcie starego
    widoku (wykonanie na zamkniętym połączeniu)."""
    a, [(tid, etykieta)] = _baza_z_dopisanymi(tmp_path)
    b = str(tmp_path / "b.db")
    db.open_db(b).close()
    win = _okno(a, monkeypatch)
    try:
        win.object_view.set_busy(True)
        _odloz_dopisanie(win, tid, etykieta)
        win.open_path(b)
        assert win.db_path == b
        assert str(win._pelny_komunikat) == i18n.t("main.db_loaded", path=b)
        assert win._recepta_porzadkow_stan is None and not win.object_view.podaj_odlozone()
        win.open_path(a)
        assert str(win._pelny_komunikat) == i18n.t("object.config_undo_add.ready", telescope=etykieta)
        stan = win._recepta_porzadkow_stan
        assert stan is not None
        stan[0].czlony[0].wykonaj()
        assert _wycofany(win, tid)
        assert win._kolejki_osi[queries.klucz_bazy(a)] == []
    finally:
        win.close()


def test_dwa_okna_jednego_procesu_maja_osobne_kolejki(qapp, tmp_path, monkeypatch):
    """AR-321: kolejka jest atrybutem INSTANCJI okna - drugie okno tego procesu na tej samej bazie nie dostaje
    odłożenia pierwszego (nie wykona cudzej recepty). Falsyfikator: magazyn kolejek na klasie okna."""
    a, [(tid, etykieta)] = _baza_z_dopisanymi(tmp_path)
    pierwsze = _okno(a, monkeypatch)
    drugie = _okno(a, monkeypatch)
    try:
        pierwsze.object_view.set_busy(True)
        _odloz_dopisanie(pierwsze, tid, etykieta)
        assert pierwsze._kolejki_osi[queries.klucz_bazy(a)]
        assert drugie._kolejki_osi.get(queries.klucz_bazy(a), []) == []
        assert not drugie.object_view.podaj_odlozone()
        assert str(drugie._pelny_komunikat) != i18n.t("object.config_undo_add.ready", telescope=etykieta)
    finally:
        pierwsze.close()
        drugie.close()


def test_kopia_bazy_to_inna_baza_a_zamkniecie_okna_konczy_kolejke(qapp, tmp_path, monkeypatch):
    """AR-321: tożsamość kolejki = ścieżka bazy (`queries.klucz_bazy`) - kopia pliku pod inną nazwą to inna baza
    (bez cudzego odłożenia); kolejka żyje, dopóki okno jest otwarte - nowe okno na tej samej bazie startuje
    z pustą kolejką („dopóki program jest otwarty”). Falsyfikator: klucz po samej nazwie pliku albo po treści."""
    import shutil
    a, [(tid, etykieta)] = _baza_z_dopisanymi(tmp_path)
    kopia = str(tmp_path / "kopia" / "o.db")
    os.makedirs(os.path.dirname(kopia))
    shutil.copyfile(a, kopia)
    win = _okno(a, monkeypatch)
    try:
        win.object_view.set_busy(True)
        _odloz_dopisanie(win, tid, etykieta)
        win.open_path(kopia)
        assert str(win._pelny_komunikat) == i18n.t("main.db_loaded", path=kopia)
        assert not win.object_view.podaj_odlozone()
    finally:
        win.close()
    nowe = _okno(a, monkeypatch)
    try:
        assert not nowe.object_view.podaj_odlozone()
        assert nowe._recepta_porzadkow_stan is None
    finally:
        nowe.close()


def test_koniec_zapisu_przy_stojacej_recepcie_nie_zmienia_paska(qapp, tmp_path, monkeypatch):
    """AR-321: dwa wpisy w kolejce; koniec etapu podaje pierwszy (recepta stoi), a koniec zapisu Zbiorów
    (`set_writeback_busy(False)`) NIE nadpisuje go drugim - pasek i stan recepty to te same obiekty. Wykonanie
    pierwszej recepty daje jej wynik i gotowość drugiej jedną emisją. Falsyfikator: podanie bez straży
    stojącej recepty (stan sprzed AR-321 - pierwsza recepta znikała na zawsze)."""
    from horreum.gui.app import NAV_PORZADKI
    a, [(t1, e1), (t2, e2)] = _baza_z_dopisanymi(tmp_path, ile=2)
    win = _okno(a, monkeypatch)
    ov = win.object_view
    try:
        win._show_view(NAV_PORZADKI)
        ov.set_busy(True)
        _odloz_dopisanie(win, t1, e1)
        _odloz_dopisanie(win, t2, e2)
        ov.set_busy(False)
        pasek, stan = win._pelny_komunikat, win._recepta_porzadkow_stan
        assert str(pasek) == i18n.t("object.config_undo_add.ready", telescope=e1)
        assert stan is not None and win._czlony_recepty == stan[0].czlony   # recepta na przycisku paska
        ov.set_writeback_busy(True)
        ov.set_writeback_busy(False)
        assert win._pelny_komunikat is pasek and win._recepta_porzadkow_stan is stan
        stan[0].czlony[0].wykonaj()
        assert _wycofany(win, t1) and not _wycofany(win, t2)
        assert i18n.t("object.config_undo_add.ready", telescope=e2) in str(win._pelny_komunikat)
        assert str(win._pelny_komunikat) != i18n.t("object.config_undo_add.ready", telescope=e2)  # z wynikiem
    finally:
        win.close()


def test_recepta_zgaszona_bez_kliku_wraca_tylko_przy_wejsciu_w_porzadki_doklejona(qapp, tmp_path, monkeypatch):
    """AR-321: podana recepta osi, którą zgasił cudzy raport bez kliku, nie ginie - wpis zostaje w kolejce do startu
    swojego gestu i wraca przy wejściu w Porządki, DOKLEJONY do raportu odłożonego tam w międzyczasie (raport, który
    na człowieka czekał, stoi pierwszy). Inne chwile podania już jej nie powtarzają i nie zastępują cudzego raportu:
    start i koniec zapisu Zbiorów, koniec NASTĘPNEGO etapu (wpis drugi czeka na koniec etapu, który go odłożył, a ten
    minął przy stojącej recepcie). Dawniej (ten test przed zmianą) gotowość wracała przy każdej chwili podania i
    zastępowała raport na pasku. Falsyfikatory: wpis usuwany przy podaniu; podanie przy starcie blokady; koniec
    blokady bez numeru biegu (podaje wpis cudzego etapu); wejście w Porządki zastępuje raport zamiast doklejać."""
    from horreum.gui.app import NAV_PORZADKI, NAV_ZBIORY
    a, [(t1, e1), (t2, e2)] = _baza_z_dopisanymi(tmp_path, ile=2)
    win = _okno(a, monkeypatch)
    ov = win.object_view
    try:
        win._show_view(NAV_PORZADKI)
        ov.set_busy(True)
        _odloz_dopisanie(win, t1, e1)
        _odloz_dopisanie(win, t2, e2)
        ov.set_busy(False)
        gotowosc = i18n.t("object.config_undo_add.ready", telescope=e1)
        assert str(win._pelny_komunikat) == gotowosc
        win._flash("cudzy raport")
        ov.set_writeback_busy(True)
        ov.set_writeback_busy(False)
        ov.set_busy(True)
        ov.set_busy(False)
        assert str(win._pelny_komunikat) == "cudzy raport", "chwila podania powtórzyła gotowość nad cudzym raportem"
        win._show_view(NAV_ZBIORY)
        ov.status_message.emit("raport osi")                  # odłożony do Porządków (`_raport_miejsca`)
        win._show_view(NAV_PORZADKI)
        assert str(win._pelny_komunikat) == "raport osi - " + gotowosc
        win._recepta_porzadkow_stan[0].czlony[0].wykonaj()
        assert _wycofany(win, t1) and not _wycofany(win, t2)
        assert str(win._pelny_komunikat).endswith(" - " + i18n.t("object.config_undo_add.ready", telescope=e2))
    finally:
        win.close()


def test_otwarcie_bazy_nie_podaje_drugi_raz_podanego_wpisu(qapp, tmp_path, monkeypatch):
    """AR-321: wpis podany już raz (koniec etapu) nie zastępuje „Baza: … wczytana” przy ponownym otwarciu tej samej
    bazy - otwarcie podaje wyłącznie wpis niepodany (powrót do bazy z odłożeniem sprzed przełączenia,
    `test_kolejka_odlozen_wraca_z_powrotem_do_bazy`); recepta dalej wraca przy wejściu w Porządki.
    Falsyfikator: koniec otwarcia bazy podaje każdy wpis."""
    from horreum.gui.app import NAV_PORZADKI
    a, [(tid, etykieta)] = _baza_z_dopisanymi(tmp_path)
    win = _okno(a, monkeypatch)
    try:
        win._show_view(NAV_PORZADKI)
        win.object_view.set_busy(True)
        _odloz_dopisanie(win, tid, etykieta)
        win.object_view.set_busy(False)
        gotowosc = i18n.t("object.config_undo_add.ready", telescope=etykieta)
        assert str(win._pelny_komunikat) == gotowosc
        win.open_path(a)
        assert str(win._pelny_komunikat) == i18n.t("main.db_loaded", path=a)
        win._show_view(NAV_PORZADKI)
        assert str(win._pelny_komunikat) == gotowosc
    finally:
        win.close()


def _wiersz_osi_teleskopu(win, tid):
    """Oś teleskopu Porządków z zaznaczonym teleskopem `tid` (podstrona otwarta, tabela przeładowana)."""
    win.tasks_view.otworz_os_teleskopu()
    av = win.axis_view
    av.refresh()
    av.table.selectRow(_wiersz(av, tid))
    return av


def test_cofniecie_dopisania_osia_teleskopu_zdejmuje_wpis_kolejki(qapp, tmp_path, monkeypatch):
    """AR-321: wpis „Cofnij dopisanie” odłożony i podany, potem gest zamknięty DROGĄ TRWAŁĄ tego okna - przycisk
    „Cofnij dopisanie” Osi teleskopu: gospodarz zdejmuje od razu wpis z kolejki i podaną już receptę ze swojego stanu
    (wejście w Porządki jej nie przywróci), a wejście w Porządki nie ogłasza „znów możliwe” gestu, którego już nie
    ma. Falsyfikatory: droga trwała bez zdjęcia wpisu przez gospodarza (wpis zostaje w kolejce); zdjęcie wpisu bez
    jego recepty (stan recepty Porządków trzyma martwy gest)."""
    from horreum.gui.app import NAV_PORZADKI, NAV_ZBIORY
    a, [(tid, etykieta)] = _baza_z_dopisanymi(tmp_path)
    win = _okno(a, monkeypatch)
    try:
        win._show_view(NAV_PORZADKI)
        win.object_view.set_busy(True)
        _odloz_dopisanie(win, tid, etykieta)
        win.object_view.set_busy(False)
        gotowosc = i18n.t("object.config_undo_add.ready", telescope=etykieta)
        assert str(win._pelny_komunikat) == gotowosc
        martwa = win._recepta_porzadkow_stan[0]
        av = _wiersz_osi_teleskopu(win, tid)
        assert av.btn_undo_add.isEnabled()
        av.btn_undo_add.click()
        assert _wycofany(win, tid)
        assert win._kolejki_osi[queries.klucz_bazy(a)] == [], "droga trwała zostawiła wpis w kolejce"
        assert win._recepta_porzadkow_stan is None, "stan recepty Porządków trzyma martwy gest"
        assert win._czlony_recepty is not martwa.czlony
        win._show_view(NAV_ZBIORY)
        win._show_view(NAV_PORZADKI)
        assert gotowosc not in str(win._pelny_komunikat)
        assert win._recepta_porzadkow_stan is None and win._czlony_recepty is not martwa.czlony
        assert not win.object_view.podaj_odlozone()
    finally:
        win.close()


def test_martwa_glowa_kolejki_nie_zaslania_wpisu_za_nia(qapp, tmp_path, monkeypatch):
    """AR-321: dwa wpisy „Cofnij dopisanie”; pierwszy cofnięty poza tym oknem (drugie połączenie - jak CLI), więc baza
    nie zostawia mu nic do cofnięcia: koniec etapu zdejmuje go po cichu i podaje DRUGI. Falsyfikatory: gotowość bez
    pytania bazy (martwa głowa „znów możliwe” bez końca, wpis za nią zasłonięty)."""
    a, [(t1, e1), (t2, e2)] = _baza_z_dopisanymi(tmp_path, ile=2)
    win = _okno(a, monkeypatch)
    try:
        win.object_view.set_busy(True)
        _odloz_dopisanie(win, t1, e1)
        _odloz_dopisanie(win, t2, e2)
        con = db.open_db(a)
        try:
            repo.undo_new_telescope(con, telescope_id=t1, now=NOW)
        finally:
            con.close()
        win.object_view.set_busy(False)
        assert str(win._pelny_komunikat) == i18n.t("object.config_undo_add.ready", telescope=e2)
        assert [w.klucz for w in win._kolejki_osi[queries.klucz_bazy(a)]] == [("dopisanie", t2)]
    finally:
        win.close()


def test_martwy_podany_wpis_kart_nie_wraca_przy_wejsciu_w_porzadki(qapp, tmp_path, monkeypatch):
    """AR-321: dwa wpisy (karty, potem dopisanie) odłożone w etapie; koniec etapu podaje pierwszy - jego recepta stoi na
    pasku Porządków. Commit cofnięty poza tym oknem (drugie połączenie - jak `header-fix --undo`): wyjście z Porządków
    i powrót nie przywraca martwej recepty ani jej „znów możliwe”, tylko podaje wpis drugi z jego receptą.
    Falsyfikatory: przywrócenie recepty Porządków bez pytania bazy (straż stojącej recepty trzyma martwy gest i blokuje
    drugi wpis); gospodarz bez zdjęcia recepty martwego wpisu."""
    from horreum.gui.app import NAV_DOM, NAV_PORZADKI, MainWindow
    from test_gui_grid_recepty import _naprawa_prawdziwym_exec, _okno_naprawy_z_kamera
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    win, path, _pliki = _okno_naprawy_z_kamera(tmp_path)
    ov = win.object_view
    try:
        commit = _naprawa_prawdziwym_exec(win)
        karty = win._recepta_porzadkow_stan[0]
        fids = [r[0] for r in win.con.execute("SELECT id FROM frame ORDER BY id")]
        tid, _g = repo.user_assign_config_new_telescope(win.con, frame_ids=fids, name="RC8 0.5x", focal_mm=800.0,
                                                         now=NOW)
        ov.set_busy(True)
        karty.czlony[0].wykonaj()
        ov._recepta_cofniecia_dopisania(tid, "RC8 0.5x").czlony[0].wykonaj()
        ov.set_busy(False)
        assert str(win._pelny_komunikat) == i18n.t("wb.undo_recipe_ready", id=commit)
        martwa = win._recepta_porzadkow_stan[0]
        con = db.open_db(str(path))
        try:
            assert writeback.undo(con, commit, now=NOW).complete
        finally:
            con.close()
        win._show_view(NAV_DOM)
        win._show_view(NAV_PORZADKI)
        assert str(win._pelny_komunikat) == i18n.t("object.config_undo_add.ready", telescope="RC8 0.5x")
        stan = win._recepta_porzadkow_stan
        assert stan is not None and stan[0] is not martwa
        assert win.recipe_label.isVisible()
        assert win.recipe_label.toolTip() == i18n.t("object.config_undo_add", telescope="RC8 0.5x")
    finally:
        win.close()


def test_wpis_cofniecia_kart_bez_czego_cofac_schodzi_po_cichu(qapp, tmp_path, monkeypatch):
    """AR-321: „Cofnij zapis (commit N)” odłożony w biegu etapu; commit cofnięty poza tym oknem (rdzeń
    `writeback.undo` na drugim połączeniu - jak `header-fix --undo`): koniec etapu nie ogłasza „znów możliwe”,
    wpis schodzi z kolejki. Falsyfikator: gotowość kart bez reguły rdzenia „commit ma co cofać”."""
    from horreum.gui.app import MainWindow
    from test_gui_grid_recepty import _naprawa_prawdziwym_exec, _okno_naprawy
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    win, path, _pliki = _okno_naprawy(tmp_path)
    ov = win.object_view
    try:
        commit = _naprawa_prawdziwym_exec(win)
        ov.set_busy(True)
        win._recepta_porzadkow_stan[0].czlony[0].wykonaj()
        assert str(win._pelny_komunikat) == i18n.t("wb.undo_recipe_busy", id=commit)
        con = db.open_db(str(path))
        try:
            assert writeback.undo(con, commit, now=NOW).complete
        finally:
            con.close()
        ov.set_busy(False)
        assert str(win._pelny_komunikat) != i18n.t("wb.undo_recipe_ready", id=commit)
        assert win._kolejki_osi[queries.klucz_bazy(str(path))] == []
    finally:
        win.close()


# ------------------------------------------------------------ AR-348: aktywacja okna jako chwila podania, koniec blokady

def _pokazane(sciezka, monkeypatch):
    """`_okno` pokazane i aktywne - aktywacja (`MainWindow.changeEvent`) potrzebuje okna na ekranie (offscreen)."""
    from test_gui_pasek_szczegol import _czekaj
    win = _okno(sciezka, monkeypatch)
    win.resize(1400, 900)
    win.show()
    win.activateWindow()
    _czekaj(lambda: QApplication.activeWindow() is win, "okno aktywne")
    return win


def _cofnij_dopisanie_obok(sciezka, tid):
    """„Cofnij dopisanie” drugim połączeniem - jak drugie okno albo CLI: w tym oknie nie pada żadne zdarzenie."""
    con = db.open_db(sciezka)
    try:
        repo.undo_new_telescope(con, telescope_id=tid, now=NOW)
    finally:
        con.close()


@pytest.mark.parametrize("droga", ["drugie_okno", "modal"])
def test_aktywacja_okna_zdejmuje_martwa_recepte_dopisania_z_paska_porzadkow(qapp, tmp_path, monkeypatch, droga):
    """AR-348: recepta „Cofnij dopisanie” podana w Porządkach, gest zamknięty poza oknem drugim połączeniem - przed
    powrotem z innego okna (`drugie_okno`) albo pod oknem modalnym tego okna (`modal`: prawdziwe `exec()`, zamknięte
    `reject`). Bez zdarzenia w oknie recepta stoi; powrót do okna (aktywacja) zdejmuje ją z paska i ze stanu, a wpis
    z kolejki. Obie drogi kończą się tą samą linią produktu (jedno `changeEvent`, bez gałęzi modala), więc falsyfikator
    jest jeden: okno bez obsługi aktywacji (martwa recepta do najbliższej chwili podania)."""
    from PySide6.QtCore import QTimer
    from horreum.gui.app import NAV_PORZADKI
    from test_gui_grid_szuflada import _aktywuj
    from test_gui_pasek_szczegol import _czekaj
    a, [(tid, etykieta)] = _baza_z_dopisanymi(tmp_path)
    win = _pokazane(a, monkeypatch)
    ov = win.object_view
    try:
        win._show_view(NAV_PORZADKI)
        ov.set_busy(True)
        _odloz_dopisanie(win, tid, etykieta)
        ov.set_busy(False)
        assert str(win._pelny_komunikat) == i18n.t("object.config_undo_add.ready", telescope=etykieta)
        assert win._recepta_porzadkow_stan is not None and win.recipe_label.isVisible()
        if droga == "drugie_okno":
            _cofnij_dopisanie_obok(a, tid)
        else:
            okno = QDialog(win)
            okno.setModal(True)

            def _w_modalu():
                _cofnij_dopisanie_obok(a, tid)
                okno.reject()
            bezpiecznik = QTimer()
            bezpiecznik.setSingleShot(True)
            bezpiecznik.timeout.connect(okno.reject)            # okno zamyka się samo, gdyby krok nie przeszedł
            bezpiecznik.start(10000)
            QTimer.singleShot(50, _w_modalu)
            try:
                okno.exec()
            finally:
                bezpiecznik.stop()
            # Offscreen nie ma menedżera okien, który po zamknięciu modala oddaje aktywację rodzicowi (platforma
            # natywna robi to sama) - test oddaje ją niżej jawnie: przejście aktywacji okno modalne → okno główne.
            assert QApplication.activeWindow() is not win
        assert win._recepta_porzadkow_stan is not None        # bez zdarzenia w oknie stoi
        if droga == "drugie_okno":
            _aktywuj(win)
        else:
            win.activateWindow()
            _czekaj(lambda: QApplication.activeWindow() is win, "okno aktywne po modalu")
        assert win._recepta_porzadkow_stan is None
        assert not win.recipe_label.isVisible()
        assert win._kolejki_osi[queries.klucz_bazy(a)] == []
    finally:
        win.close()


def test_sama_dezaktywacja_okna_zostawia_martwa_recepte(qapp, tmp_path, monkeypatch):
    """AR-348: odejście do innego okna bez powrotu nie jest chwilą podania - recepta „Cofnij dopisanie”, której gest
    zamknięto poza oknem, stoi na pasku i w stanie, a martwy wpis w kolejce, dopóki okno nie wróci do aktywnych (pasek
    czyta się po powrocie; czyszczenie przy odejściu dokładałoby drugi odczyt bazy na każde odejście i powrót).
    Falsyfikator: `changeEvent` bez `isActiveWindow()` (czyszczenie także przy dezaktywacji)."""
    from PySide6.QtWidgets import QWidget
    from horreum.gui.app import NAV_PORZADKI
    from test_gui_pasek_szczegol import _czekaj
    a, [(tid, etykieta)] = _baza_z_dopisanymi(tmp_path)
    win = _pokazane(a, monkeypatch)
    ov = win.object_view
    inne = QWidget()
    try:
        win._show_view(NAV_PORZADKI)
        ov.set_busy(True)
        _odloz_dopisanie(win, tid, etykieta)
        ov.set_busy(False)
        assert win._recepta_porzadkow_stan is not None
        _cofnij_dopisanie_obok(a, tid)
        inne.resize(200, 100)
        inne.show()
        inne.activateWindow()
        _czekaj(lambda: QApplication.activeWindow() is inne, "drugie okno aktywne")
        assert win._recepta_porzadkow_stan is not None and win.recipe_label.isVisible()
        [wpis] = win._kolejki_osi[queries.klucz_bazy(a)]
        assert not ov._zywy(wpis)                       # wpis martwy w bazie - stoi wyłącznie z braku powrotu
    finally:
        inne.close()
        win.close()


def test_aktywacja_okna_zdejmuje_martwe_zdanie_cofniecia_kart_poza_porzadkami(qapp, tmp_path, monkeypatch):
    """AR-348: gotowość „Cofnij zapis (commit N)” ma szczegół (polecenie CLI) i nie ma miejsca, więc stoi na pasku
    KAŻDEJ strony; commit cofnięty poza oknem (rdzeń na drugim połączeniu - jak `header-fix --undo`) przy Domu na
    ekranie: powrót do okna zdejmuje martwe zdanie i stan recepty. Falsyfikatory: brak obsługi aktywacji; czyszczenie
    z `WindowActivate` Porządków (dociera tylko do widocznych dzieci - na Domu Porządków nie widać)."""
    from horreum.gui.app import NAV_DOM, MainWindow
    from test_gui_grid_recepty import _naprawa_prawdziwym_exec, _okno_naprawy
    from test_gui_grid_szuflada import _aktywuj
    from test_gui_pasek_szczegol import _czekaj
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    win, path, _pliki = _okno_naprawy(tmp_path)
    ov = win.object_view
    try:
        commit = _naprawa_prawdziwym_exec(win)
        ov.set_busy(True)
        win._recepta_porzadkow_stan[0].czlony[0].wykonaj()
        ov.set_busy(False)
        gotowosc = i18n.t("wb.undo_recipe_ready", id=commit)
        assert str(win._pelny_komunikat) == gotowosc
        win._show_view(NAV_DOM)
        win.activateWindow()
        _czekaj(lambda: QApplication.activeWindow() is win, "okno aktywne")
        assert str(win._pelny_komunikat) == gotowosc           # zdanie bez miejsca stoi na Domu
        con = db.open_db(str(path))
        try:
            assert writeback.undo(con, commit, now=NOW).complete
        finally:
            con.close()
        _aktywuj(win)
        assert gotowosc not in str(win._pelny_komunikat)
        assert win._recepta_porzadkow_stan is None
        assert win._kolejki_osi[queries.klucz_bazy(str(path))] == []
    finally:
        win.close()


def test_koniec_zapisu_podaje_wpis_za_martwa_recepta_podana_przy_wejsciu(qapp, tmp_path, monkeypatch):
    """AR-348 (droga końca blokady): A „dopisanie” odłożony w etapie, podany i zgaszony cudzym raportem; zapis Zbiorów
    w biegu (prawdziwy uchwyt `grid._wb`); B „karty” odłożony w tym zapisie; wejście w Porządki podaje ponownie A; A
    cofnięty poza oknem; koniec zapisu - pasek mówi gotowość B, a stan recepty to recepta B. Falsyfikator: czyszczenie
    martwych wpisów PO straży stojącej recepty (straż widzi żywą receptę A i nic nie podaje)."""
    from horreum.gui.app import NAV_DOM, NAV_PORZADKI, MainWindow
    from test_gui_grid_recepty import _naprawa_prawdziwym_exec, _okno_naprawy_z_kamera
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    win, path, _pliki = _okno_naprawy_z_kamera(tmp_path)
    ov = win.object_view
    etykieta = "RC8 0.5x"
    try:
        commit = _naprawa_prawdziwym_exec(win)
        karty = win._recepta_porzadkow_stan[0]
        fids = [r[0] for r in win.con.execute("SELECT id FROM frame ORDER BY id")]
        tid, _g = repo.user_assign_config_new_telescope(win.con, frame_ids=fids, name=etykieta, focal_mm=800.0,
                                                         now=NOW)
        ov.set_busy(True)
        ov._recepta_cofniecia_dopisania(tid, etykieta).czlony[0].wykonaj()
        ov.set_busy(False)
        assert str(win._pelny_komunikat) == i18n.t("object.config_undo_add.ready", telescope=etykieta)
        win._flash("cudzy raport")
        grid = win.grid_view
        grid._wb.busy_changed.emit(True)
        karty.czlony[0].wykonaj()
        assert str(win._pelny_komunikat) == i18n.t("wb.undo_recipe_foreign", id=commit)
        win._show_view(NAV_DOM)
        win._show_view(NAV_PORZADKI)
        assert i18n.t("object.config_undo_add.ready", telescope=etykieta) in str(win._pelny_komunikat)
        _cofnij_dopisanie_obok(str(path), tid)
        grid._wb.busy_changed.emit(False)
        assert str(win._pelny_komunikat) == i18n.t("wb.undo_recipe_ready", id=commit)
        stan = win._recepta_porzadkow_stan
        assert stan is not None and stan[0].czlony[0].tekst == i18n.t("wb.undo_recipe", id=commit)
    finally:
        win.close()


# ------------------------------------------------------------ AR-336: tożsamość zamiaru we wpisie kolejki

NOW_INNY = "2026-10-12T10:00:00.123456+00:00"


def _baza_z_dopisaniem_w(katalog, now):
    """`_baza_z_dopisanymi` w katalogu `katalog` z zegarem gestu `now` - druga biblioteka z gestem tego samego numeru
    teleskopu i tymi samymi numerami zdarzeń (ten sam skrypt), różna wyłącznie chwilą gestu."""
    con, obce, rc8 = _baza(katalog)
    tid, _g = repo.user_assign_config_new_telescope(con, frame_ids=[obce[0]], name="RC8 0.5x", focal_mm=800.0,
                                                     in_park=1, source_telescope_id=rc8, now=now)
    con.close()
    return str(katalog / "o.db"), tid


def _bez_wal(sciezka):
    for koncowka in ("-wal", "-shm"):
        assert not os.path.exists(sciezka + koncowka), sciezka + koncowka


def test_podmiana_pliku_bazy_inna_biblioteka_nie_podaje_cudzego_commitu(qapp, tmp_path, monkeypatch):
    """AR-336: „Cofnij zapis (commit N)” odłożony w bibliotece A pod ścieżką P; okno przechodzi do B, a pod P trafia
    inna biblioteka C z ŻYWYM commitem kart o tym samym numerze - powrót do P nie ogłasza gotowości (klik cofnąłby
    commit C - zapis do jej plików), wpis schodzi z kolejki. Klucz kolejki zostaje ścieżką. Falsyfikator: `_zywy` bez
    tożsamości zamiaru (`commits.run_id`)."""
    import shutil
    from horreum.gui.app import MainWindow
    from test_gui_grid_recepty import _naprawa_prawdziwym_exec, _okno_naprawy
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    (tmp_path / "a").mkdir()
    (tmp_path / "c").mkdir()
    win_c, path_c, _pliki_c = _okno_naprawy(tmp_path / "c")
    try:
        commit_c = _naprawa_prawdziwym_exec(win_c)
    finally:
        win_c.close()
    win, path, _pliki = _okno_naprawy(tmp_path / "a")
    ov = win.object_view
    try:
        commit = _naprawa_prawdziwym_exec(win)
        assert commit == commit_c
        ov.set_busy(True)
        win._recepta_porzadkow_stan[0].czlony[0].wykonaj()
        assert str(win._pelny_komunikat) == i18n.t("wb.undo_recipe_busy", id=commit)
        b = str(tmp_path / "b.db")
        db.open_db(b).close()
        win.open_path(b)
        _bez_wal(str(path))
        _bez_wal(str(path_c))         # commit C cały w pliku głównym - kopia niesie go, a nie stan sprzed niego
        shutil.copyfile(path_c, path)
        win.open_path(str(path))
        assert str(win._pelny_komunikat) == i18n.t("main.db_loaded", path=str(path))
        assert win._kolejki_osi[queries.klucz_bazy(str(path))] == []
    finally:
        win.close()


def test_podmiana_pliku_bazy_nie_podaje_cudzego_dopisania(qapp, tmp_path, monkeypatch):
    """AR-336: „Cofnij dopisanie” odłożony w A; pod tę ścieżkę trafia C z OTWARTYM gestem tego samego numeru teleskopu
    i tymi samymi numerami zdarzeń, ale z inną chwilą gestu - powrót nie ogłasza gotowości, wpis schodzi. Falsyfikator:
    tożsamość wyłącznie dla kart (dopisanie po samym numerze teleskopu)."""
    import shutil
    (tmp_path / "a").mkdir()
    (tmp_path / "c").mkdir()
    a, [(tid, etykieta)] = _baza_z_dopisanymi(tmp_path / "a")
    c, tid_c = _baza_z_dopisaniem_w(tmp_path / "c", NOW_INNY)
    assert tid_c == tid
    b = str(tmp_path / "b.db")
    db.open_db(b).close()
    win = _okno(a, monkeypatch)
    try:
        win.object_view.set_busy(True)
        _odloz_dopisanie(win, tid, etykieta)
        win.open_path(b)
        _bez_wal(a)
        _bez_wal(c)                   # gest C cały w pliku głównym - kopia niesie go, a nie stan sprzed niego
        shutil.copyfile(c, a)
        win.open_path(a)
        assert str(win._pelny_komunikat) == i18n.t("main.db_loaded", path=a)
        assert win._kolejki_osi[queries.klucz_bazy(a)] == []
    finally:
        win.close()


def test_przywrocona_kopia_tej_samej_biblioteki_podaje_wpis(qapp, tmp_path, monkeypatch):
    """AR-336 (granica w drugą stronę): kopia TEJ SAMEJ biblioteki wraca pod ścieżkę - zamiar ten sam, więc gotowość
    „Cofnij dopisanie” pada po otwarciu jak dotąd. Falsyfikator: tożsamość, która żadnej bazy nie uznaje za tę samą."""
    import shutil
    import sqlite3
    a, [(tid, etykieta)] = _baza_z_dopisanymi(tmp_path)
    kopia = str(tmp_path / "kopia.db")
    b = str(tmp_path / "b.db")
    db.open_db(b).close()
    win = _okno(a, monkeypatch)
    try:
        win.object_view.set_busy(True)
        _odloz_dopisanie(win, tid, etykieta)
        zrodlo, cel = sqlite3.connect(a), sqlite3.connect(kopia)
        try:
            zrodlo.backup(cel)
        finally:
            zrodlo.close()
            cel.close()
        win.open_path(b)
        _bez_wal(a)
        shutil.copyfile(kopia, a)
        win.open_path(a)
        assert str(win._pelny_komunikat) == i18n.t("object.config_undo_add.ready", telescope=etykieta)
    finally:
        win.close()
