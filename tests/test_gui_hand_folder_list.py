"""Lista folderów okien gestu ręki (`config_dialog` + `observatory_dialog`) - filtr, elizja
środka ścieżki, okno startowe szersze. Zmierzone przed zmianą na żywej bazie: okno stanowiska
333 × 589 px, w kadrze 10 ze 178 folderów, ścieżka ucięta przed licznikiem, LMC 50. wierszem -
wskazanie folderu kosztowało 9-10 interakcji. Cel: 6.

Foldery i współrzędne SYNTETYCZNE (repo publiczne).
`importorskip` na poziomie MODUŁU; `QT_QPA_PLATFORM=offscreen` PRZED importem Qt."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from horreum import db, repo
from horreum.gui import i18n
from horreum.gui.config_dialog import (
    FOLDER_ROLE, AssignConfigDialog, elide_head_keep_tail, folder_hit,
)
from horreum.gui.observatory_dialog import AssignObservatoryDialog

NOW = "2026-10-06T12:00:00+00:00"
_N = 178                                     # tyle folderów miał kubełek w zgłoszeniu
_LMC = 49                                    # LMC jako 50. wiersz


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def con(qapp, tmp_path):
    c = db.open_db(str(tmp_path / "h.db"))
    repo.propose_observatory(c, lat=10.0, lon=20.0, now=NOW)
    yield c
    c.close()


def _folder(i):
    nazwa = "LMC" if i == _LMC else f"OBIEKT{i:03d}"
    return f"X:\\ARCHIWUM\\ASTRO\\RAW\\WYJAZDY\\2024\\{nazwa}\\2024-01-{i % 28 + 1:02d}"


def _grupy_obs():
    return [{"folder": _folder(i), "observatory_label": None, "n_frames": 3,
             "frame_ids": [3 * i, 3 * i + 1, 3 * i + 2], "kinds": [("light/raw", 3)]}
            for i in range(_N)]


def _grupy_cfg():
    return [{"folder": _folder(i), "camera_id": 1, "camera_model": "A7R3", "telescop": None,
             "telescope_label": None, "n_frames": 3, "frame_ids": [3 * i, 3 * i + 1, 3 * i + 2],
             "other_kinds": []} for i in range(_N)]


def _widoczne(dlg):
    return [i for i in range(dlg.items.count()) if not dlg.items.item(i).isHidden()]


# --- predykat i elizja (logika) ---

def test_folder_hit_kazde_slowo_bez_wielkosci_liter():
    sciezka = "X:\\A\\LMC\\2024-01-05"
    assert folder_hit("lmc", sciezka) and folder_hit("LMC 2024", sciezka)
    assert folder_hit("", sciezka) and folder_hit("   ", sciezka)
    assert not folder_hit("lmc 2023", sciezka)


def test_elizja_tnie_srodek_sciezki_i_zostawia_ogon(qapp):
    fm = QFontMetrics(QApplication.font())
    glowa = _folder(_LMC)
    ogon = "  ·  3 klatki  ·  light/raw (3)"
    szer = fm.horizontalAdvance(ogon) + fm.horizontalAdvance(glowa) // 2
    tekst = elide_head_keep_tail(fm, glowa, ogon, szer)
    assert tekst.endswith(ogon)                           # licznik cały
    assert "…" in tekst and tekst.startswith("X:")        # środek ścieżki ucięty, początek jest
    assert tekst[: -len(ogon)].endswith(glowa[-3:])       # koniec ścieżki (dzień) też jest
    assert fm.horizontalAdvance(tekst) <= szer
    assert elide_head_keep_tail(fm, glowa, ogon, 10 ** 5) == glowa + ogon


def test_delegat_maluje_elidowany_tekst_a_wiersz_zostaje_pelny(con):
    dlg = AssignObservatoryDialog(con, groups=_grupy_obs())
    it = dlg.items.item(_LMC)
    assert it.data(FOLDER_ROLE) == _folder(_LMC)
    assert it.text().startswith(_folder(_LMC)) and it.toolTip() == it.text()
    opt = QStyleOptionViewItem()
    opt.initFrom(dlg.items.viewport())
    fm = QFontMetrics(opt.font)
    opt.rect = QRect(0, 0, fm.horizontalAdvance(it.text()) // 2, fm.height() + 4)
    index = dlg.items.model().index(_LMC, 0)
    dlg.items.itemDelegate().initStyleOption(opt, index)
    ogon = it.text()[len(_folder(_LMC)):]
    assert opt.text.endswith(ogon) and "…" in opt.text
    dlg.close()


# --- okno: rozmiar, filtr, Enter, przełącznik całości ---

@pytest.mark.parametrize("okno", ["obs", "cfg"])
def test_okno_startuje_szerokie_w_granicach_ekranu(con, okno):
    """Przed zmianą okno startowało na `sizeHint` (333 px na żywej bazie, ~45 znaków). Teraz
    ~120 znaków fontu, ale nigdy szersze niż ekran."""
    dlg = (AssignObservatoryDialog(con, groups=_grupy_obs()) if okno == "obs"
           else AssignConfigDialog(con, groups=_grupy_cfg()))
    fm = dlg.fontMetrics()
    avail = dlg.screen().availableGeometry()
    assert dlg.width() >= min(fm.averageCharWidth() * 100, int(avail.width() * 0.8))
    assert dlg.width() <= avail.width() and dlg.height() <= avail.height()
    assert dlg.items.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    dlg.close()


def test_filtr_chowa_niepasujace_i_mowi_o_braku_trafien(con):
    dlg = AssignObservatoryDialog(con, groups=_grupy_obs())
    dlg.filter.setText("lmc")
    assert _widoczne(dlg) == [_LMC]
    assert not dlg.filter.empty.isVisibleTo(dlg)
    dlg.filter.setText("nie ma takiego")
    assert _widoczne(dlg) == [] and dlg.filter.empty.isVisibleTo(dlg)
    assert "nie ma takiego" in dlg.filter.empty.text()
    dlg.filter.clear()                                    # natywne „×” = pusta fraza
    assert len(_widoczne(dlg)) == _N and not dlg.filter.empty.isVisibleTo(dlg)
    dlg.close()


def _klatki(rows):
    return [f for i in rows for f in (3 * i, 3 * i + 1, 3 * i + 2)]


def test_zestaw_od_stanu_domyslnego_zapisuje_tylko_widoczne(con):
    """Kontrakt „co widać, to się zapisze” od RZECZYWISTEGO stanu domyślnego okna zestawu
    (grupy wchodzą zaznaczone) - bez `check_all.click()` przed frazą."""
    i18n.set_lang("pl")
    dlg = AssignConfigDialog(con, groups=_grupy_cfg())
    assert len(dlg._zaznaczone()) == 3 * _N               # stan domyślny: wszystko zaznaczone
    dlg.combo.addItem("T", (1, "T"))                      # teleskop z parku (szew: baza bez parku)
    dlg.combo.setCurrentIndex(dlg.combo.count() - 1)
    dlg.filter.setText("lmc")
    assert _widoczne(dlg) == [_LMC]                       # zaznaczone, ale niepasujące - ukryte
    assert dlg._zaznaczone() == _klatki([_LMC])
    assert dlg.accept_btn.text() == i18n.t("cfg.assign_btn", n=3)
    assert dlg.check_all.checkState() == Qt.Checked       # przełącznik odbija widoczne
    dlg.filter.clear()                                    # zaznaczenia ukrytych przetrwały filtr
    assert len(_widoczne(dlg)) == _N and len(dlg._zaznaczone()) == 3 * _N
    assert dlg.accept_btn.text() == i18n.t("cfg.assign_btn", n=3 * _N)
    dlg.filter.setText("lmc")
    dlg.accept_btn.click()
    assert dlg.selected == (1, "T", _klatki([_LMC]))      # zapis bierze tylko trafienie
    dlg.close()


def test_stanowisko_zapisuje_tylko_widoczne_zaznaczone(con):
    i18n.set_lang("pl")
    dlg = AssignObservatoryDialog(con, groups=_grupy_obs())
    dlg.combo.setCurrentIndex(1)
    dlg.items.item(3).setCheckState(Qt.Checked)
    dlg.filter.setText("lmc")
    assert _widoczne(dlg) == [_LMC]                       # zaznaczony #3 ukryty, nie odznaczony
    assert dlg.items.item(3).checkState() == Qt.Checked
    assert dlg._zaznaczone() == [] and not dlg.accept_btn.isEnabled()
    assert dlg.accept_btn.text() == i18n.t("obshand.assign_btn", n=0)
    QTest.keyClick(dlg.filter, Qt.Key_Return)
    assert dlg.accept_btn.text() == i18n.t("obshand.assign_btn", n=3)
    dlg.filter.clear()
    assert len(_widoczne(dlg)) == _N and dlg._zaznaczone() == _klatki([3, _LMC])
    dlg.filter.setText("lmc")
    dlg.accept_btn.click()
    assert dlg.selected["frame_ids"] == _klatki([_LMC])
    dlg.close()


def test_sekwencja_zaznacz_fraza_odznacz_spojna_z_fraza(con):
    """Widoczność zależy wyłącznie od frazy: zmiana zaznaczenia jej nie rusza, a licznik idzie
    za widocznymi zaznaczonymi."""
    dlg = AssignObservatoryDialog(con, groups=_grupy_obs())
    dlg.items.item(_LMC).setCheckState(Qt.Checked)        # zaznacz
    dlg.items.item(5).setCheckState(Qt.Checked)
    dlg.filter.setText("2024-01-06")                      # zmień frazę: i = 5, 33, 61, …
    assert 5 in _widoczne(dlg) and _LMC not in _widoczne(dlg)
    assert dlg._zaznaczone() == _klatki([5])
    dlg.items.item(5).setCheckState(Qt.Unchecked)         # odznacz widoczny
    assert 5 in _widoczne(dlg)                            # dalej pasuje - dalej widoczny
    assert dlg._zaznaczone() == []
    assert dlg.accept_btn.text() == i18n.t("obshand.assign_btn", n=0)
    dlg.filter.clear()
    assert dlg._zaznaczone() == _klatki([_LMC])
    dlg.close()


def test_enter_w_filtrze_zaznacza_trafienie_i_nie_zamyka_okna(con):
    dlg = AssignObservatoryDialog(con, groups=_grupy_obs())
    dlg.combo.setCurrentIndex(1)                          # cel gotowy - domyślny przycisk aktywny
    dlg.show()
    QTest.keyClicks(dlg.filter, "lmc")
    QTest.keyClick(dlg.filter, Qt.Key_Return)
    assert dlg.items.item(_LMC).checkState() == Qt.Checked
    assert dlg.isVisible() and dlg.selected is None       # Enter nie zapisał gestu w pół wyboru
    QTest.keyClick(dlg.filter, Qt.Key_Return)             # brak kolejnego trafienia - bez skutku
    assert dlg._zaznaczone() == [3 * _LMC, 3 * _LMC + 1, 3 * _LMC + 2]
    dlg.close()


def test_przelacznik_calosci_dziala_na_widocznych(con):
    i18n.set_lang("pl")
    dlg = AssignConfigDialog(con, groups=_grupy_cfg())   # zestaw wchodzi ZAZNACZONY
    dlg.check_all.click()                                 # wszystkie → żadna
    assert dlg._zaznaczone() == []
    dlg.filter.setText("2024-01-05")                      # i = 4, 32, 60, … (co 28.)
    widoczne = _widoczne(dlg)
    assert 1 < len(widoczne) < _N
    dlg.check_all.click()
    zaznaczone = [i for i in range(_N) if dlg.items.item(i).checkState() == Qt.Checked]
    assert zaznaczone == widoczne                         # ukryte nietknięte
    assert dlg.check_all.checkState() == Qt.Checked       # przełącznik odbija widoczne
    dlg.close()


def test_wskazanie_folderu_w_szesciu_interakcjach(con):
    """Ścieżka z mierzonym kosztem: (1) otwarcie okna, (2) wpisanie frazy - fokus już w filtrze,
    (3) Enter zaznacza trafienie, (4-5) rozwinięcie listy stanowisk i wybór, (6) zapis."""
    dlg = AssignObservatoryDialog(con, groups=_grupy_obs())                    # 1
    dlg.show()
    dlg.activateWindow()
    assert dlg.focusWidget() is dlg.filter
    QTest.keyClicks(dlg.focusWidget(), "lmc")                                  # 2
    QTest.keyClick(dlg.focusWidget(), Qt.Key_Return)                           # 3
    dlg.combo.setCurrentIndex(1)                                               # 4-5
    dlg.accept_btn.click()                                                     # 6
    assert dlg.selected is not None
    assert dlg.selected["frame_ids"] == [3 * _LMC, 3 * _LMC + 1, 3 * _LMC + 2]
