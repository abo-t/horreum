"""Dialog „Wydaj na stół" (F2 redesignu — PLAN_ux_redesign §3) — testy STERUJĄCE realnym oknem Qt
(offscreen). Cele z QSettings (karty-radio, pamięć, walidacja przy dodawaniu), auto-DRY na otwarciu
(tryb inline przez `off_thread=False` — seam wzorca `_writeback_async`), APPLY OFF-THREAD (P2/W1:
pasek `done/total`, „Anuluj" na granicy pliku, zamrożone parametry, abort sondy), auto-decyzja hardlink/kopia
po serialach wolumenów (R#4+R2-1), licznik generacji stale-DRY (R2-2), słownictwo per tryb (wiz #5),
rozmiar przy kopii (R#5), „Utwórz…" na PRAWDZIWYCH plikach. Czyste pomocniki (chosen_present/
volume_decision/size_summary) testowane wprost. `importorskip` — bez PySide6 plik pomijany.
Realny R: NIGDY nie dotykany; QSettings izolowane od rejestru (conftest, fixture `ustawienia`)."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, projection

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from horreum.gui import i18n, theme
from horreum.gui import projection_dialog as pd_mod
from horreum.gui.projection_dialog import (
    ProjectionDialog, chosen_present, eta_text, size_summary, volume_decision,
)

NOW = "2026-07-17T00:00:00+00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


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


def _target(ustawienia, root, name="feed"):
    """Zapamiętany cel w ustawieniach PRZED otwarciem dialogu (otwarcie → auto-DRY)."""
    ustawienia.setValue("projection/targets", json.dumps([{"name": name, "path": str(root)}]))
    ustawienia.setValue("projection/last_target", str(root))


def _dlg(con, ids):
    return ProjectionDialog(con, ids, now_fn=lambda: NOW, off_thread=False)


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


def test_eta_text_dopiero_po_rozgrzewce():
    """ETA milczy, dopóki tempo nie jest wiarygodne (pierwsze `warmup` plików) i na ostatnim pliku;
    dalej skaluje jednostkę s → min → h. Cofająca się prognoza byłaby gorsza niż jej brak."""
    assert eta_text(1, 100, 1.0) == ""                     # rozgrzewka: tempo z 1 próbki kłamie
    assert eta_text(100, 100, 10.0) == ""                  # koniec — nie ma czego prognozować
    assert eta_text(10, 20, 0) == ""                       # zegar nie ruszył
    assert eta_text(10, 20, 10.0) == " · pozostało ~10 s"
    assert eta_text(10, 1000, 10.0) == " · pozostało ~16 min"   # 990 pozostałych × 1 s/plik
    assert eta_text(10, 10_000, 10.0) == " · pozostało ~2.8 h"


# ---------- dialog: auto-DRY + hardlink ----------

def test_dialog_cel_z_pamieci_auto_dry_1_klik(qapp, tmp_path, ustawienia, monkeypatch):
    """Cel z pamięci → otwarcie dialogu SAMO robi DRY (zdarzenie dyskretne #1) i uzbraja „Utwórz
    N linków" — ścieżka wydania 1-klik. Apply tworzy prawdziwe hardlinki + manifest."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g.db"))
    ids = _seed_files(con, tmp_path, 2)
    root = tmp_path / "_WBPP" / "feed"
    _target(ustawienia, root)
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
    assert ustawienia.value("projection/last_target") == str(root)
    con.close()


def test_dry_mowi_o_innym_ukladzie_w_korzeniu(qapp, tmp_path, ustawienia, monkeypatch):
    """Resztka z recenzji P2: manifest niósł `segments`, ale nikt ich nie czytał. Auto-DRY na
    otwarciu ma powiedzieć, że w korzeniu stoi drzewo o INNYM kształcie — stare pozycje leżą pod
    inną ścieżką, więc `conflict` = 0 i raport bez tej linii wygląda czysto. Ostrzeżenie, nie
    blokada: „Utwórz" zostaje uzbrojone."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "drift.db"))
    ids = _seed_files(con, tmp_path, 2)
    root = tmp_path / "_WBPP" / "feed"
    root.mkdir(parents=True)
    (root / projection.MANIFEST_NAME).write_text(json.dumps(
        {"layout": "wbpp-feed", "segments": [["object_canon"],
                                             ["telescope_label", "telescop_canon"],
                                             ["filter_canon"]]}), encoding="utf-8")
    _target(ustawienia, root)
    dlg = _dlg(con, ids)
    rep = dlg.report.toPlainText()
    assert "innym układzie" in rep and "wbpp-feed" in rep
    assert "do zlinkowania: 2" in rep and dlg.btn_apply.isEnabled()
    con.close()


def test_dialog_auto_kopia_inny_wolumen(qapp, tmp_path, ustawienia, monkeypatch):
    """Seriale źródeł ≠ serial celu → auto-KOPIA całości: słownictwo per tryb (wiz #5), rozmiar
    z kubełkiem NULL (R#5), nota „inny wolumen" na karcie; pliki po apply NIE są hardlinkami."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "INNY")
    con = db.open_db(str(tmp_path / "g2.db"))
    ids = _seed_files(con, tmp_path, 2, sizes=[100, None])
    root = tmp_path / "_WBPP" / "kopie"
    _target(ustawienia, root)
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


def test_dialog_zniknieta_klatka_nie_przelacza_na_kopie(qapp, tmp_path, ustawienia, monkeypatch):
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
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids + [99])
    rep = dlg.report.toPlainText()
    assert "do zlinkowania: 1" in rep
    assert "pominięto: 1" in rep
    assert dlg.btn_apply.text() == "Utwórz 1 link"        # NIE kopia — zniknięta nie decyduje
    con.close()


def test_dialog_wymus_kopie_checkbox(qapp, tmp_path, ustawienia, monkeypatch):
    """Tryb zaawansowany: „wymuś kopię" nadpisuje auto-decyzję hardlink (SMB-niewiadoma)."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g4.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(ustawienia, tmp_path / "_Review" / "x")
    dlg = _dlg(con, ids)
    assert "do zlinkowania: 1" in dlg.report.toPlainText()
    dlg.chk_copy.setChecked(True)                         # zdarzenie dyskretne → świeży DRY
    assert "do skopiowania: 1" in dlg.report.toPlainText()
    assert dlg.btn_apply.text() == "Utwórz 1 kopię"
    sel = next(c for c in dlg._cards if c["radio"].isChecked())
    assert "wymuszona kopia" in sel["note"].text()
    con.close()


# ---------- dialog: APPLY off-thread (P2/W1) ----------

def _wait_until(pred, timeout_ms=10_000):
    """Pompuj pętlę zdarzeń, aż `pred()` (wynik wątku tła dolatuje sygnałem KOLEJKOWANYM — bez pompy
    slot nigdy się nie wykona). False = timeout, żeby test padł na asercji, nie zawisł."""
    from PySide6.QtCore import QDeadlineTimer
    from PySide6.QtTest import QTest

    deadline = QDeadlineTimer(timeout_ms)
    while not pred():
        if deadline.hasExpired():
            return False
        QTest.qWait(10)
    return True


def _spy_progress(monkeypatch, hook=None):
    """Podgląd postępu apply przez PODKLASĘ `ApplyWorker` (podmiana atrybutu dialogu pinowałaby MOMENT
    `connect`, nie zachowanie — przeniesienie connectów do `__init__` rozbroiłoby szpiega po cichu).
    `hook(done_n, worker)` wołany PO emisji — stąd `request_cancel` w środku biegu."""
    seen = []

    class SpyWorker(pd_mod.ApplyWorker):
        def _emit_progress(self, done_n, total, dst, status):
            super()._emit_progress(done_n, total, dst, status)
            seen.append((done_n, total, status))
            if hook is not None:
                hook(done_n, self)

    monkeypatch.setattr(pd_mod, "ApplyWorker", SpyWorker)
    return seen


def test_apply_offthread_postep_i_pasek(qapp, tmp_path, ustawienia, monkeypatch):
    """W1: apply idzie przez `ApplyWorker` z postępem per plik (pasek DETERMINOWANY `done/total` —
    apply zna liczbę z planu). Po biegu pasek wraca do postaci DRY (nieokreślony, schowany)."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "a1.db"))
    ids = _seed_files(con, tmp_path, 3)
    root = tmp_path / "_WBPP" / "feed"
    _target(ustawienia, root)
    in_run = []
    seen = _spy_progress(monkeypatch, hook=lambda n, w: in_run.append(dlg.report.toPlainText()))
    dlg = _dlg(con, ids)
    dlg._on_apply()
    # P1: przez CAŁY bieg największy panel okna nie może twierdzić „DRY - bez zmian na dysku"
    assert all("DRY" not in r and "Wydaję na stół" in r and str(root) in r for r in in_run)
    assert [s[0] for s in seen] == [1, 2, 3]               # postęp PER PLIK, nie jeden skok na końcu
    assert all(s[1] == 3 and s[2] == "linked" for s in seen)
    assert "zlinkowano: 3" in dlg.report.toPlainText()
    assert len(list((root / "_UNSET" / "_UNSET").glob("*.fits"))) == 3
    assert dlg.busy.isHidden() and dlg.busy.maximum() == 0   # z powrotem tryb DRY (nieokreślony)
    assert dlg.progress_note.text() == ""
    # widoczność przez isHidden(): isVisible() jest False, gdy przodek niepokazany (offscreen, jak w gridzie)
    assert not dlg.btn_apply.isHidden() and dlg.btn_cancel.isHidden()
    assert dlg.btn_apply.text() == "Utworzono ✓"
    con.close()


def test_apply_anulowanie_na_granicy_pliku(qapp, tmp_path, ustawienia, monkeypatch):
    """„Anuluj" po pierwszym pliku: rdzeń przerywa PRZED kolejnym → na dysku 1 plik, raport mówi
    „Przerwano" (nie „Utworzono"), „Utwórz" gaśnie — kolejne wydanie wymaga świeżego DRY."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "a2.db"))
    ids = _seed_files(con, tmp_path, 3)
    root = tmp_path / "_WBPP" / "feed"
    _target(ustawienia, root)
    _spy_progress(monkeypatch, hook=lambda n, w: w.request_cancel() if n == 1 else None)
    dlg = _dlg(con, ids)
    dlg._on_apply()
    rep = dlg.report.toPlainText()
    assert rep.startswith("Przerwano")
    assert "zlinkowano: 1" in rep
    assert len(list((root / "_UNSET" / "_UNSET").glob("*.fits"))) == 1   # reszta planu NIETKNIĘTA
    assert (root / projection.MANIFEST_NAME).exists()     # manifest opisuje wynik CZĘŚCIOWY
    assert dlg.btn_apply.text() == "Przerwano" and not dlg.btn_apply.isEnabled()
    assert dlg.combo_layout.isEnabled()                    # parametry odmrożone po biegu
    con.close()


def test_apply_zamraza_parametry_w_biegu(qapp, tmp_path, ustawienia, monkeypatch):
    """Parametry (cel/układ/kopia/„Odśwież") ZABLOKOWANE w biegu — inaczej klik wywołałby
    `_invalidate` i wyzerował `self._plan`, który worker właśnie materializuje."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "a3.db"))
    ids = _seed_files(con, tmp_path, 2)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    frozen = []
    _spy_progress(monkeypatch, hook=lambda n, w: frozen.append((
        dlg.combo_layout.isEnabled(), dlg.chk_copy.isEnabled(), dlg.btn_dry.isEnabled(),
        dlg.btn_add.isEnabled(), dlg._cards[0]["radio"].isEnabled(),
        not dlg.btn_cancel.isHidden(), not dlg.btn_apply.isHidden(), dlg.btn_apply.isEnabled())))
    dlg = _dlg(con, ids)
    dlg._on_apply()
    assert frozen and all(f == (False, False, False, False, False, True, False, False) for f in frozen)
    assert dlg.combo_layout.isEnabled() and dlg.chk_copy.isEnabled() and dlg.btn_dry.isEnabled()
    con.close()


def test_apply_abort_sondy_osobnym_sygnalem(qapp, tmp_path, ustawienia, monkeypatch):
    """Sonda pierwszego linku pada (SMB oddał kopię) → `ProjectionAbort` z wątku wraca sygnałem
    `aborted`: raport ABORT + wynik CZĘŚCIOWY, żadnego crashu, parametry odmrożone."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    monkeypatch.setattr(projection, "_verify_content", lambda src, dst, nbytes=65536: False)
    con = db.open_db(str(tmp_path / "a4.db"))
    ids = _seed_files(con, tmp_path, 3)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    dlg._on_apply()
    rep = dlg.report.toPlainText()
    assert rep.startswith("ABORT:") and "Wynik częściowy" in rep
    assert "verify_bad: 1" in rep
    assert dlg.btn_apply.text() == "Nie utworzono"
    assert not dlg.btn_apply.isEnabled()
    assert dlg.combo_layout.isEnabled() and dlg.btn_cancel.isHidden()
    con.close()


def test_apply_blad_nie_zabija_dialogu(qapp, tmp_path, ustawienia, monkeypatch):
    """Wyjątek w klindze → sygnał `failed` (raport, nie crash); „Utwórz" gaśnie, bo dysk mógł się
    zmienić częściowo — kolejna próba przez „Odśwież podgląd"."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "a5.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)

    def boom(*a, **kw):
        raise OSError("dysk odpięty")

    monkeypatch.setattr(projection, "apply", boom)
    dlg._on_apply()
    assert "Błąd: OSError: dysk odpięty" in dlg.report.toPlainText()
    assert "Odśwież podgląd" in dlg.report.toPlainText()
    assert dlg.btn_apply.text() == "Przerwane błędem"      # przycisk nie obiecuje akcji, której raport zabrania
    assert not dlg.btn_apply.isEnabled()
    assert not dlg.btn_apply.isHidden() and dlg.btn_cancel.isHidden()
    con.close()


def test_apply_realny_qthread_pelny_cykl(qapp, tmp_path, ustawienia, monkeypatch):
    """Jedyny test na PRAWDZIWYM `QThread` (reszta jedzie inline): DRY i apply przechodzą przez
    `moveToThread` + sygnały kolejkowane + `_cleanup_apply_thread`. Bez niego cała maszyneria
    wątkowa byłaby niepokryta, a nazwa „off-thread" — obietnicą bez dowodu."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "t1.db"))
    ids = _seed_files(con, tmp_path, 3)
    root = tmp_path / "_WBPP" / "feed"
    _target(ustawienia, root)
    dlg = ProjectionDialog(con, ids, now_fn=lambda: NOW, off_thread=True)
    assert _wait_until(lambda: dlg.btn_apply.isEnabled())          # auto-DRY na własnym wątku
    dlg._on_apply()
    assert _wait_until(lambda: dlg._apply_thread is None and dlg._apply_worker is None)
    assert "zlinkowano: 3" in dlg.report.toPlainText()
    assert len(list((root / "_UNSET" / "_UNSET").glob("*.fits"))) == 3
    assert dlg.btn_apply.text() == "Utworzono ✓"
    dlg.done(0)                                                    # zamknięcie po biegu: wątków już nie ma
    con.close()


def test_zamkniecie_w_biegu_anuluje_i_zostawia_okno(qapp, tmp_path, ustawienia, monkeypatch):
    """Zamknięcie (Zamknij/Esc/X) W BIEGU wydania = ŻĄDANIE ANULOWANIA, okno ZOSTAJE: nie ma
    czekania z timeoutem (kopia przez SMB przekracza każdy limit → wątek-sierota pod skasowanym
    rodzicem = „QThread: Destroyed while thread is still running"), a raport „Przerwano" ma dokąd
    trafić. Dopiero zamknięcie PO biegu naprawdę zamyka."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "t2.db"))
    ids = _seed_files(con, tmp_path, 3)
    root = tmp_path / "_WBPP" / "feed"
    _target(ustawienia, root)
    dlg = _dlg(con, ids)
    dlg.show()
    _spy_progress(monkeypatch, hook=lambda n, w: dlg.done(0) if n == 1 else None)
    dlg._on_apply()
    assert not dlg.isHidden()                                      # okno NIE zamknięte w biegu
    rep = dlg.report.toPlainText()
    assert rep.startswith("Przerwano") and "zlinkowano: 1" in rep  # zamknięcie zadziałało jak „Anuluj"
    assert "nietknięte: 2" in rep                                  # ile planu ZOSTAŁO (drzewo niżej jest z pełnego planu)
    dlg.done(0)                                                    # drugie zamknięcie, już po biegu
    assert dlg.isHidden()
    con.close()


def test_apply_blad_w_polowie_mowi_ile_powstalo(qapp, tmp_path, ustawienia, monkeypatch):
    """Błąd w POŁOWIE biegu: ścieżka anulowania mówi „nietknięte: N", ścieżka błędu musi powiedzieć,
    ile już powstało — inaczej user widzi samą awarię i nie wie o częściowym drzewie w celu."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "a6.db"))
    ids = _seed_files(con, tmp_path, 4)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    real_link = projection._link_to

    def boom_after_two(src, dst, *, do_apply, copy):
        if do_apply and boom_after_two.n >= 2:
            raise OSError("cel odpięty w biegu")
        boom_after_two.n += 1 if do_apply else 0
        return real_link(src, dst, do_apply=do_apply, copy=copy)

    boom_after_two.n = 0
    dlg = _dlg(con, ids)
    monkeypatch.setattr(projection, "_link_to", boom_after_two)
    dlg._on_apply()
    rep = dlg.report.toPlainText()
    assert "Błąd: OSError: cel odpięty w biegu" in rep
    assert "Utworzono 2 z 4 przed błędem" in rep
    con.close()


def test_apply_zamraza_caly_wiersz_karty(qapp, tmp_path, ustawienia, monkeypatch):
    """Zamrożenie bierze CAŁY wiersz karty (`holder`), nie samo radio — inaczej nota trybu zostaje
    w pełnej jasności i blokada czyta się plamiasto."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "a7.db"))
    ids = _seed_files(con, tmp_path, 2)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    notes = []
    dlg = _dlg(con, ids)
    _spy_progress(monkeypatch, hook=lambda n, w: notes.append(dlg._cards[0]["note"].isEnabled()))
    dlg._on_apply()
    assert notes and not any(notes)                        # nota gaśnie razem z radiem
    assert dlg._cards[0]["note"].isEnabled()               # i wraca po biegu
    con.close()


# ---------- dialog: inwalidacja / generacje ----------

def test_dialog_zmiana_ukladu_swiezy_dry_pod_nowe_parametry(qapp, tmp_path, ustawienia, monkeypatch):
    """Zmiana układu = zdarzenie dyskretne: inwalidacja (generacja ++) + auto-DRY pod DOKŁADNIE nowe
    parametry; kontrakt `_invalidate` (bez świeżego DRY „Utwórz" gaśnie) zachowany."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g5.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(ustawienia, tmp_path / "_WBPP" / "a")
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


def test_dialog_stale_dry_odrzucony_i_retrigger(qapp, tmp_path, ustawienia, monkeypatch):
    """R2-2: wynik DRY ze STARĄ generacją jest odrzucany (nie uzbraja „Utwórz" pod stare parametry)
    i planuje re-trigger; świeży przebieg uzbraja pod bieżące."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g6.db"))
    ids = _seed_files(con, tmp_path, 2)
    _target(ustawienia, tmp_path / "_WBPP" / "a")
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

def test_dialog_walidacja_celu_przy_dodawaniu(qapp, tmp_path, ustawienia, monkeypatch):
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


def test_dialog_cel_pamietany_miedzy_otwarciami(qapp, tmp_path, ustawienia, monkeypatch):
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


def test_dialog_bez_celu_szczery_komunikat(qapp, tmp_path, ustawienia):
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


# --- i18n: EN renderuje z katalogu (§4 rollout `projection_dialog`) ---

def test_en_render_projekcja_z_katalogu(qapp, tmp_path, ustawienia, monkeypatch):
    """§5 (rollout projekcji): `set_lang('en')` PRZED budową → tytuł/etykiety/przyciski ORAZ raport
    DRY+apply (`_format`, `eta_text`) renderują EN z katalogu; `t_plural` przycisku „Create N links".
    Realny hardlink jak w teście 1-klik. Autouse-fixture `_reset_i18n_lang` wraca na PL."""
    i18n.set_lang("en")
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "en.db"))
    ids = _seed_files(con, tmp_path, 2)
    root = tmp_path / "_WBPP" / "feed"
    _target(ustawienia, root)
    dlg = _dlg(con, ids)
    assert dlg.windowTitle() == "Serve to table"
    assert dlg.btn_add.text() == "+ another target…" and dlg.btn_apply.text() == "Create 2 links"
    rep = dlg.report.toPlainText()
    assert "to link: 2" in rep and "plan tree:" in rep       # nagłówki raportu DRY po EN
    sel = next(c for c in dlg._cards if c["radio"].isChecked())
    assert sel["note"].text() == "same volume → hardlink (zero bytes)"
    dlg._on_apply()
    assert "linked: 2" in dlg.report.toPlainText()
    assert dlg.btn_apply.text() == "Created ✓"
    assert eta_text(10, 20, 10.0) == " · ~10 s left"          # Qt-wolny helper też EN
    con.close()


# --- P-C: kolor semantyczny nagłówka raportu (wizytacja P2 — dialog był jednolicie szary) ---

def _block_fmt(edit, n):
    """Format PIERWSZEGO znaku bloku `n` raportu — tędy widać kolor nagłówka. `textFormats()` się
    do tego nie nadaje: oddaje zakres także dla tekstu NIEformatowanego (domyślny format bloku),
    więc „są formaty" nie znaczy „jest kolor"."""
    cur = QTextCursor(edit.document().findBlockByNumber(n))
    cur.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor)
    return cur.charFormat()


class _Res:
    """Minimalny nośnik wyniku dla `report_outcome` — Qt-wolny helper czyta tylko dwa pola."""

    def __init__(self, counts, cancelled=False):
        self.counts = counts
        self.cancelled = cancelled


def test_report_outcome_zielono_tylko_przy_pelnym_sukcesie():
    ok = {"linked": 5, "exists": 2}
    assert pd_mod.report_outcome(_Res(ok), partial=False) == "ok"
    assert pd_mod.report_outcome(_Res(ok, cancelled=True), partial=False) == "warn"
    assert pd_mod.report_outcome(_Res(ok), partial=True) == "warn"
    for bad in ("conflict", "error", "verify_bad", "skipped"):
        assert pd_mod.report_outcome(_Res({**ok, bad: 1}), partial=False) == "warn", bad


def test_show_report_koloruje_naglowek_nie_ruszajac_tekstu(qapp, tmp_path, ustawienia, monkeypatch):
    """Kolor to warstwa FORMATU: `toPlainText()` oddaje dokładnie to, co weszło (kontrakt „raport
    zaczyna się od «Przerwano»" trzyma), a pierwszy blok dostaje kolor roli i bold. Drugi blok
    zostaje bez koloru — inaczej kolorowałby się cały słupek liczb."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "col.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    dlg._show_report("Utworzono\nzlinkowano: 1", "ok")
    assert dlg.report.toPlainText() == "Utworzono\nzlinkowano: 1"
    head = _block_fmt(dlg.report, 0)
    assert head.foreground().color().name().lower() == theme.accents(theme.DEFAULT)["ok_green"].lower()
    assert head.fontWeight() > QFont.Normal
    tail = _block_fmt(dlg.report, 1)                       # słupek liczb zostaje neutralny
    assert tail.foreground().style() == Qt.NoBrush and tail.fontWeight() == QFont.Normal
    con.close()


def test_show_report_bez_werdyktu_nie_maluje(qapp, tmp_path, ustawienia, monkeypatch):
    """`outcome=None` (sonda, plan, podgląd) zostaje w kolorze tekstu — neutralność też jest
    komunikatem, a pomalowanie planu na zielono obiecywałoby skutek, którego nie było."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "col2.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    dlg._show_report("Sonduję cel…")
    head = _block_fmt(dlg.report, 0)
    assert head.foreground().style() == Qt.NoBrush and head.fontWeight() == QFont.Normal
    con.close()


def test_use_theme_przelacza_kolory_naglowka():
    """Kolory nagłówka idą Z MOTYWU (SPOT), nie z literałów — jak `grid.use_theme`."""
    pd_mod.use_theme("light")
    assert pd_mod._COLORS["error"].name().lower() == theme.accents("light")["exclusion_red"].lower()
    pd_mod.use_theme(theme.DEFAULT)
    assert pd_mod._COLORS["error"].name().lower() == theme.accents("dark")["exclusion_red"].lower()


def test_zlota_akcja_ma_wage_wizualna(qapp, tmp_path, ustawienia, monkeypatch):
    """Wiz F3 #3: terminalna akcja dialogu odróżnia się od dwóch pomocniczych obok (bold + wysokość
    jak „Przyjmij nowe" Dostawy). Bez tego [Odśwież][Utwórz][Zamknij] czytało się jak trzy bliźniaki."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "gold.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    assert dlg.btn_apply.font().bold() and dlg.btn_apply.minimumHeight() == 34
    assert not dlg.btn_dry.font().bold()                  # pomocnicza zostaje pomocniczą
    con.close()


# --- P-C adjudykacja: nagłówek nie obiecuje czynności, której nie było (wizytacja #1/#4) ---

def test_report_head_key_powtorka_nie_glosi_utworzenia():
    """Wizytacja P-C #1: powtórne wydanie na ten sam cel dawało „Utworzono … zlinkowano: 0
    istniało: 4" — a nowy zielony akcent tę nieprawdę pogłaśniał. `linked == 0` bez anulowania to
    „Nic nowego", nie porażka: rola zostaje `ok`, zmienia się CZASOWNIK."""
    assert pd_mod.report_head_key(_Res({"linked": 4}), partial=False) == "proj.head_created"
    assert pd_mod.report_head_key(_Res({"linked": 0, "exists": 4}), partial=False) \
        == "proj.head_nothing_new"
    assert pd_mod.report_head_key(_Res({}), partial=False) == "proj.head_nothing_new"
    assert pd_mod.report_head_key(_Res({"linked": 0}, cancelled=True), partial=False) \
        == "proj.head_cancelled"
    assert pd_mod.report_head_key(_Res({"linked": 2}), partial=True) == "proj.head_partial"
    # Kolor i czasownik czytają JEDEN rozbiór — „nic nowego" pozostaje zielone.
    assert pd_mod.report_outcome(_Res({"linked": 0, "exists": 4}), partial=False) == "ok"


def test_dry_complete_nic_do_zrobienia_i_nic_zlego():
    """Komplet = zero do utworzenia, coś leży, zero konfliktów i błędów sondy. `skipped` kompletu
    nie psuje (tych klatek żadne wydanie nie położy), anulowana sonda nie jest werdyktem."""
    assert pd_mod.dry_complete(_Res({"exists": 3})) is True
    assert pd_mod.dry_complete(_Res({"exists": 3, "skipped": 1})) is True
    for zle in ({"exists": 3, "would-link": 1}, {"exists": 3, "conflict": 1},
                {"exists": 3, "error": 1}, {}, {"skipped": 2}):
        assert pd_mod.dry_complete(_Res(zle)) is False, zle
    assert pd_mod.dry_complete(_Res({"exists": 3}, cancelled=True)) is False


def test_powtorne_wydanie_mowi_nic_nowego(qapp, tmp_path, ustawienia, monkeypatch):
    """Pełna droga na PRAWDZIWYCH plikach: wydanie → świeży DRY → wydanie na ten sam cel."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "rep.db"))
    ids = _seed_files(con, tmp_path, 2)
    root = tmp_path / "_WBPP" / "feed"
    _target(ustawienia, root)
    dlg = _dlg(con, ids)
    dlg._on_apply()
    assert dlg.report.toPlainText().startswith("Utworzono")
    dlg._on_manual_dry()                                   # świeży DRY uzbraja „Utwórz" ponownie
    dlg._on_apply()
    rep = dlg.report.toPlainText()
    assert rep.startswith("Nic nowego") and "zlinkowano: 0" in rep and "istniało: 2" in rep
    assert dlg.btn_apply.text() == "Bez zmian ✓"
    con.close()


def test_dry_komplet_w_celu_mowi_naglowkiem(qapp, tmp_path, ustawienia, monkeypatch):
    """Sonda po wydaniu, która nie ma nic do zrobienia, mówi „Komplet już w celu" zamiast nagłówka
    „DRY" nad samymi zerami. Perspektywa gridu nie dostaje Eksploratora - to droga wydania obiektu."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "komplet.db"))
    ids = _seed_files(con, tmp_path, 2)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    assert dlg.report.toPlainText().startswith("DRY - bez zmian na dysku")
    dlg._on_apply()
    dlg._on_manual_dry()
    rep = dlg.report.toPlainText()
    assert rep.startswith("Komplet już w celu (układ po-obiektach, hardlinki):")
    assert "do zlinkowania: 0   istnieje: 2   konflikty: 0" in rep
    assert not dlg.btn_apply.isEnabled() and dlg.btn_open.isHidden()
    con.close()


def test_rozmiar_kopii_tylko_po_pozycjach_do_skopiowania(qapp, tmp_path, ustawienia, monkeypatch):
    """Rozmiar kopii to bajty, które wydanie naprawdę skopiuje: pozycja, której kopia z wydania już
    leży w celu (`copy2` - ten sam rozmiar, czas i treść), jest `exists` i do sumy nie wchodzi.
    Po całym planie suma obiecywała przy ponownym wydaniu gigabajty plików, które już są."""
    import shutil

    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "INNY")
    con = db.open_db(str(tmp_path / "rozmiar.db"))
    ids = _seed_files(con, tmp_path, 2, sizes=[100, 50])
    root = tmp_path / "_WBPP" / "kopie"
    juz = root / "_UNSET" / "_UNSET" / "raw0.fits"
    juz.parent.mkdir(parents=True)
    shutil.copy2(str(tmp_path / "lib" / "raw0.fits"), str(juz))   # kopia z poprzedniego wydania
    _target(ustawienia, root)
    dlg = _dlg(con, ids)
    rep = dlg.report.toPlainText()
    assert "do skopiowania: 1   istnieje: 1   konflikty: 0" in rep
    assert "rozmiar kopii: 50 B" in rep                    # po całym planie byłoby 150 B
    assert dlg.btn_apply.text() == "Utwórz 1 kopię"
    con.close()


def test_wydanie_zostawia_slad_po_zamknieciu(qapp, tmp_path, ustawienia, monkeypatch):
    """Wizytacja P-C #4: po `exec()` okno główne nie niosło ANI SŁOWA o wydaniu — jedynym trwałym
    zapisem był `_PROJEKCJA.json` w celu, czyli poza aplikacją. Zdanie składa dialog (tam liczby
    są świeże), `grid` je tylko przekazuje na statusbar."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "slad.db"))
    ids = _seed_files(con, tmp_path, 2)
    root = tmp_path / "_WBPP" / "feed"
    _target(ustawienia, root)
    dlg = _dlg(con, ids)
    assert dlg.summary is None                             # przed wydaniem nie ma czego głosić
    dlg._on_apply()
    assert dlg.summary and "2" in dlg.summary and "zlinkowano" in dlg.summary
    assert str(root) in dlg.summary
    con.close()


# ============================================================ wydanie obiektu (tryb obiektu + teczki)

def _obiekt_wydania(tmp_path):
    """Baza z PRAWDZIWYMI plikami pod wydanie obiektu. NGC 6992 w dwóch zestawach: A (A140R x mono,
    config 10) - light z master flatem i darkiem, light OIII z surowymi flatami tej samej nocy,
    light Ha `pending` (master jest, stanu nie ma), light SII bez profilu flatu, light Ha bez
    obecnej kopii; B (RC8 x mono, config 20) - light z master flatem B i TYM SAMYM master darkiem
    (master wspólny dwóch zestawów = dwie pozycje planu). M42: jeden light SII bez niczego (red).
    IC1795: jeden light z kompletem (green). Zwraca (con, ids)."""
    from horreum.calibration import run_calibration

    con = db.open_db(str(tmp_path / "obj.db"))
    con.execute("INSERT INTO camera (id, model_canon, is_mono, created_at) VALUES "
                "(1, 'ASI2600MM', 1, ?)", (NOW,))
    con.execute("INSERT INTO telescope (id, telescop_canon, label, status, created_at) VALUES "
                "(1, 'A140R', NULL, 'proposed', ?), (2, 'RC8', NULL, 'proposed', ?)", (NOW, NOW))
    con.execute("INSERT INTO config (id, telescope_id, camera_id, status, created_at) VALUES "
                "(10, 1, 1, 'proposed', ?), (20, 2, 1, 'proposed', ?)", (NOW, NOW))
    con.execute("INSERT INTO object (id, canon) VALUES (1, 'NGC 6992'), (2, 'M42'), (3, 'IC1795')")
    ids = {}

    def k(name, *, kind, config_id=10, object_id=None, filtr=None, exptime=300.0, present=True,
          date_obs="2024-03-01T23:00:00"):
        src = tmp_path / "lib" / f"{name}.fits"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(name.encode())
        cur = con.execute(
            "INSERT INTO frame (sha1_data, kind, filetype, camera_id, config_id, object_id, "
            "filter_canon, first_seen_at) VALUES (?, ?, 'fits', 1, ?, ?, ?, ?)",
            (name, kind, config_id, object_id, filtr, NOW))
        fid = cur.lastrowid
        con.execute("INSERT INTO header (frame_id, raw_json, date_obs, exptime, xbinning) "
                    "VALUES (?, '{}', ?, ?, 1)", (fid, date_obs, exptime))
        con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', ?, ?)",
                    (fid, str(src), int(present)))
        ids[name] = fid

    k("md", kind="master_dark", config_id=None)
    k("mf_a", kind="master_flat", filtr="Ha")
    k("mf_b", kind="master_flat", config_id=20, filtr="Ha")
    k("f1", kind="flat", filtr="OIII", date_obs="2024-03-02T05:30:00")
    k("f2", kind="flat", filtr="OIII", date_obs="2024-03-02T05:31:00")
    k("la1", kind="light", object_id=1, filtr="Ha")
    k("la2", kind="light", object_id=1, filtr="OIII")
    k("la3", kind="light", object_id=1, filtr="Ha")
    k("la4", kind="light", object_id=1, filtr="SII")
    k("la_gone", kind="light", object_id=1, filtr="Ha", present=False)
    k("lb1", kind="light", config_id=20, object_id=1, filtr="Ha")
    k("lm1", kind="light", object_id=2, filtr="SII")
    k("lg1", kind="light", config_id=20, object_id=3, filtr="Ha", exptime=3600.0)
    con.commit()
    run_calibration(con, now=NOW)                         # profile: surowe OIII, mastery Ha
    for light, master, rel in (("la1", "mf_a", "flat"), ("la1", "md", "dark"),
                               ("la_gone", "mf_a", "flat"), ("lb1", "mf_b", "flat"),
                               ("lb1", "md", "dark"), ("lg1", "mf_b", "flat"), ("lg1", "md", "dark")):
        con.execute("INSERT INTO calibration (light_frame_id, master_frame_id, relation, asserted_by, "
                    "confidence) VALUES (?, ?, ?, 'horreum', 'recipe')", (ids[light], ids[master], rel))
    con.commit()
    return con, ids


def _dlg_obj(con, object_id=1):
    return ProjectionDialog(con, object_id=object_id, now_fn=lambda: NOW, off_thread=False)


class _Pulpit:
    """Podmiana `QDesktopServices` - test nie otwiera Eksploratora na pulpicie, tylko zapisuje URL."""

    def __init__(self):
        self.urls = []

    def openUrl(self, url):                                # noqa: N802 - nazwa z API Qt
        self.urls.append(url)
        return True


def test_tryb_obiektu_jedno_z_dwojga_i_nieznany_obiekt(qapp, tmp_path):
    """Konstruktor przyjmuje `frame_ids` ALBO `object_id` - oba albo żadne to błąd wołającego,
    nie tryb do zgadywania; nieznany obiekt też (nagłówek nie ma czego nazwać)."""
    con, ids = _obiekt_wydania(tmp_path)
    with pytest.raises(ValueError, match="ALBO"):
        ProjectionDialog(con, [ids["la1"]], object_id=1, now_fn=lambda: NOW, off_thread=False)
    with pytest.raises(ValueError, match="ALBO"):
        ProjectionDialog(con, now_fn=lambda: NOW, off_thread=False)
    with pytest.raises(ValueError, match="nieznany obiekt"):
        ProjectionDialog(con, object_id=999, now_fn=lambda: NOW, off_thread=False)
    con.close()


def test_tryb_obiektu_dry_naglowek_apply_manifest_eksplorator(qapp, tmp_path, ustawienia, monkeypatch):
    """Pełna droga trybu obiektu na PRAWDZIWYCH plikach: DRY liczy POZYCJE planu (lighty + mastery
    + surowe; master dark wspólny dwóch zestawów dwa razy), nagłówek nazywa liczby archiwum
    (mastery DISTINCT), `pending` stoi osobno, combo układu schowane, combo zestawu ma pozycje
    z liczbą lightów. Apply idzie do `<karta>/OBJECTS/<obiekt>` (`object_root`), manifest = `info` +
    etykieta, a „Otwórz w Eksploratorze" otwiera dokładnie ten folder."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    pulpit = _Pulpit()
    monkeypatch.setattr(pd_mod, "QDesktopServices", pulpit)
    con, ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    _target(ustawienia, card)
    dlg = _dlg_obj(con)
    assert dlg.windowTitle() == "Wydaj obiekt do WBPP"
    rep = dlg.report.toPlainText()
    assert "do zlinkowania: 11" in rep and "pominięto: 1" in rep
    assert dlg.btn_apply.text() == "Utwórz 11 linków"
    pozycje = [it.frame_id for it in dlg._plan.items]
    assert pozycje.count(ids["md"]) == 2                   # master wspólny: pozycja w KAŻDYM zestawie
    assert {ids["mf_a"], ids["mf_b"], ids["f1"], ids["f2"]} <= set(pozycje)
    assert dlg.head_label.text() == ("NGC 6992: 6 lightów · 3 mastery · 2 surowe flaty · "
                                     "bez flatu 1 · bez darka 4")
    assert not dlg.pending_label.isHidden()
    assert dlg.pending_label.text() == "do przeliczenia w Dostawie: 1"
    # raport: powód „bez flatu" przy liczbie, `pending` osobną linią ze swoim zdaniem
    assert "bez flatu: 1 - brak w archiwum flatów tej nastawy: 1" in rep
    assert "do przeliczenia w Dostawie: 1 - master jest, rodowód go nie przeliczył" in rep
    assert "A140R_ASI2600MM/FLAT_RAW/OIII: 2" in rep
    assert dlg.combo_layout.isHidden()
    assert [dlg.combo_zestaw.itemText(i) for i in range(dlg.combo_zestaw.count())] == [
        "Wszystkie", "A140R_ASI2600MM (5 lightów)", "RC8_ASI2600MM (1 light)"]
    assert dlg.btn_open.isHidden()                         # przed wydaniem nie ma czego otwierać

    dlg._on_apply()
    obj_root = card / "OBJECTS" / "NGC_6992"
    assert projection.object_root(str(card), dlg._plan) == str(obj_root)
    assert "zlinkowano: 11" in dlg.report.toPlainText()
    light = obj_root / "A140R_ASI2600MM" / "LIGHT" / "Ha" / "la1.fits"
    assert os.stat(str(light)).st_ino == os.stat(str(tmp_path / "lib" / "la1.fits")).st_ino
    for zestaw in ("A140R_ASI2600MM", "RC8_ASI2600MM"):
        assert (obj_root / zestaw / "MASTER" / "dark" / "md.fits").exists()
    assert (obj_root / "A140R_ASI2600MM" / "FLAT_RAW" / "OIII" / "f2.fits").exists()
    man = json.loads((obj_root / projection.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert man["layout"] == "wbpp-obiekt" and man["object_id"] == 1
    assert man["etykieta"] == "NGC 6992"
    assert set(man["zestawy"]) == {"A140R_ASI2600MM", "RC8_ASI2600MM"}
    assert man["zestawy"]["A140R_ASI2600MM"]["pending"] == [ids["la3"]]
    assert dlg.summary == f"Wydano obiekt NGC 6992: 11 zlinkowano → {obj_root}"
    assert ustawienia.value("projection/last_target") == str(card)   # pamięć = KARTA, nie folder obiektu

    assert not dlg.btn_open.isHidden()
    QTest.mouseClick(dlg.btn_open, Qt.LeftButton)
    assert [os.path.normpath(u.toLocalFile()) for u in pulpit.urls] == [str(obj_root)]
    con.close()


def test_tryb_obiektu_combo_zestawu_zaweza_i_blokuje_sie_w_biegu(qapp, tmp_path, ustawienia,
                                                                   monkeypatch):
    """Zmiana zestawu = `_invalidate` + auto-DRY pod NOWE parametry (generacja w górę, plan
    zawężony, nagłówek z NAZWĄ i liczbami zestawu, lista zestawów NIE kurczy się do jednego). W biegu
    apply combo zestawu jest zamrożone jak układ - inaczej klik zerowałby materializowany plan."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    _target(ustawienia, card)
    dlg = _dlg_obj(con)
    gen0 = dlg._gen
    dlg.combo_zestaw.setCurrentIndex(2)                    # RC8_ASI2600MM (config 20)
    assert dlg._gen > gen0
    assert dlg._plan.info["config_id"] == 20 and list(dlg._plan.info["zestawy"]) == ["RC8_ASI2600MM"]
    assert {it.frame_id for it in dlg._plan.items} == {ids["lb1"], ids["md"], ids["mf_b"]}
    assert dlg.btn_apply.text() == "Utwórz 3 linki"
    assert dlg.head_label.text() == ("NGC 6992 / RC8_ASI2600MM: 1 light · 2 mastery · "
                                     "0 surowych flatów · bez flatu 0 · bez darka 0")
    assert dlg.pending_label.isHidden()                    # zero do przeliczenia → linia znika
    assert dlg.combo_zestaw.count() == 3
    frozen = []
    _spy_progress(monkeypatch, hook=lambda n, w: frozen.append(dlg.combo_zestaw.isEnabled()))
    dlg._on_apply()
    assert frozen and not any(frozen)
    assert dlg.combo_zestaw.isEnabled()
    man = json.loads((card / "OBJECTS" / "NGC_6992" / projection.MANIFEST_NAME)
                     .read_text(encoding="utf-8"))
    assert man["etykieta"] == "NGC 6992 / RC8_ASI2600MM" and man["config_id"] == 20
    con.close()


def test_tryb_obiektu_wolumen_i_rozmiar_z_pozycji_planu(qapp, tmp_path, ustawienia, monkeypatch):
    """Decyzja hardlink/kopia i rozmiar kopii biorą klatki z POZYCJI planu, nie z perspektywy:
    master na innym wolumenie przełącza CAŁOŚĆ na kopię, choć żaden light tam nie leży, a master
    wspólny dwóch zestawów liczy się do rozmiaru dwa razy (dwie kopie na dysku)."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, ids = _obiekt_wydania(tmp_path)
    con.execute("UPDATE location SET size_bytes = 100")
    con.execute("UPDATE location SET volume = 'X' WHERE frame_id = ?", (ids["md"],))
    con.commit()
    _target(ustawienia, tmp_path / "_WBPP" / "karta")
    dlg = _dlg_obj(con)
    rep = dlg.report.toPlainText()
    assert "do skopiowania: 11" in rep
    assert "rozmiar kopii: 1.1 KB" in rep                  # 11 pozycji × 100 B; po klatkach byłoby 1000 B
    assert dlg.btn_apply.text() == "Utwórz 11 kopii"
    con.close()


def test_tryb_obiektu_anulowane_wydanie_nie_otwiera_eksploratora(qapp, tmp_path, ustawienia,
                                                                 monkeypatch):
    """„Otwórz w Eksploratorze" pojawia się po UDANYM wydaniu - przerwane zostawia raport
    „Przerwano" i liczbę nietkniętych, a nie zaproszenie do folderu z połową drzewa. Zdanie na
    statusbar (jedyny ślad po zamknięciu okna) też mówi „Przerwano", nie „Wydano"."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    _target(ustawienia, card)
    _spy_progress(monkeypatch, hook=lambda n, w: w.request_cancel() if n == 1 else None)
    dlg = _dlg_obj(con)
    dlg._on_apply()
    assert dlg.report.toPlainText().startswith("Przerwano")
    assert dlg.btn_open.isHidden()
    assert dlg.summary == ("Przerwano wydanie obiektu NGC 6992: zlinkowano 1 z 11, reszta nietknięta "
                           f"→ {card / 'OBJECTS' / 'NGC_6992'}")
    con.close()


@pytest.mark.parametrize("serial, tryb", [("INNY", "kopie"), ("V", "hardlinki")])
def test_tryb_obiektu_powrot_do_kompletu_od_razu_eksplorator(qapp, tmp_path, ustawienia, monkeypatch,
                                                             serial, tryb):
    """Powrót do wydanego obiektu (nowe okno, ta sama karta): sonda zastaje komplet - kopie z wydania
    są `exists`, nie konfliktami - więc nagłówek mówi „Komplet już w celu", rozmiar kopii nie liczy
    plików, które leżą, a „Otwórz w Eksploratorze" jest od razu i otwiera folder obiektu."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: serial)
    pulpit = _Pulpit()
    monkeypatch.setattr(pd_mod, "QDesktopServices", pulpit)
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    _target(ustawienia, card)
    pierwsze = _dlg_obj(con)
    pierwsze._on_apply()
    assert pierwsze.report.toPlainText().startswith("Utworzono")

    powrot = _dlg_obj(con)
    rep = powrot.report.toPlainText()
    assert rep.startswith(f"Komplet już w celu (układ wbpp-obiekt, {tryb}):")
    assert "0   istnieje: 11   konflikty: 0   pominięto: 1" in rep
    assert "bez rozmiaru" not in rep                       # zero pozycji do skopiowania - zero niewiadomych
    assert not powrot.btn_apply.isEnabled()
    assert not powrot.btn_open.isHidden()
    QTest.mouseClick(powrot.btn_open, Qt.LeftButton)
    assert [os.path.normpath(u.toLocalFile()) for u in pulpit.urls] == [
        str(card / "OBJECTS" / "NGC_6992")]
    con.close()


def test_tryb_obiektu_eksplorator_zyje_tylko_przy_swoich_parametrach(qapp, tmp_path, ustawienia,
                                                                     monkeypatch):
    """„Otwórz w Eksploratorze" należy do parametrów, przy których go uzbrojono. Wydanie niczego nie
    unieważnia, więc zaraz po nim przycisk stoi i otwiera właśnie wydany folder. Przejście na kartę
    B („do zlinkowania: 11") gasi go - inaczej otwierałby folder z karty A; powrót na A zastaje
    komplet i uzbraja go znowu; padnięta sonda (karta bez segmentu wykluczonego) gasi go także
    sama, bez pomocy zmiany parametru."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    pulpit = _Pulpit()
    monkeypatch.setattr(pd_mod, "QDesktopServices", pulpit)
    con, _ids = _obiekt_wydania(tmp_path)
    karta_a, karta_b = tmp_path / "_WBPP" / "a", tmp_path / "_WBPP" / "b"
    zla = tmp_path / "poza_wykluczeniem"
    ustawienia.setValue("projection/targets", json.dumps(
        [{"name": n, "path": str(p)} for n, p in (("a", karta_a), ("b", karta_b), ("zla", zla))]))
    ustawienia.setValue("projection/last_target", str(karta_a))
    dlg = _dlg_obj(con)
    radio = {c["path"]: c["radio"] for c in dlg._cards}
    assert dlg.btn_open.isHidden()

    dlg._on_apply()
    assert not dlg.btn_open.isHidden()                     # zaraz po wydaniu - bez regresji
    QTest.mouseClick(dlg.btn_open, Qt.LeftButton)
    assert [os.path.normpath(u.toLocalFile()) for u in pulpit.urls] == [
        str(karta_a / "OBJECTS" / "NGC_6992")]

    radio[str(karta_b)].setChecked(True)
    assert "do zlinkowania: 11" in dlg.report.toPlainText()
    assert dlg.btn_open.isHidden() and dlg._released_root is None

    radio[str(karta_a)].setChecked(True)
    assert dlg.report.toPlainText().startswith("Komplet już w celu")
    assert not dlg.btn_open.isHidden()

    radio[str(zla)].setChecked(True)
    assert dlg.report.toPlainText().startswith("Nie można")
    assert dlg.btn_open.isHidden()

    radio[str(karta_a)].setChecked(True)
    assert not dlg.btn_open.isHidden()
    dlg._on_dry_failed(dlg._gen, "OSError: cel odpięty")   # sonda bieżących parametrów padła
    assert dlg.btn_open.isHidden() and dlg._released_root is None
    con.close()


def test_tryb_obiektu_zmiana_zestawu_po_wydaniu_gasi_eksplorator(qapp, tmp_path, ustawienia,
                                                                 monkeypatch):
    """Po wydaniu jednego zestawu zmiana zestawu gasi „Otwórz w Eksploratorze" już na czas nowej
    sondy (podgląd z wnętrza workera). Wraca wyłącznie wtedy, gdy nowa sonda sama zastanie
    komplet: „Wszystkie" mają w celu tylko wydany zestaw, więc przycisk zostaje zgaszony; powrót
    na wydany zestaw zastaje komplet i uzbraja go znowu."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    _target(ustawienia, tmp_path / "_WBPP" / "karta")
    dlg = _dlg_obj(con)
    dlg.combo_zestaw.setCurrentIndex(2)                    # RC8_ASI2600MM
    dlg._on_apply()
    assert not dlg.btn_open.isHidden()
    w_biegu = []

    class Szpieg(pd_mod.DryWorker):
        def run(self):
            w_biegu.append(dlg.btn_open.isHidden())
            super().run()

    monkeypatch.setattr(pd_mod, "DryWorker", Szpieg)
    dlg.combo_zestaw.setCurrentIndex(0)                    # Wszystkie: A140R nie leży w celu
    assert "do zlinkowania: 8   istnieje: 3" in dlg.report.toPlainText()
    assert dlg.btn_open.isHidden()
    dlg.combo_zestaw.setCurrentIndex(2)                    # z powrotem wydany zestaw
    assert dlg.report.toPlainText().startswith("Komplet już w celu")
    assert not dlg.btn_open.isHidden()
    assert w_biegu == [True, True]                         # w biegu każdej sondy - zgaszony
    con.close()


def test_tryb_obiektu_combo_zestawu_szerokosc_za_trescia(qapp, tmp_path, ustawienia, monkeypatch):
    """Pozycje zestawów dochodzą z pierwszego planu - w biegu na żywo już PO pokazaniu okna (sonda
    w wątku tła). Szerokość ustalona przy pierwszym pokazaniu na „Wszystkie" ucinała nazwy zestawów;
    combo ma rosnąć za treścią. Okno pokazane bez celu, cel dodany potem = ta sama kolejność."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    dlg = _dlg_obj(con)                                    # bez celu: tylko „Wszystkie"
    combo = dlg.combo_zestaw
    assert combo.count() == 1
    dlg.show()
    qapp.processEvents()
    przed = combo.width()
    assert dlg._add_target_path(str(tmp_path / "_WBPP" / "karta"), "karta")   # → auto-DRY → zestawy
    qapp.processEvents()
    fm = combo.fontMetrics()
    najdluzsza = max((combo.itemText(i) for i in range(combo.count())), key=fm.horizontalAdvance)
    assert najdluzsza == "A140R_ASI2600MM (5 lightów)"
    assert combo.width() > przed
    assert combo.width() >= fm.horizontalAdvance(najdluzsza)
    dlg.close()
    con.close()


def test_tryb_obiektu_naglowek_nie_klamie_w_biegu_nowej_sondy(qapp, tmp_path, ustawienia,
                                                               monkeypatch):
    """Zmiana zestawu unieważnia plan, więc nagłówek przez CAŁY bieg nowej sondy pokazuje samą
    nazwę obiektu - liczby poprzedniego zestawu wracają dopiero z przyjętym DRY, już nowe.
    Podgląd tekstu w chwili startu workera (podklasa `DryWorker`) - tryb inline kończy sondę
    synchronicznie, więc stan „w biegu" widać tylko od środka. Falsyfikator: zdejmij
    `_show_object_head(None)` z `_invalidate` → w biegu widać „6 lightów"."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    _target(ustawienia, tmp_path / "_WBPP" / "karta")
    dlg = _dlg_obj(con)
    assert dlg.head_label.text().startswith("NGC 6992: 6 lightów")
    assert not dlg.pending_label.isHidden()
    w_biegu = []

    class Szpieg(pd_mod.DryWorker):
        def run(self):
            w_biegu.append((dlg.head_label.text(), dlg.pending_label.isHidden()))
            super().run()

    monkeypatch.setattr(pd_mod, "DryWorker", Szpieg)
    dlg.combo_zestaw.setCurrentIndex(2)                    # RC8_ASI2600MM
    assert w_biegu == [("NGC 6992", True)]
    assert dlg.head_label.text().startswith("NGC 6992 / RC8_ASI2600MM: 1 light")   # przyjęty DRY
    con.close()


def test_tryb_perspektywy_bez_elementow_obiektu(qapp, tmp_path, ustawienia, monkeypatch):
    """Tryb perspektywy („Wydaj na stół…") bez zmian: układ widoczny, zestawu nie ma, Eksploratora
    nie ma także po wydaniu, payload DRY niesie korzeń karty."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "persp.db"))
    ids = _seed_files(con, tmp_path, 2)
    root = tmp_path / "_WBPP" / "feed"
    _target(ustawienia, root)
    dlg = _dlg(con, ids)
    assert dlg.combo_zestaw is None and not dlg.combo_layout.isHidden()
    assert dlg._dry["root"] == str(root)
    dlg._on_apply()
    assert dlg.btn_open.isHidden()
    con.close()


# ---------- okno teczek (`ObjectPickDialog`) ----------

def _wiersz(pick, canon):
    return next(i for i, r in enumerate(pick._rows) if r["canon"] == canon)


def _dwuklik(pick, canon):
    """Fizyczny dwuklik w komórkę teczki: najpierw klik, potem zdarzenie podwójne - tak dociera on
    od systemu. Sam `mouseDClick` nie ustawia `pressedIndex` widoku i `QAbstractItemView` traktuje
    go jak zwykłe wciśnięcie (sygnał `doubleClicked` nie pada)."""
    rect = pick.table.visualItemRect(pick.table.item(_wiersz(pick, canon), 1))
    QTest.mouseClick(pick.table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    QTest.mouseDClick(pick.table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())


def test_teczki_kolejnosc_kropka_z_motywu_i_kolumny(qapp, tmp_path):
    """Teczki godzinami malejąco, kropka stanu w kolorze Z MOTYWU (rola ok/warn/error, nie literał)
    z powodem pod kursorem, procenty flatu `master / surowy`, `pending` nazwany osobno. Bez
    preselekcji „Dalej" jest szczerze wygaszony."""
    con, _ids = _obiekt_wydania(tmp_path)
    pick = pd_mod.ObjectPickDialog(con)
    assert [r["canon"] for r in pick._rows] == ["IC1795", "NGC 6992", "M42"]
    akcent = theme.accents(theme.DEFAULT)
    for canon, kolor in (("IC1795", "ok_green"), ("NGC 6992", "warn"), ("M42", "exclusion_red")):
        dot = pick.table.item(_wiersz(pick, canon), 0)
        assert dot.foreground().color().name().lower() == akcent[kolor].lower(), canon
    assert pick.table.item(0, 0).toolTip().startswith("komplet")
    ngc = _wiersz(pick, "NGC 6992")
    cells = [pick.table.item(ngc, c).text() for c in range(1, pick.table.columnCount())]
    # flat: la1, la_gone, lb1 z masterem (3/6), la2 z surowymi (1/6 → 16), la3 `pending` (1/6)
    assert cells == ["NGC 6992", "0.5", "6", "1", "2",
                     "50 % / 16 % · do przeliczenia w Dostawie: 16 %", "33 %", "2024-03-01"]
    assert pick.table.selectionModel().selectedRows() == []
    assert not pick.btn_next.isEnabled()
    con.close()


def test_teczki_szukaj_preselekcja_dwuklik_i_enter(qapp, tmp_path):
    """Pole „Szukaj" zawęża i zaznacza pierwszą pasującą teczkę; preselekcja zaznacza teczkę
    obiektu ze zbioru; dwuklik i Enter (prawdziwy klawisz przy tabeli) wybierają obiekt i zamykają
    okno. Reguła szukania (aliasy, separatory, oznaczenie katalogowe) - test niżej."""
    con, _ids = _obiekt_wydania(tmp_path)
    pick = pd_mod.ObjectPickDialog(con, preselect=2)
    assert pick._selected_row() == _wiersz(pick, "M42") and pick.btn_next.isEnabled()
    pick.search.setText("6992")
    widoczne = [r["canon"] for i, r in enumerate(pick._rows) if not pick.table.isRowHidden(i)]
    assert widoczne == ["NGC 6992"]
    assert pick._selected_row() == _wiersz(pick, "NGC 6992")   # M42 wypadł z widoku
    pick.search.setText("zzz")
    assert pick._selected_row() is None and not pick.btn_next.isEnabled()

    pick.search.setText("")
    pick.show()
    qapp.processEvents()
    _dwuklik(pick, "IC1795")
    assert pick.result() == QDialog.Accepted and pick.object_id == 3

    enter = pd_mod.ObjectPickDialog(con, preselect=1)
    enter.show()
    qapp.processEvents()
    QTest.keyClick(enter.table, Qt.Key_Return)
    assert enter.result() == QDialog.Accepted and enter.object_id == 1
    con.close()


def _teczki_do_szukania(tmp_path):
    """Teczki pod regułę szukania: kanony zapisane jak w archiwum (`Sh2-131`, `NGC4258`, `NGC6992`)
    i `IC1795` z aliasem ręki „Heart of the Soul" (`object_alias.alias_norm`). Po jednym lighcie,
    godziny malejąco w kolejności wstawiania - kolejność teczek jest stała."""
    con = db.open_db(str(tmp_path / "szukaj.db"))
    con.execute("INSERT INTO object (id, canon) VALUES "
                "(1, 'Sh2-131'), (2, 'NGC4258'), (3, 'IC1795'), (4, 'NGC6992')")
    con.execute("INSERT INTO object_alias (alias_norm, object_id, source) "
                "VALUES ('HEARTOFTHESOUL', 3, 'user')")
    for oid in (1, 2, 3, 4):
        cur = con.execute("INSERT INTO frame (sha1_data, kind, filetype, object_id, first_seen_at) "
                          "VALUES (?, 'light', 'fits', ?, ?)", (f"s{oid}", oid, NOW))
        con.execute("INSERT INTO header (frame_id, raw_json, date_obs, exptime) "
                    "VALUES (?, '{}', '2024-03-01T23:00:00', ?)", (cur.lastrowid, 3600.0 * (5 - oid)))
    con.commit()
    return con


def _widoczne(pick):
    return [r["canon"] for i, r in enumerate(pick._rows) if not pick.table.isRowHidden(i)]


def test_teczki_szukaj_regula_facetu_aliasy_separatory(qapp, tmp_path):
    """Pole „Szukaj" to reguła szukajki facetu Obiekt (`facet_model.search_hit` z aliasami), nie
    własny klucz okna: separatory nie przeszkadzają, oznaczenie katalogowe trafia swój obiekt także
    przez drugą nazwę (`m106` → `NGC4258`), nazwa potoczna - przez alias ręki. Fraza niekatalogowa
    zawęża podciągiem, pusta pokazuje wszystko; zaznaczenie idzie za pierwszą trafioną teczką."""
    con = _teczki_do_szukania(tmp_path)
    pick = pd_mod.ObjectPickDialog(con)
    assert _widoczne(pick) == ["Sh2-131", "NGC4258", "IC1795", "NGC6992"]
    for fraza, oczek in (("sh2 131", ["Sh2-131"]), ("sh2131", ["Sh2-131"]), ("SH2-131", ["Sh2-131"]),
                         ("m106", ["NGC4258"]), ("m 106", ["NGC4258"]),
                         ("heart of the soul", ["IC1795"]), ("Heart-of-the-Soul", ["IC1795"]),
                         ("ngc", ["NGC4258", "NGC6992"]), ("", ["Sh2-131", "NGC4258", "IC1795",
                                                                "NGC6992"])):
        pick.search.setText(fraza)
        assert _widoczne(pick) == oczek, fraza
    pick.search.setText("heart of the soul")
    assert pick._selected_row() == _wiersz(pick, "IC1795") and pick.btn_next.isEnabled()
    con.close()


def test_teczki_wpisywanie_po_literze_nie_gubi_teczki(qapp, tmp_path):
    """Pole filtruje po każdej literze, a niedokończone oznaczenie (`sh2`, `sh2 13`, `ngc69`)
    `catalog_canon` czyta jako pełne innego obiektu. Na żadnym etapie wpisywania prawdziwymi
    klawiszami teczka, do której nazwa zmierza, nie znika, a zdanie „Brak teczek…" się nie
    pojawia - pusty wynik w połowie nazwy kazałby userowi szukać inaczej czegoś, co istnieje."""
    con = _teczki_do_szukania(tmp_path)
    pick = pd_mod.ObjectPickDialog(con)
    pick.show()
    pick.activateWindow()
    qapp.processEvents()
    assert pick.search.hasFocus()
    for fraza, cel in (("sh2 131", "Sh2-131"), ("ngc6992", "NGC6992"), ("ngc 4258", "NGC4258")):
        pick.search.clear()
        for litera in fraza:
            QTest.keyClicks(pick.focusWidget(), litera)
            napisane = pick.search.text()
            if not napisane.strip():
                continue
            assert cel in _widoczne(pick), napisane
            assert pick.empty_label.isHidden(), napisane
        assert _widoczne(pick) == [cel] and pick._selected_row() == _wiersz(pick, cel)
    con.close()


def test_teczki_strzalki_w_polu_przesuwaja_zaznaczenie(qapp, tmp_path):
    """Up/Down w polu z fokusem (prawdziwe klawisze) przesuwają zaznaczenie po WIDOCZNYCH teczkach
    i stają na krańcach; fokus i fraza zostają w polu, a Enter wybiera przesuniętą teczkę. Droga:
    pisz → strzałka → Enter, bez sięgania po mysz, gdy trafień jest więcej niż jedno."""
    con = _teczki_do_szukania(tmp_path)
    pick = pd_mod.ObjectPickDialog(con)
    pick.show()
    pick.activateWindow()
    qapp.processEvents()
    assert pick.focusWidget() is pick.search and pick.search.hasFocus()
    pole = pick.focusWidget()
    QTest.keyClicks(pole, "ngc")
    assert _widoczne(pick) == ["NGC4258", "NGC6992"]
    assert pick._selected_row() == _wiersz(pick, "NGC4258")
    QTest.keyClick(pole, Qt.Key_Down)
    assert pick._selected_row() == _wiersz(pick, "NGC6992")   # ukryte IC1795 pominięte
    QTest.keyClick(pole, Qt.Key_Down)
    assert pick._selected_row() == _wiersz(pick, "NGC6992")   # kraniec - zostaje
    QTest.keyClick(pole, Qt.Key_Up)
    assert pick._selected_row() == _wiersz(pick, "NGC4258")
    QTest.keyClick(pole, Qt.Key_Up)
    assert pick._selected_row() == _wiersz(pick, "NGC4258")
    assert pick.search.hasFocus() and pick.search.text() == "ngc"
    QTest.keyClick(pole, Qt.Key_Down)
    QTest.keyClick(pole, Qt.Key_Return)
    assert pick.result() == QDialog.Accepted and pick.object_id == 4
    con.close()


def test_teczki_stan_pusty_dwa_zdania(qapp, tmp_path):
    """Fraza bez trafień ma zdanie z frazą zamiast gołej tabeli, a „Dalej" gaśnie; pusta baza ma
    INNE zdanie - także gdy ktoś coś wpisał, bo prawdą jest brak teczek, nie za wąska fraza."""
    con = _teczki_do_szukania(tmp_path)
    pick = pd_mod.ObjectPickDialog(con)
    assert pick.empty_label.isHidden()
    pick.search.setText("zzz")
    assert not pick.empty_label.isHidden()
    assert pick.empty_label.text() == "Brak teczek dla „zzz”"
    assert pick._selected_row() is None and not pick.btn_next.isEnabled()
    pick.search.setText("")
    assert pick.empty_label.isHidden() and pick.btn_next.isEnabled()
    con.close()

    pusta = db.open_db(str(tmp_path / "pusta.db"))
    nic = pd_mod.ObjectPickDialog(pusta)
    assert not nic.empty_label.isHidden()
    assert nic.empty_label.text() == "Brak obiektów z lightami w bazie."
    nic.search.setText("m42")
    assert nic.empty_label.text() == "Brak obiektów z lightami w bazie."
    pusta.close()


def test_przycisk_paska_droga_trzech_interakcji(qapp, tmp_path, ustawienia, monkeypatch):
    """Droga z briefu: klik „Wydaj obiekt…" → dwuklik teczki → „Utwórz N linków" = 3 interakcje,
    na PRAWDZIWYM `QThread` (domyślny tryb FramesView). Teczka obiektu ze zbioru gridu jest
    zaznaczona na starcie, a wydanie zostawia zdanie na statusbarze. `exec()` podmieniony tak,
    żeby wykonać REALNE kliknięcia zamiast czekać na rękę."""
    from horreum.gui.grid import FramesView

    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    _target(ustawienia, card)
    view = FramesView(con, now_fn=lambda: NOW)
    assert _wait_until(lambda: not view._zbior_w_drodze())
    view._frame_ids = [ids["la1"], ids["la2"], ids["f1"]]   # zbiór: lighty jednego obiektu
    msgs, kliki, widziane = [], [], {}
    view.status_message.connect(msgs.append)

    def pick_exec(self):
        self.show()
        qapp.processEvents()
        widziane["preselekcja"] = self._rows[self._selected_row()]["canon"]
        _dwuklik(self, "NGC 6992")
        kliki.append("dwuklik teczki")
        return self.result()

    def proj_exec(self):
        self.show()
        assert _wait_until(lambda: self.btn_apply.isEnabled())
        widziane["przycisk"] = self.btn_apply.text()
        QTest.mouseClick(self.btn_apply, Qt.LeftButton)
        kliki.append("utwórz")
        assert _wait_until(lambda: self._apply_worker is None and self._apply_thread is None)
        return 0

    monkeypatch.setattr(pd_mod.ObjectPickDialog, "exec", pick_exec)
    monkeypatch.setattr(pd_mod.ProjectionDialog, "exec", proj_exec)
    view.show()
    qapp.processEvents()
    assert view.sel_bar.btn_obj.isEnabled() and view.sel_bar.btn_obj.text() == "Wydaj obiekt…"
    QTest.mouseClick(view.sel_bar.btn_obj, Qt.LeftButton)
    kliki.insert(0, "Wydaj obiekt…")
    assert kliki == ["Wydaj obiekt…", "dwuklik teczki", "utwórz"]
    assert widziane == {"preselekcja": "NGC 6992", "przycisk": "Utwórz 11 linków"}
    assert (card / "OBJECTS" / "NGC_6992" / "RC8_ASI2600MM" / "LIGHT" / "Ha" / "lb1.fits").exists()
    assert any(m.startswith("Wydano obiekt NGC 6992: 11") for m in msgs)
    view.close()
    con.close()


def test_przycisk_paska_odmowa_w_drodze(qapp, tmp_path, monkeypatch):
    """Zbiór w drodze → odmowa jak przy „Wydaj na stół…" (podpowiedź teczki liczona ze zbioru,
    który zaraz zniknie); okno teczek się nie otwiera."""
    from horreum.gui.grid import FramesView

    con, _ids = _obiekt_wydania(tmp_path)
    view = FramesView(con, now_fn=lambda: NOW)
    assert _wait_until(lambda: not view._zbior_w_drodze())
    otwarte = []
    monkeypatch.setattr(pd_mod.ObjectPickDialog, "exec", lambda self: otwarte.append(1) or 0)
    monkeypatch.setattr(view, "_zbior_w_drodze", lambda: True)
    msgs = []
    view.status_message.connect(msgs.append)
    view._open_object_release()
    assert not otwarte and msgs == [i18n.t("grid.sel.loading_refused")]
    con.close()


# ---------- Qt-wolne pomocniki trybu obiektu + i18n ----------

def test_flat_gap_text_szesc_tokenow_ma_zdanie_pl_i_en():
    """Parytet tokenów luki z katalogiem (mapa `_FLAT_GAP_KEYS` - kolektor literałów jej nie
    widzi): sześć tokenów `raw_flats_for`, każdy ze zdaniem PL i EN; okno nocy wchodzi do zdania
    `out_of_window`, a token spoza mapy renderuje klucz, nie pustkę."""
    from horreum.gui.i18n_catalog import CATALOG

    tokeny = {"incomplete_recipe", "no_profile", "pending", "no_raw", "out_of_window", "no_time"}
    assert set(pd_mod._FLAT_GAP_KEYS) == tokeny
    for key in pd_mod._FLAT_GAP_KEYS.values():
        assert CATALOG[key]["pl"] and CATALOG[key]["en"], key
    for key in pd_mod._STATE_TIPS.values():
        assert key in CATALOG, key
    assert pd_mod.flat_gap_text("out_of_window", 30) == "najbliższe surowe flaty dalej niż 30 dni"
    assert pd_mod.flat_gap_text("nowy_token", 30) == "proj.obj.gap.nowy_token"
    i18n.set_lang("en")
    assert pd_mod.flat_gap_text("out_of_window", 7) == "nearest raw flats more than 7 days away"


def test_odmiana_liczebnikow_naglowka_obiektu():
    """Odmiana przez `t_plural` (1, 2-4, 5+, 12-14, 22) - PL odmienia frazę, EN rzeczownik."""
    oczek = {
        "proj.obj.n_lights": ("1 light", "2 lighty", "5 lightów", "12 lightów", "22 lighty"),
        "proj.obj.n_masters": ("1 master", "2 mastery", "5 masterów", "12 masterów", "22 mastery"),
        "proj.obj.n_raw_flats": ("1 surowy flat", "2 surowe flaty", "5 surowych flatów",
                                 "12 surowych flatów", "22 surowe flaty"),
    }
    for key, formy in oczek.items():
        assert tuple(i18n.t_plural(key, n) for n in (1, 2, 5, 12, 22)) == formy, key
    assert i18n.t_plural("proj.obj.zestaw_item", 3, seg="RC8_X") == "RC8_X (3 lighty)"
    i18n.set_lang("en")
    assert i18n.t_plural("proj.obj.n_lights", 1) == "1 light"
    assert i18n.t_plural("proj.obj.n_raw_flats", 2) == "2 raw flats"


def test_object_totals_mastery_distinct_pending_osobno():
    """Nagłówek mówi o archiwum, nie o folderach: master wspólny dwóch zestawów liczy się raz,
    surowy flat też; `pending` nie wchodzi do „bez flatu"."""
    info = {"zestawy": {
        "A": {"lights": [1, 2, 3], "masters": {"dark": [9], "flat": [8]}, "flat_raw": [7, 6],
              "bez_flatu": [3], "bez_darka": [2, 3], "pending": [2]},
        "B": {"lights": [4], "masters": {"dark": [9]}, "flat_raw": [7],
              "bez_flatu": [], "bez_darka": [], "pending": []},
    }}
    assert pd_mod.object_totals(info) == {"lights": 4, "masters": 2, "raw": 2, "bez_flatu": 1,
                                          "bez_darka": 2, "pending": 1}


def test_en_render_trybu_obiektu_i_teczek(qapp, tmp_path, ustawienia, monkeypatch):
    """EN z katalogu: tytuł, nagłówek z odmianą, combo zestawu, kolumny teczek, przycisk paska."""
    i18n.set_lang("en")
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    _target(ustawienia, tmp_path / "_WBPP" / "karta")
    dlg = _dlg_obj(con)
    assert dlg.windowTitle() == "Release object to WBPP"
    assert dlg.head_label.text() == ("NGC 6992: 6 lights · 3 masters · 2 raw flats · "
                                     "without flat 1 · without dark 4")
    assert dlg.pending_label.text() == "to recompute in Delivery: 1"
    assert dlg.combo_zestaw.itemText(0) == "All" and dlg.btn_open.text() == "Open in Explorer"
    assert dlg.btn_apply.text() == "Create 11 links"
    pick = pd_mod.ObjectPickDialog(con)
    assert pick.windowTitle() == "Pick an object to release" and pick.btn_next.text() == "Next"
    assert pick.table.horizontalHeaderItem(1).text() == "Object"
    assert i18n.t("grid.sel.release_object") == "Release object…"
    con.close()


def test_en_komplet_w_celu_i_stan_pusty_teczek(qapp, tmp_path, ustawienia, monkeypatch):
    """EN z katalogu: nagłówek sondy przy komplecie i zdanie frazy bez trafień w oknie teczek."""
    i18n.set_lang("en")
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "en_komplet.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    dlg._on_apply()
    dlg._on_manual_dry()
    assert dlg.report.toPlainText().startswith(
        "Already complete in the target (layout po-obiektach, hardlinks):")
    con.close()
    teczki = _teczki_do_szukania(tmp_path)
    pick = pd_mod.ObjectPickDialog(teczki)
    pick.search.setText("zzz")
    assert pick.empty_label.text() == "No objects to release for “zzz”"
    teczki.close()
