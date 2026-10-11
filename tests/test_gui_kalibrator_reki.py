"""Gest ręki na osi KALIBRACJI panelu „Rodowód" (E4-5) i ergonomia tej osi (wizytacja 0802) - testy
STERUJĄCE realnym oknem Qt (offscreen): klik w wiersz listy, klik w przycisk, wybór w oknie
kandydatów. Rdzeń (klinga, rekoncyliacja, kandydaci) ma własne testy w `test_lineage.py`; tu
sprawdzamy, czy powierzchnia prowadzi do nich człowieka i mówi prawdę o wyniku."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QThread, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from horreum import db, repo
from horreum.calibration import run_calibration
from horreum.lineage import run_lineage

NOW = "2026-10-11T12:00:00+00:00"
LIGHT, MF_HA, MF_OIII, DUBEL = 1, 3, 5, 7


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def kcon(tmp_path):
    """Light Ha z kompletnym przepisem flatu, masterflat Ha (z przepisu) i masterflat OIII tej samej
    kamery (spoza przepisu), oś przepisu policzona, rodowód NIE - flat lightu jest „nieliczony"."""
    con = db.open_db(str(tmp_path / "k.db"))
    con.execute("INSERT INTO camera(id, model_canon, pixel_um, is_mono, created_at) "
                "VALUES (1, 'ASI2600MM', 3.76, 1, ?)", (NOW,))
    con.execute("INSERT INTO telescope(id, telescop_canon, status, created_at) "
                "VALUES (1, 'A140R', 'proposed', ?)", (NOW,))
    con.execute("INSERT INTO config(id, telescope_id, camera_id, label, status, created_at) "
                "VALUES (1, 1, 1, 'A140R x ASI2600MM', 'proposed', ?)", (NOW,))
    for fid, kind, filtr, data, sciezka in (
            (LIGHT, "light", "Ha", "2024-06-01T22:00:00", r"R:\ASTRO_\LIGHTS\M31\M31_Ha_0001.fits"),
            (MF_HA, "master_flat", "Ha", "2024-05-30T20:00:00",
             r"R:\ASTRO_\CALIBRATION\masters\flats\MF_Ha.xisf"),
            (MF_OIII, "master_flat", "OIII", "2024-05-01T20:00:00",
             r"R:\ASTRO_\CALIBRATION\masters\flats\MF_OIII.xisf")):
        con.execute("INSERT INTO frame(id, sha1_data, kind, filetype, camera_id, config_id, "
                    "filter_canon, first_seen_at) VALUES (?, ?, ?, 'xisf', 1, 1, ?, ?)",
                    (fid, f"s{fid}", kind, filtr, NOW))
        con.execute("INSERT INTO header(frame_id, raw_json, date_obs, xbinning) "
                    "VALUES (?, '{}', ?, 1)", (fid, data))
        con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (fid, sciezka))
    con.commit()
    run_calibration(con, now=NOW)
    yield con
    con.close()


@pytest.fixture
def view(qapp, kcon):
    from horreum.gui.grid import FramesView
    v = FramesView(kcon, now_fn=lambda: NOW)
    v._writeback_async = False
    v.resize(1400, 900)
    v.show()
    qapp.processEvents()
    yield v
    if not any(t.isRunning() for t in v.findChildren(QThread)):
        v.close()
        v.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _otworz_panel_lightu(view):
    view.refresh()
    for i, r in enumerate(view.model._rows):
        if isinstance(r, dict) and r.get("frame_id") == LIGHT:
            view.table.selectRow(i)
            break
    else:
        raise AssertionError("light nie stoi w gridzie")
    if not view._lineage_panel_open():
        view._toggle_panel("lineage")
    else:
        view._refresh_lineage()
    QApplication.processEvents()
    return view.lineage_bar


def _klik_wiersz(bar, relation):
    """Klik MYSZĄ w wiersz relacji na liście panelu (nie `setSelected`)."""
    i = [r["relation"] for r in bar._relacje].index(relation)
    item = bar.items.item(i)
    bar.items.scrollToItem(item)
    QTest.mouseClick(bar.items.viewport(), Qt.LeftButton, Qt.NoModifier,
                     bar.items.visualItemRect(item).center())
    QApplication.processEvents()
    assert bar.items.selectedItems() == [item], "klik nie zaznaczył wiersza"


def _wybierz_w_oknie(fragment, zebrane):
    """Steruje modalnym oknem kandydatów: zapamiętuje jego wiersze i wybiera ten z `fragment`.
    Zapasowy timer zamyka okno, gdyby wybór nie trafił - test ma paść, nie zawisnąć."""
    def _wybierz():
        dlg = QApplication.activeModalWidget()
        if dlg is None or dlg.objectName() != "calibrator_picker":
            return
        wiersze = [dlg.lista.item(i).text() for i in range(dlg.lista.count())]
        zebrane.extend(wiersze)
        trafione = [i for i, t in enumerate(wiersze) if fragment in t]
        if trafione:
            dlg.lista.setCurrentRow(trafione[0])
            dlg.accept()

    def _awaryjnie():
        dlg = QApplication.activeModalWidget()
        if dlg is not None:
            dlg.reject()
    QTimer.singleShot(0, _wybierz)
    QTimer.singleShot(3000, _awaryjnie)


def _ogniwo(con):
    r = con.execute("SELECT master_frame_id, asserted_by, confidence FROM calibration "
                    "WHERE light_frame_id = ? AND relation = 'flat'", (LIGHT,)).fetchone()
    return None if r is None else tuple(r)


def test_wskaz_kalibrator_klikiem_zapisuje_reke_spoza_przepisu(view, kcon):
    """E4-5 przez prawdziwy gest: klik w wiersz pola → „Wskaż kalibrator…” → wybór mastera OIII
    (spoza przepisu lightu Ha) w oknie listy → zapis `user`/`user`, panel mówi „Twoja decyzja ·
    spoza przepisu”, pasek mówi, że przeliczenia wyboru nie zmienią."""
    run_lineage(kcon, now=NOW)
    assert _ogniwo(kcon) == (MF_HA, "horreum", "recipe")
    komunikaty = []
    view.status_message.connect(komunikaty.append)
    bar = _otworz_panel_lightu(view)
    assert not bar._cal_row.isHidden()
    assert not bar.btn_cal_pick.isEnabled(), "bez zaznaczonego wiersza gest nie ma celu"
    assert "Zaznacz na liście" in bar.btn_cal_pick.toolTip()
    assert bar.btn_cal_restore.isHidden(), "nie ma Twojej decyzji - nie ma czego przywracać"

    _klik_wiersz(bar, "flat")
    assert bar.btn_cal_pick.isEnabled()
    wiersze = []
    _wybierz_w_oknie(f"(#{MF_OIII})", wiersze)
    QTest.mouseClick(bar.btn_cal_pick, Qt.LeftButton)
    QApplication.processEvents()

    # Okno: najpierw z przepisu (z oznaczeniem obecnego), potem SPOZA PRZEPISU - w każdym wierszu.
    assert wiersze[0].startswith("[z przepisu]") and f"(#{MF_HA})" in wiersze[0]
    assert wiersze[0].endswith("obecny")
    assert wiersze[1].startswith("[SPOZA PRZEPISU · filtr OIII ≠ Ha]") and "MF_OIII.xisf" in wiersze[1]
    assert _ogniwo(kcon) == (MF_OIII, "user", "user")
    assert kcon.execute("SELECT actor FROM event WHERE verb = 'calibration.linked' "
                        "ORDER BY id DESC LIMIT 1").fetchone()[0] == "user:local"
    teksty = [bar.items.item(i).text() for i in range(bar.items.count())]
    assert any("Twoja decyzja · spoza przepisu" in t for t in teksty), teksty
    assert "Zapisano Twój kalibrator" in komunikaty[-1]
    assert not bar.btn_cal_restore.isHidden(), "droga powrotu ma się pokazać"

    s = run_lineage(kcon, now=NOW)                        # przebieg nie rusza wyboru ręki
    assert _ogniwo(kcon) == (MF_OIII, "user", "user") and not s.linked_new


def test_przywroc_automat_klikiem_zdejmuje_reke_i_liczy_rodowod(view, kcon):
    """„Przywróć automat”: wiersz ręki znika (klinga z CAS na masterze z ekranu), a etap Rodowód
    rusza od razu z nazwą `lineage` - bez wycieczki do Dostawy. Klatka wraca do zaznaczenia przy
    przeładowaniu zbioru po przebiegu (`_cel_gestu`)."""
    run_lineage(kcon, now=NOW)
    repo.link_calibration(kcon, light_frame_id=LIGHT, master_frame_id=MF_OIII, relation="flat",
                          now=NOW, actor="user:local", asserted_by="user", confidence="user",
                          expected=(MF_HA, "horreum"))
    wolane, komunikaty = [], []
    view.run_stage_fn = lambda etap: wolane.append(etap) or None
    view.status_message.connect(komunikaty.append)
    bar = _otworz_panel_lightu(view)
    _klik_wiersz(bar, "flat")
    assert bar.btn_cal_restore.isEnabled()

    QTest.mouseClick(bar.btn_cal_restore, Qt.LeftButton)
    QApplication.processEvents()
    assert _ogniwo(kcon) is None
    assert wolane == ["lineage"]
    assert "Zdjęto Twój wybór" in komunikaty[-1] and "liczę" in komunikaty[-1]
    assert view._cel_gestu == [LIGHT]
    # Do końca etapu panel mówi prawdę: master z przepisu jest, powiązania nie policzono.
    assert "pole (flat): nie policzono" in bar.head.text()

    run_lineage(kcon, now=NOW)                            # to, co zrobi etap w tle
    view.refresh_lineage_panel()
    assert _ogniwo(kcon) == (MF_HA, "horreum", "recipe")
    assert "pole (flat): jest" in bar.head.text()


def test_policz_teraz_przy_ostrzezeniu_jednym_kliknieciem(view, kcon):
    """Stan nieliczony to ⚠ (nie wygaszenie) z przyciskiem „Policz teraz” obok - jedno
    kliknięcie zamiast czterech. Odmowa etapu mówi, dlaczego nie policzono."""
    wolane, komunikaty = [], []
    view.run_stage_fn = lambda etap: wolane.append(etap) or None
    view.status_message.connect(komunikaty.append)
    bar = _otworz_panel_lightu(view)

    assert "⚠" in bar.warn.full_text() and not bar.btn_cal_count.isHidden()
    from horreum.gui.grid_model import _COLORS
    relacje = [r["relation"] for r in bar._relacje]
    flat, dark = (bar.items.item(relacje.index(r)) for r in ("flat", "dark"))
    assert flat.text().startswith("pole (flat) · ⚠"), flat.text()
    assert dark.foreground().color() == _COLORS["secondary_text"], "luka (bez nastawy) wygaszona"
    assert flat.foreground().color() != _COLORS["secondary_text"], "nieliczone wygląda jak luka"
    # Nazwa klatki i stan każdej klasy w nagłówku.
    assert bar.head.text().startswith("M31_Ha_0001.fits - ")
    assert "pole (flat): nie policzono" in bar.head.text()

    QTest.mouseClick(bar.btn_cal_count, Qt.LeftButton)
    assert wolane == ["lineage"] and "liczę rodowód kalibracji" in komunikaty[-1]

    view.run_stage_fn = lambda _etap: "etap już biegnie"
    QTest.mouseClick(bar.btn_cal_count, Qt.LeftButton)
    assert "NIE policzono" in komunikaty[-1] and "biegnie" in komunikaty[-1]

    run_lineage(kcon, now=NOW)
    view.refresh_lineage_panel()
    assert bar.btn_cal_count.isHidden() and bar.warn.full_text() == ""


def test_gest_odmowiony_przy_dryfie_pokazuje_stan_biezacy(view, kcon):
    """Panel pokazał automat, a w międzyczasie ktoś zapisał inny wybór - klinga odmawia (`drift`),
    zapis się nie odbywa, pasek mówi dlaczego, a panel pokazuje stan z bazy."""
    run_lineage(kcon, now=NOW)
    komunikaty = []
    view.status_message.connect(komunikaty.append)
    bar = _otworz_panel_lightu(view)
    _klik_wiersz(bar, "flat")
    repo.link_calibration(kcon, light_frame_id=LIGHT, master_frame_id=MF_OIII, relation="flat",
                          now=NOW, actor="user:other", asserted_by="user", confidence="user",
                          expected=(MF_HA, "horreum"))

    _wybierz_w_oknie(f"(#{MF_HA})", [])
    QTest.mouseClick(bar.btn_cal_pick, Qt.LeftButton)
    QApplication.processEvents()
    assert _ogniwo(kcon) == (MF_OIII, "user", "user")
    assert "zmienił się w międzyczasie" in komunikaty[-1]
    assert any("Twoja decyzja" in bar.items.item(i).text() for i in range(bar.items.count()))


def test_gesty_kalibracji_milkna_na_czas_etapu_i_znikaja_poza_osia(view, kcon):
    """Etap w tle pisze do `calibration` - gesty tej osi gasną razem z resztą panelu (`set_busy`).
    Wyjście z osi (klatka kalibracyjna, oś stosów) chowa wiersz gestów - „Wskaż kalibrator…” nie
    wisi nad czymś, czego nie dotyczy."""
    run_lineage(kcon, now=NOW)
    bar = _otworz_panel_lightu(view)
    _klik_wiersz(bar, "flat")
    view.set_busy(True)
    assert not bar.btn_cal_pick.isEnabled() and not bar.btn_cal_count.isEnabled()
    view.set_busy(False)
    assert bar.btn_cal_pick.isEnabled()

    for i, r in enumerate(view.model._rows):
        if isinstance(r, dict) and r.get("frame_id") == MF_HA:
            view.table.selectRow(i)
    view._refresh_lineage()
    assert bar._cal_row.isHidden() and bar._light_id is None
    assert "klatka kalibracyjna" in bar.head.text()


def test_okno_kalibratora_dwuklik_zatwierdza_i_nazywa_niezgodnosc(view, kcon):
    """Wizytacja fali 4: flat OIII stał na liście dla lightu Ha bez wyróżnienia, a po wyborze panel
    mówił zwykłe „jest”. Teraz wiersz kandydata nazywa różnicę, DWUKLIK wiersza zatwierdza wybór,
    przyciski mówią po polsku, a panel po wyborze ostrzega o innej nastawie."""
    run_lineage(kcon, now=NOW)
    bar = _otworz_panel_lightu(view)
    _klik_wiersz(bar, "flat")
    widziane = {}

    def _dwuklik():
        dlg = QApplication.activeModalWidget()
        if dlg is None or dlg.objectName() != "calibrator_picker" or not dlg.isVisible():
            QTimer.singleShot(20, _dwuklik)                # okno jeszcze nie stoi - spróbuj za chwilę
            return
        QApplication.processEvents()                       # układ listy przed liczeniem kadru
        widziane["przyciski"] = sorted(b.text() for b in dlg.findChildren(QPushButton))
        widziane["min_h"] = dlg.minimumHeight()
        wiersz = next(i for i in range(dlg.lista.count())
                      if f"(#{MF_OIII})" in dlg.lista.item(i).text())
        item = dlg.lista.item(wiersz)
        widziane["tekst"] = item.text()
        dlg.lista.scrollToItem(item)
        punkt = dlg.lista.visualItemRect(item).center()
        # Dwuklik w Qt 6 = pierwszy klik + `mouseDClick` (drugi klik z DblClick) - sam `mouseDClick`
        # nie wyzwala `itemDoubleClicked` (sonda `s4_dwuklik.py`).
        QTest.mouseClick(dlg.lista.viewport(), Qt.LeftButton, Qt.NoModifier, punkt)
        QTest.mouseDClick(dlg.lista.viewport(), Qt.LeftButton, Qt.NoModifier, punkt)

    def _awaryjnie():
        dlg = QApplication.activeModalWidget()
        if dlg is not None:
            dlg.reject()
    QTimer.singleShot(0, _dwuklik)
    QTimer.singleShot(3000, _awaryjnie)
    QTest.mouseClick(bar.btn_cal_pick, Qt.LeftButton)
    QApplication.processEvents()

    assert widziane["przyciski"] == ["Anuluj", "Wskaż"]
    assert widziane["min_h"] >= 400
    assert widziane["tekst"].startswith("[SPOZA PRZEPISU · filtr OIII ≠ Ha]")
    assert _ogniwo(kcon) == (MF_OIII, "user", "user"), "dwuklik nie zatwierdził wyboru"
    flat = bar.items.item([r["relation"] for r in bar._relacje].index("flat")).text()
    assert "⚠ inna nastawa: filtr OIII ≠ Ha" in flat, flat
    assert "pole (flat): jest (inna nastawa)" in bar.head.text()


def _wycofaj(con, fid):
    con.execute("UPDATE frame SET retired_at = ? WHERE id = ?", (NOW, fid))
    con.commit()


def test_reka_na_nieaktywnym_masterze_ostrzega_i_sama_sie_zaznacza(view, kcon):
    """Wskazanie ręki na masterze wycofanym: nagłówek „jest (nieaktywny)”, wiersz z ⚠ „wskaż inny”,
    a wiersz WYMAGAJĄCY ręki jest zaznaczony od wejścia - „Wskaż kalibrator…” działa bez kliku
    w listę. Po geście zaznaczenie wraca na tę samą relację (następny gest o klik bliżej)."""
    run_lineage(kcon, now=NOW)
    repo.link_calibration(kcon, light_frame_id=LIGHT, master_frame_id=MF_OIII, relation="flat",
                          now=NOW, actor="user:local", asserted_by="user", confidence="user",
                          expected=(MF_HA, "horreum"))
    _wycofaj(kcon, MF_OIII)
    bar = _otworz_panel_lightu(view)
    assert "pole (flat): jest (nieaktywny)" in bar.head.text()
    flat = [r["relation"] for r in bar._relacje].index("flat")
    assert "⚠ master wycofany" in bar.items.item(flat).text()
    assert bar.items.selectedItems() == [bar.items.item(flat)], "wiersz do ręki nie zaznaczony"
    assert bar.btn_cal_pick.isEnabled()

    _wybierz_w_oknie(f"(#{MF_HA})", [])
    QTest.mouseClick(bar.btn_cal_pick, Qt.LeftButton)
    QApplication.processEvents()
    assert _ogniwo(kcon) == (MF_HA, "user", "user")
    assert bar.items.selectedItems() == [bar.items.item(flat)], "zaznaczenie nie wróciło po geście"
    assert bar.btn_cal_restore.isEnabled()


def test_przywroc_automat_bez_kandydata_z_przepisu_mowi_ze_zostanie_bez_kalibratora(view, kcon):
    """Przepis nie ma aktywnego kandydata (master z przepisu wycofany): podpowiedź „Przywróć automat”
    mówi o skutku PRZED kliknięciem, a po nim zdanie mówi, że klatka została bez kalibratora - bez
    uruchamiania etapu, który niczego by nie odtworzył."""
    run_lineage(kcon, now=NOW)
    repo.link_calibration(kcon, light_frame_id=LIGHT, master_frame_id=MF_OIII, relation="flat",
                          now=NOW, actor="user:local", asserted_by="user", confidence="user",
                          expected=(MF_HA, "horreum"))
    _wycofaj(kcon, MF_HA)
    wolane, komunikaty = [], []
    view.run_stage_fn = lambda etap: wolane.append(etap) or None
    view.status_message.connect(komunikaty.append)
    bar = _otworz_panel_lightu(view)
    _klik_wiersz(bar, "flat")
    assert "zostanie bez kalibratora" in bar.btn_cal_restore.toolTip()

    QTest.mouseClick(bar.btn_cal_restore, Qt.LeftButton)
    QApplication.processEvents()
    assert _ogniwo(kcon) is None and wolane == []
    assert "klatka została bez kalibratora" in komunikaty[-1]


def test_gesty_gasna_przy_zapisie_plikow_i_mowia_dlaczego(view, kcon, monkeypatch):
    """Zapis do plików (ta powierzchnia albo okno naprawy) trzyma blokadę bazy jak etap w tle -
    gesty gasną z podpowiedzią o przyczynie. Blokada, która mimo to przyjdzie (`OperationalError`),
    kończy się zdaniem, nie wyjątkiem, i bez zapisu."""
    run_lineage(kcon, now=NOW)
    komunikaty = []
    view.status_message.connect(komunikaty.append)
    bar = _otworz_panel_lightu(view)
    _klik_wiersz(bar, "flat")
    view.set_writeback_busy(True)
    assert not bar.btn_cal_pick.isEnabled()
    assert "zapis do plików" in bar.btn_cal_pick.toolTip()
    view.set_writeback_busy(False)
    assert bar.btn_cal_pick.isEnabled()
    view._on_wlasny_zapis_plikow(True)
    assert not bar.btn_cal_pick.isEnabled()
    view._on_wlasny_zapis_plikow(False)
    view.set_busy(True)
    assert "Trwa etap" in bar.btn_cal_pick.toolTip()
    view.set_busy(False)

    import sqlite3

    def _zablokowana(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(repo, "link_calibration", _zablokowana)
    _wybierz_w_oknie(f"(#{MF_OIII})", [])
    QTest.mouseClick(bar.btn_cal_pick, Qt.LeftButton)
    QApplication.processEvents()
    assert "baza jest zajęta" in komunikaty[-1]
    assert _ogniwo(kcon) == (MF_HA, "horreum", "recipe")


def test_zaznaczenie_wraca_po_prawdziwym_odswiezeniu_po_etapie(view, kcon):
    """„Policz teraz” → etap → przeładowanie zbioru (`refresh`, które czyści zaznaczenie) → klatka
    wraca do zaznaczenia, a panel pokazuje przeliczony stan. Bez tego powrót był całym kosztem
    tej drogi (ponowne szukanie klatki)."""
    view.run_stage_fn = lambda etap: None
    bar = _otworz_panel_lightu(view)
    QTest.mouseClick(bar.btn_cal_count, Qt.LeftButton)
    run_lineage(kcon, now=NOW)                             # to, co zrobi etap w tle
    view.refresh()                                         # przeładowanie po przebiegu
    QApplication.processEvents()
    assert [r["frame_id"] for r in view._selected_data_rows()] == [LIGHT]
    view.refresh_lineage_panel()
    assert "pole (flat): jest" in bar.head.text()


def test_otwarty_panel_rodowodu_przezywa_nowy_widok(qapp, kcon, ustawienia):
    """Panel rodowodu otwarty przy zamknięciu wraca otwarty (QSettings), zamknięty - zamknięty."""
    from horreum.gui.grid import FramesView
    pierwszy = FramesView(kcon, now_fn=lambda: NOW)
    assert not pierwszy._lineage_panel_open()
    pierwszy._toggle_panel("lineage")
    assert ustawienia.value("grid/lineage_panel_open", False, type=bool) is True
    drugi = FramesView(kcon, now_fn=lambda: NOW)
    assert drugi._lineage_panel_open(), "otwarty panel nie wrócił"
    drugi._toggle_panel("lineage")                        # zamknięcie zapamiętuje „zamknięty"
    trzeci = FramesView(kcon, now_fn=lambda: NOW)
    assert not trzeci._lineage_panel_open()
    drugi._toggle_panel("macro")                          # inny panel = rodowód zamknięty
    assert ustawienia.value("grid/lineage_panel_open", True, type=bool) is False
    for v in (pierwszy, drugi, trzeci):
        v.close()
        v.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_gospodarz_przelacza_na_Dostawe_tylko_dla_rodowodu_stosow():
    """`run_stage_fn` z NAZWĄ etapu: rodowód stosów (długi) przełącza na Dostawę, rodowód kalibracji
    (ułamek sekundy) zostaje w Zbiorach - powrót z Dostawy był całym kosztem „Policz teraz”."""
    from horreum.gui.app import MainWindow, NAV_DOSTAWA

    class _Gospodarz:
        def __init__(self):
            self.etapy, self.widoki = [], []
            self.pipeline_view = self

        def run_stage(self, etap):
            self.etapy.append(etap)
            return None

        def _show_view(self, nav):
            self.widoki.append(nav)

    g = _Gospodarz()
    assert MainWindow._etap_po_gescie_rodowodu(g, "lineage") is None
    assert MainWindow._etap_po_gescie_rodowodu(g, "stack_lineage") is None
    assert g.etapy == ["lineage", "stack_lineage"] and g.widoki == [NAV_DOSTAWA]
