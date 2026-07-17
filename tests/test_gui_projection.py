"""Dialog „Wydaj na stół" (F2 redesignu — PLAN_ux_redesign §3) — testy STERUJĄCE realnym oknem Qt
(offscreen). Cele z QSettings (karty-radio, pamięć, walidacja przy dodawaniu), auto-DRY na otwarciu
(tryb inline przez `dry_async=False` — seam wzorca `_writeback_async`), auto-decyzja hardlink/kopia
po serialach wolumenów (R#4+R2-1), licznik generacji stale-DRY (R2-2), słownictwo per tryb (wiz #5),
rozmiar przy kopii (R#5), „Utwórz…" na PRAWDZIWYCH plikach. Czyste pomocniki (chosen_present/
volume_decision/size_summary/plural) testowane wprost. `importorskip` — bez PySide6 plik pomijany.
Realny R: NIGDY nie dotykany; QSettings izolowane od rejestru (fake_settings)."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, projection

from PySide6.QtWidgets import QApplication

from horreum.gui import projection_dialog as pd_mod
from horreum.gui.projection_dialog import (
    ProjectionDialog, chosen_present, plural, size_summary, volume_decision,
)

NOW = "2026-07-17T00:00:00+00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def fake_settings(monkeypatch):
    """Izolacja QSettings (cele wydania) — pamięć w dict zamiast realnego rejestru użytkownika."""
    store = {}
    from PySide6.QtCore import QSettings
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: store.get(k, d))
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: store.__setitem__(k, v))
    return store


def _seed_files(con, tmp_path, n=2, sizes=None, volume="V"):
    """`n` frame'ów z PRAWDZIWYMI plikami (do os.link/copy w „Utwórz"). Bez header/object/filter →
    segmenty _UNSET (test plumbingu dialogu). `sizes` = size_bytes per plik (None = brak rozmiaru).
    Zwraca listę frame_id."""
    lib = tmp_path / "lib"
    lib.mkdir(exist_ok=True)
    ids = []
    for i in range(n):
        p = lib / f"raw{i}.fits"
        p.write_bytes(b"DATA" + bytes([i]))
        con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) VALUES (?,?,?,?,?)",
                    (i + 1, f"d{i}", "light", "fits", NOW))
        sb = sizes[i] if sizes else p.stat().st_size
        con.execute("INSERT INTO location (frame_id, volume, path, present, size_bytes) VALUES (?,?,?,?,?)",
                    (i + 1, volume, str(p), 1, sb))
        ids.append(i + 1)
    con.commit()
    return ids


def _target(fake_settings, root, name="feed"):
    """Zapamiętany cel w fake-QSettings PRZED otwarciem dialogu (otwarcie → auto-DRY)."""
    fake_settings["projection/targets"] = json.dumps([{"name": name, "path": str(root)}])
    fake_settings["projection/last_target"] = str(root)


def _dlg(con, ids):
    return ProjectionDialog(con, ids, now_fn=lambda: NOW, dry_async=False)


# ---------- pomocniki Qt-wolne (decyzja wolumenowa, rozmiar, liczba mnoga) ----------

def test_chosen_present_pierwsza_obecna_kwarantanna_odpada():
    """Lustro D-P5: pierwsza obecna per frame; frame bez obecnej kopii NIE uczestniczy (R2-1)."""
    rows = [
        {"frame_id": 1, "location_id": 10, "volume": "V", "size_bytes": 7},
        {"frame_id": 1, "location_id": 11, "volume": "X", "size_bytes": 7},   # druga kopia — nie wybrana
        {"frame_id": 2, "location_id": None, "volume": None, "size_bytes": None},  # zniknięta → odpada
    ]
    assert [r["location_id"] for r in chosen_present(rows)] == [10]


def test_volume_decision_tabela():
    def loc(vol):
        return {"frame_id": 1, "location_id": 1, "volume": vol, "size_bytes": None}
    assert volume_decision([loc("V")], "V") is False               # wszystkie na celu → hardlink
    assert volume_decision([loc("V"), loc("X")], "V") is True      # JAKIKOLWIEK inny → kopia CAŁOŚCI
    assert volume_decision([loc("?")], "?") is True                # '?' = wolumen nieznany, nigdy hardlink
    assert volume_decision([loc("V")], None) is True               # serial celu nieustalony → kopia
    assert volume_decision([], "V") is False                       # pusty zbiór wybranych — nic nie wymusza


def test_size_summary_null_osobnym_kubelkiem():
    rows = [{"size_bytes": 100}, {"size_bytes": None}, {"size_bytes": 50}]
    assert size_summary(rows) == (150, 1)


def test_plural_polski():
    assert plural(1, "kopię", "kopie", "kopii") == "kopię"
    assert plural(3, "kopię", "kopie", "kopii") == "kopie"
    assert plural(13, "kopię", "kopie", "kopii") == "kopii"
    assert plural(22, "link", "linki", "linków") == "linki"
    assert plural(5, "link", "linki", "linków") == "linków"


# ---------- dialog: auto-DRY + hardlink ----------

def test_dialog_cel_z_pamieci_auto_dry_1_klik(qapp, tmp_path, fake_settings, monkeypatch):
    """Cel z pamięci → otwarcie dialogu SAMO robi DRY (zdarzenie dyskretne #1) i uzbraja „Utwórz
    N linków" — ścieżka wydania 1-klik. Apply tworzy prawdziwe hardlinki + manifest."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g.db"))
    ids = _seed_files(con, tmp_path, 2)
    root = tmp_path / "_WBPP" / "feed"
    _target(fake_settings, root)
    dlg = _dlg(con, ids)
    assert "do zlinkowania: 2" in dlg.report.toPlainText()
    assert dlg.btn_apply.isEnabled()
    assert dlg.btn_apply.text() == "Utwórz 2 linki"
    assert not root.exists()                              # DRY: zero tworzenia
    sel = next(c for c in dlg._cards if c["radio"].isChecked())
    assert "hardlink" in sel["note"].text()               # szczera nota trybu na karcie (brief §3)
    dlg._on_apply()
    assert "zlinkowano: 2" in dlg.report.toPlainText()
    linked = list((root / "_UNSET" / "_UNSET").glob("*.fits"))
    assert len(linked) == 2
    for lf in linked:                                     # prawdziwy hardlink
        src = tmp_path / "lib" / lf.name
        assert os.stat(str(src)).st_ino == os.stat(str(lf)).st_ino
    assert (root / projection.MANIFEST_NAME).exists()
    assert not dlg.btn_apply.isEnabled()                  # po Utwórz → wymaga nowego DRY
    assert dlg.btn_apply.text() == "Utworzono ✓"          # przycisk nie głosi zaszłej akcji (wiz K2)
    assert dlg.btn_dry.isEnabled()                        # ręczny re-DRY dostępny po biegu (wiz W2/K5)
    assert fake_settings["projection/last_target"] == str(root)
    con.close()


def test_dialog_auto_kopia_inny_wolumen(qapp, tmp_path, fake_settings, monkeypatch):
    """Seriale źródeł ≠ serial celu → auto-KOPIA całości: słownictwo per tryb (wiz #5), rozmiar
    z kubełkiem NULL (R#5), nota „inny wolumen" na karcie; pliki po apply NIE są hardlinkami."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "INNY")
    con = db.open_db(str(tmp_path / "g2.db"))
    ids = _seed_files(con, tmp_path, 2, sizes=[100, None])
    root = tmp_path / "_WBPP" / "kopie"
    _target(fake_settings, root)
    dlg = _dlg(con, ids)
    rep = dlg.report.toPlainText()
    assert "do skopiowania: 2" in rep
    assert "rozmiar kopii: 100 B" in rep
    assert "(+1 plik bez rozmiaru)" in rep                # odmiana K1: 1 plik / 2 pliki / 5 plików
    assert dlg.btn_apply.text() == "Utwórz 2 kopie"
    sel = next(c for c in dlg._cards if c["radio"].isChecked())
    assert "inny wolumen" in sel["note"].text()
    dlg._on_apply()
    assert "skopiowano: 2" in dlg.report.toPlainText()
    copied = list((root / "_UNSET" / "_UNSET").glob("*.fits"))
    assert len(copied) == 2
    for cf in copied:                                     # kopia bajtów, NIE hardlink
        assert os.stat(str(cf)).st_nlink == 1
    con.close()


def test_dialog_zniknieta_klatka_nie_przelacza_na_kopie(qapp, tmp_path, fake_settings, monkeypatch):
    """R2-1: frame bez obecnej kopii idzie do `pominięto` i NIE uczestniczy w decyzji — reszta na
    wolumenie celu zostaje przy hardlinkach."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g3.db"))
    ids = _seed_files(con, tmp_path, 1)
    con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) VALUES (?,?,?,?,?)",
                (99, "d99", "light", "fits", NOW))
    con.execute("INSERT INTO location (frame_id, volume, path, present, size_bytes) VALUES (?,?,?,?,?)",
                (99, "X", str(tmp_path / "lib" / "gone.fits"), 0, None))   # tylko zniknięta kopia
    con.commit()
    _target(fake_settings, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids + [99])
    rep = dlg.report.toPlainText()
    assert "do zlinkowania: 1" in rep
    assert "pominięto: 1" in rep
    assert dlg.btn_apply.text() == "Utwórz 1 link"        # NIE kopia — zniknięta nie decyduje
    con.close()


def test_dialog_wymus_kopie_checkbox(qapp, tmp_path, fake_settings, monkeypatch):
    """Tryb zaawansowany: „wymuś kopię" nadpisuje auto-decyzję hardlink (SMB-niewiadoma)."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g4.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(fake_settings, tmp_path / "_Review" / "x")
    dlg = _dlg(con, ids)
    assert "do zlinkowania: 1" in dlg.report.toPlainText()
    dlg.chk_copy.setChecked(True)                         # zdarzenie dyskretne → świeży DRY
    assert "do skopiowania: 1" in dlg.report.toPlainText()
    assert dlg.btn_apply.text() == "Utwórz 1 kopię"
    sel = next(c for c in dlg._cards if c["radio"].isChecked())
    assert "wymuszona kopia" in sel["note"].text()
    con.close()


# ---------- dialog: inwalidacja / generacje ----------

def test_dialog_zmiana_ukladu_swiezy_dry_pod_nowe_parametry(qapp, tmp_path, fake_settings, monkeypatch):
    """Zmiana układu = zdarzenie dyskretne: inwalidacja (generacja ++) + auto-DRY pod DOKŁADNIE nowe
    parametry; kontrakt `_invalidate` (bez świeżego DRY „Utwórz" gaśnie) zachowany."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g5.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(fake_settings, tmp_path / "_WBPP" / "a")
    dlg = _dlg(con, ids)
    assert dlg._plan.layout == "po-obiektach"
    gen0 = dlg._gen
    dlg.combo_layout.setCurrentIndex(1)                   # wbpp-feed
    assert dlg._gen > gen0                                # inwalidacja podbiła generację
    assert dlg._plan.layout == "wbpp-feed"                # świeży DRY pod nowe parametry
    assert dlg.btn_apply.isEnabled()
    dlg._invalidate()                                     # sama inwalidacja → „Utwórz" gaśnie
    assert not dlg.btn_apply.isEnabled()
    assert dlg._plan is None
    con.close()


def test_dialog_stale_dry_odrzucony_i_retrigger(qapp, tmp_path, fake_settings, monkeypatch):
    """R2-2: wynik DRY ze STARĄ generacją jest odrzucany (nie uzbraja „Utwórz" pod stare parametry)
    i planuje re-trigger; świeży przebieg uzbraja pod bieżące."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g6.db"))
    ids = _seed_files(con, tmp_path, 2)
    _target(fake_settings, tmp_path / "_WBPP" / "a")
    dlg = _dlg(con, ids)
    dlg._invalidate()                                     # otwarte okno stale: gen++ bez DRY
    stale = {"plan": "STALE", "res": None, "auto_copy": False, "copy": False,
             "target_serial": "V", "size_total": 0, "size_missing": 0}
    dlg._on_dry_done(dlg._gen - 1, stale)                 # spóźniony wynik starej generacji
    assert dlg._plan is None                              # odrzucony — nie uzbroił
    assert not dlg.btn_apply.isEnabled()
    assert dlg._dry_pending                               # re-trigger zaplanowany
    dlg._trigger_dry()                                    # (w trybie threaded robi to _cleanup)
    assert dlg._plan is not None and dlg._plan != "STALE"
    assert dlg.btn_apply.isEnabled()
    assert dlg.btn_apply.text() == "Utwórz 2 linki"
    con.close()


# ---------- dialog: cele (dodawanie, walidacja, pamięć) ----------

def test_dialog_walidacja_celu_przy_dodawaniu(qapp, tmp_path, fake_settings, monkeypatch):
    """Walidacja segmentu _WBPP/_Review przy DODAWANIU (raz — brief §3): zły cel nie powstaje;
    dobry powstaje, jest zaznaczony i auto-DRY startuje."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g7.db"))
    ids = _seed_files(con, tmp_path, 1)
    dlg = _dlg(con, ids)
    assert dlg._add_target_path(str(tmp_path / "LIGHTS"), "zly") is False
    assert "Nie można dodać celu" in dlg.report.toPlainText()
    assert dlg._load_target_list() == []
    good = str(tmp_path / "_Review" / "stol")
    assert dlg._add_target_path(good, "stol") is True
    assert dlg._current_root() == good
    assert "do zlinkowania: 1" in dlg.report.toPlainText()   # auto-DRY po zaznaczeniu nowej karty
    con.close()


def test_dialog_cel_pamietany_miedzy_otwarciami(qapp, tmp_path, fake_settings, monkeypatch):
    """Wiz #8: cel dodany w jednym otwarciu wraca jako domyślna karta w następnym (3→1 interakcji)."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g8.db"))
    ids = _seed_files(con, tmp_path, 1)
    dlg1 = _dlg(con, ids)
    root = str(tmp_path / "_WBPP" / "feed")
    dlg1._add_target_path(root, "feed")
    dlg2 = _dlg(con, ids)                                 # nowe otwarcie
    assert dlg2._current_root() == root                   # karta z pamięci, zaznaczona
    assert dlg2.btn_apply.isEnabled()                     # auto-DRY na otwarciu uzbroił „Utwórz"
    con.close()


def test_dialog_bez_celu_szczery_komunikat(qapp, tmp_path, fake_settings):
    """Bez zapamiętanych celów dialog prosi o cel — zero DRY, „Utwórz" i „Odśwież" wyłączone (K5),
    wskaźnik biegu schowany (W2)."""
    con = db.open_db(str(tmp_path / "g9.db"))
    ids = _seed_files(con, tmp_path, 1)
    dlg = _dlg(con, ids)
    assert dlg._current_root() is None
    assert not dlg.btn_apply.isEnabled()
    assert not dlg.btn_dry.isEnabled()
    assert not dlg.busy.isVisible()
    con.close()


def test_framesview_projekcja_pusta_perspektywa(qapp, tmp_path):
    """FramesView._open_projection na pustym gridzie → szczery status, bez dialogu (bez exec/blokady)."""
    from horreum.gui.grid import FramesView

    con = db.open_db(str(tmp_path / "fv.db"))
    view = FramesView(con, now_fn=lambda: NOW)
    msgs = []
    view.status_message.connect(msgs.append)
    view._frame_ids = []
    view._open_projection()
    assert any("brak widocznych" in m for m in msgs)
    con.close()
