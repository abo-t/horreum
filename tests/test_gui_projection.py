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
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from horreum.gui import i18n, queries, theme
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
    assert pd_mod.target_roots() == []
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


@pytest.mark.zmienia_motyw          # przełącza kolory modułu świadomie (wracają też na końcu testu)
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
    assert rep.startswith("Komplet już w celu (układ po obiektach, hardlinki):")   # nazwa, nie token
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
    assert dlg.head_label.text() == "NGC 6992: 6 lightów · 3 mastery · 2 surowe flaty"
    assert dlg.gaps_label.text() == "bez flatu 1 · bez darka 4" and not dlg.gaps_label.isHidden()
    assert dlg.gaps_label.property("role") == "warn"       # luki rolą ostrzeżenia, nie liczbą pozytywną
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
    assert dlg.summary == f"Wydano obiekt NGC 6992: zlinkowano 11 plików → {obj_root}"
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
    assert dlg.head_label.text() == "NGC 6992 / RC8_ASI2600MM: 1 light · 2 mastery · 0 surowych flatów"
    assert dlg.gaps_label.isHidden()                       # komplet: zero luk → wiersz ostrzeżenia znika
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
    assert rep.startswith(f"Komplet już w celu (układ obiekt do WBPP, {tryb}):")
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
    # flat: la1, la_gone, lb1 z masterem (3/6), la2 z surowymi (1/6), la3 `pending` (1/6) - pokrycie
    # 5/6 = 83 %, więc części sumują się do 83 (`split_pct`, największa reszta: remis 16,67 obu
    # części rozstrzyga kolejność - surowe przed `pending`), a nie do 82 ze ścięcia każdej osobno.
    assert cells == ["NGC 6992", "0.5", "6", "1", "2",
                     "50 % / 17 % · do przeliczenia w Dostawie: 16 %", "33 %", "2024-03-01"]
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
    assert any(m.startswith("Wydano obiekt NGC 6992: zlinkowano 11 plików") for m in msgs)
    view.close()
    con.close()


def test_przycisk_paska_w_drodze_otwiera_teczki_BEZ_podpowiedzi(qapp, tmp_path, monkeypatch):
    """Zbiór w drodze → okno teczek otwiera się bez preselekcji i bez odmowy: zbiór jest tu tylko
    podpowiedzią, a podpowiedź ze zbioru, który zaraz zniknie, wskazałaby cudzą teczkę. Odmowa
    blokowała kafel Domu przez ~1 s po każdym przeładowaniu zdaniem o tabeli, której na Domu
    nie widać (wizytacja natywna). Poza drogą podpowiedź wraca."""
    from horreum.gui import grid as grid_mod
    from horreum.gui.grid import FramesView

    con, _ids = _obiekt_wydania(tmp_path)
    view = FramesView(con, now_fn=lambda: NOW)
    assert _wait_until(lambda: not view._zbior_w_drodze())
    otwarte = []

    class _Teczki:
        def __init__(self, con_, *, preselect=None, parent=None):
            otwarte.append(preselect)

        def exec(self):
            return 0

    monkeypatch.setattr(grid_mod, "ObjectPickDialog", _Teczki)
    msgs = []
    view.status_message.connect(msgs.append)
    view.apply_object_facet([(r[0], r[1]) for r in con.execute(
        "SELECT id, canon FROM object WHERE canon = 'NGC 6992'")])
    assert _wait_until(lambda: not view._zbior_w_drodze())
    view._open_object_release()
    assert otwarte[-1] is not None, "poza drogą podpowiedź teczki stoi"
    monkeypatch.setattr(view, "_zbior_w_drodze", lambda: True)
    view._open_object_release()
    assert otwarte[-1] is None and i18n.t("grid.sel.loading_refused") not in msgs
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
    assert dlg.head_label.text() == "NGC 6992: 6 lights · 3 masters · 2 raw flats"
    assert dlg.gaps_label.text() == "without flat 1 · without dark 4"
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
        "Already complete in the target (layout by object, hardlinks):")
    con.close()
    teczki = _teczki_do_szukania(tmp_path)
    pick = pd_mod.ObjectPickDialog(teczki)
    pick.search.setText("zzz")
    assert pick.empty_label.text() == "No objects to release for “zzz”"
    teczki.close()


# ---------- cele wydania: jedna postać zapisu (`remember_target`, `target_roots`) ----------

def test_remember_target_dedup_po_kluczu_a_zapis_zachowuje_wielkosc_liter(qapp, tmp_path, ustawienia):
    """Ta sama karta zapisana z `/`, z `\\`, inną wielkością liter albo końcowym separatorem to JEDEN
    cel: nowa nazwa, karta na końcu, jedna kanoniczna postać także w `projection/last_target`.
    Zapis zachowuje wielkość liter wejścia (karta trafia do nazw katalogów zakładanych przy
    wydaniu) - wielkości nie rozróżnia wyłącznie klucz porównania."""
    karta = tmp_path / "_WBPP" / "Karta"
    ustawienia.setValue("projection/targets", json.dumps(
        [{"name": "stara", "path": str(karta).replace("\\", "/")}]))        # zapis sprzed kanonizacji
    inna = tmp_path / "_Review" / "stol"

    zapisana = pd_mod.remember_target("nowa", str(karta).upper() + "\\")
    assert zapisana == os.path.normpath(str(karta).upper())
    cele = json.loads(ustawienia.value("projection/targets"))
    assert cele == [{"name": "nowa", "path": zapisana}]                    # stara karta zastąpiona, nie obok
    assert ustawienia.value("projection/last_target") == zapisana

    pd_mod.remember_target("stol", str(inna).replace("\\", "/"), select=False)
    assert ustawienia.value("projection/last_target") == zapisana          # select=False nie rusza pamięci
    assert [c["name"] for c in json.loads(ustawienia.value("projection/targets"))] == ["nowa", "stol"]

    pd_mod.remember_target("karta", str(karta))                            # powrót do pierwszej: karta na końcu
    assert [c["name"] for c in json.loads(ustawienia.value("projection/targets"))] == ["stol", "karta"]
    assert ustawienia.value("projection/last_target") == str(karta)


def test_target_roots_kanoniczne_bez_powtorzen(qapp, tmp_path, ustawienia):
    """Korzenie kart dla listy wydań: postać kanoniczna, bez powtórzeń nawet wtedy, gdy zapis sprzed
    kanonizacji niesie ten sam cel dwa razy (`/` i `\\`, inna wielkość liter)."""
    assert pd_mod.target_roots() == []
    a, b = tmp_path / "_WBPP" / "A", tmp_path / "_Review" / "B"
    ustawienia.setValue("projection/targets", json.dumps([
        {"name": "a", "path": str(a).replace("\\", "/")},
        {"name": "a2", "path": str(a).upper()},
        {"name": "b", "path": str(b)},
    ]))
    assert pd_mod.target_roots() == [str(a), str(b)]


def test_dialog_dwa_zapisy_tego_samego_celu_to_jedna_karta(qapp, tmp_path, ustawienia, monkeypatch):
    """Dodanie celu przez dialog idzie tą samą drogą co menu (`remember_target`): ta sama karta
    z `/` i potem z `\\` nie rośnie w drugą - jedna karta, zaznaczona, pamięć w postaci kanonicznej."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g_dedup.db"))
    ids = _seed_files(con, tmp_path, 1)
    dlg = _dlg(con, ids)
    karta = tmp_path / "_WBPP" / "feed"
    assert dlg._add_target_path(str(karta).replace("\\", "/"), "feed")
    assert dlg._add_target_path(str(karta), "feed2")
    assert [c["path"] for c in dlg._cards] == [str(karta)]
    assert dlg._current_root() == str(karta)
    assert ustawienia.value("projection/last_target") == str(karta)
    con.close()


def test_dialog_pamiec_celu_zapisana_inaczej_niz_karta_nadal_zaznacza_karte(
        qapp, tmp_path, ustawienia, monkeypatch):
    """`last_target` z `/` przy karcie z `\\` (albo odwrotnie) wskazuje ten sam cel: otwarcie okna
    zaznacza właśnie tę kartę, a nie ostatnio dodaną."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g_pamiec.db"))
    ids = _seed_files(con, tmp_path, 1)
    a, b = tmp_path / "_WBPP" / "a", tmp_path / "_WBPP" / "b"
    ustawienia.setValue("projection/targets", json.dumps(
        [{"name": "a", "path": str(a)}, {"name": "b", "path": str(b)}]))
    ustawienia.setValue("projection/last_target", str(a).replace("\\", "/"))
    assert _dlg(con, ids)._current_root() == str(a)
    con.close()


# ---------- wydanie obiektu: wiersz „Wyjście WBPP" ----------

def _etykiety(widget):
    return [lab.text() for lab in widget.findChildren(QLabel)]


def test_tryb_obiektu_wiersz_wyjscia_wbpp_po_wydaniu_schowek_i_invalidate(
        qapp, tmp_path, ustawienia, monkeypatch):
    """Po udanym wydaniu obiektu okno mówi, gdzie w WBPP ustawić Output Directory: wiersz
    „Wyjście WBPP: <folder obiektu>\\out", przycisk do schowka i podpowiedź (jedna sesja na wydanie,
    keyword TELESCOP przy mieszaniu). Wiersz żyje i gaśnie z `_arm_open`: przed wydaniem go nie ma,
    `_invalidate` go zdejmuje, powrót do kompletu (nowe okno, DRY zastaje komplet) uzbraja go znowu.

    Falsyfikator: `out_label.setText` poza `_arm_open` → wiersz zostaje po zmianie karty."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    karta = tmp_path / "_WBPP" / "karta"
    _target(ustawienia, karta)
    dlg = _dlg_obj(con)
    assert dlg.out_box.isHidden() and dlg._out_dir is None               # przed wydaniem nie ma czego kopiować

    dlg._on_apply()
    wyjscie = karta / "OBJECTS" / "NGC_6992" / projection.OUTPUT_DIR
    assert not dlg.out_box.isHidden()
    assert dlg.out_label.full_text() == f"Wyjście WBPP: {wyjscie}"      # treść; `text()` = to, co się zmieściło
    assert dlg.out_label.toolTip() == f"Wyjście WBPP: {wyjscie}"
    assert wyjscie.is_dir()                                              # zakłada go klinga apply, nie okno
    napisy = " ".join(_etykiety(dlg.out_box))
    assert "Output Directory" in napisy and "TELESCOP" in napisy and "jedna sesja" in napisy.lower()

    QTest.mouseClick(dlg.btn_out_copy, Qt.LeftButton)
    assert QApplication.clipboard().text() == str(wyjscie)

    QApplication.clipboard().setText("sprzed")
    dlg._invalidate()
    assert dlg.out_box.isHidden() and dlg._out_dir is None and dlg.out_label.full_text() == ""
    dlg.btn_out_copy.click()                                             # zgaszony wiersz nie kopiuje starej ścieżki
    assert QApplication.clipboard().text() == "sprzed"

    powrot = _dlg_obj(con)                                               # DRY zastaje komplet
    assert not powrot.out_box.isHidden()
    assert powrot.out_label.full_text() == f"Wyjście WBPP: {wyjscie}"
    con.close()


def test_tryb_obiektu_wiersz_wyjscia_gasnie_przy_zmianie_karty(qapp, tmp_path, ustawienia, monkeypatch):
    """Wyjście jest własnością folderu wydanego na DANEJ karcie: przejście na kartę, na której
    obiektu jeszcze nie ma, zdejmuje wiersz (inaczej wskazywałby folder cudzej karty), a padnięta
    sonda też go gasi."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    a, b = tmp_path / "_WBPP" / "a", tmp_path / "_WBPP" / "b"
    ustawienia.setValue("projection/targets", json.dumps(
        [{"name": "a", "path": str(a)}, {"name": "b", "path": str(b)}]))
    ustawienia.setValue("projection/last_target", str(a))
    dlg = _dlg_obj(con)
    radio = {c["path"]: c["radio"] for c in dlg._cards}
    dlg._on_apply()
    assert not dlg.out_box.isHidden()
    radio[str(b)].setChecked(True)
    assert dlg.out_box.isHidden()
    radio[str(a)].setChecked(True)
    assert not dlg.out_box.isHidden()
    dlg._on_dry_failed(dlg._gen, "OSError: cel odpięty")
    assert dlg.out_box.isHidden()
    con.close()


def test_wydanie_perspektywy_nie_ma_wiersza_wyjscia(qapp, tmp_path, ustawienia, monkeypatch):
    """Wiersz „Wyjście WBPP" należy do wydania OBIEKTU (WBPP wskazuje się folderem obiektu);
    wydanie klatek gridu go nie tworzy, a `_arm_open` nie sięga po nieistniejący widżet."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g_persp.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    dlg._on_apply()
    assert dlg.out_box is None
    con.close()


def test_en_wiersz_wyjscia_wbpp(qapp, tmp_path, ustawienia, monkeypatch):
    i18n.set_lang("en")
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    karta = tmp_path / "_WBPP" / "karta"
    _target(ustawienia, karta)
    dlg = _dlg_obj(con)
    dlg._on_apply()
    assert dlg.out_label.full_text() == f"WBPP output: {karta / 'OBJECTS' / 'NGC_6992' / 'out'}"
    assert dlg.btn_out_copy.text() == "Copy path"
    assert any("Output Directory" in t and "TELESCOP" in t for t in _etykiety(dlg.out_box))
    con.close()


# ---------- szlif wydania: rozmiar okna, procenty, wcięcie raportu, role, słownik, karty ----------

# Realne długości z kopii `pf4` (v36, 2026-10-13): najdłuższa nazwa pliku obecnej kopii (79 znaków)
# i najdłuższy kanon obiektu z lightami. Karta pod `tmp_path` z segmentem jak katalog sesji
# wizytacji bm - tej długości ścieżka „Wyjście WBPP" rozpychała okno do 1578 px.
_NAZWA_PF4 = "NGC891_2025-02-04_RC8_2600MC_NoFilter_120s_RGB_CALDWELL-23_fastIntegration.xisf"
_KANON_PF4 = "C/2023 A3 (Tsuchinshan-ATLAS)"
_SESJA = "e--Claude-Horreum_6ad439ba-e9d0-437d-a8ad-bd2375a42b5c"


def test_split_pct_suma_rowna_pokryciu_liczby_z_kopii_pf4():
    """Części jednej całości sumują się do pokrycia liczonego regułą `readiness_pct`, każda trzyma
    tę regułę (0 i 100 tylko, gdy prawdziwe). Liczby z kopii `pf4`: Cr464 132 + 35 ze 167 (ścięte
    osobno „79 % / 20 %", suma 99 przy flacie dla każdego lightu) i NGC6888 496 + 72 z 584 (96 przy
    pokryciu 97). Dalej progi: część zawyżona do 1 % oddaje punkt, gdy suma przerosłaby pokrycie."""
    from horreum.gui.queries import readiness_pct

    assert queries.split_pct((132, 35, 0), 167) == [79, 21, 0]
    assert queries.split_pct((496, 72, 0), 584) == [85, 12, 0]
    assert queries.split_pct((999, 1), 1000) == [99, 1]         # komplet: 100 bez części „100"
    assert queries.split_pct((998, 1), 1000) == [98, 1]         # pokrycie 99: suma nie udaje kompletu
    assert queries.split_pct((1, 1, 1), 1000) == [1, 1, 1]      # próg 1 % ważniejszy niż suma 1
    assert queries.split_pct((5, 0, 0), 5) == [100, 0, 0]
    assert queries.split_pct((0, 0, 0), 0) == [0, 0, 0]
    for total in (3, 6, 7, 167, 584):
        for a in range(0, total + 1, max(1, total // 7)):
            for b in range(0, total - a + 1, max(1, total // 5)):
                czesci = queries.split_pct((a, b), total)
                assert sum(czesci) == readiness_pct(a + b, total), (a, b, total)
                for n, p in zip((a, b), czesci):
                    assert (p == 0) == (n == 0) and (p == 100) == (n == total), (a, b, total)


def test_teczki_procenty_flatu_cr464_sumuja_sie_do_kompletu(qapp, tmp_path, monkeypatch):
    """Kolumna flatu okna teczek pokazuje części z `queries.release_readiness`, które liczy je
    `queries.split_pct` (jeden właściciel dla okna i karty na Domu): Cr464 z kopii `pf4` (flat dla
    każdego lightu, podgląd mówi „bez flatu 0") pokazuje 79 + 21, nie 79 + 20."""
    czesci = queries.split_pct((132, 35, 0), 167)
    assert czesci == [79, 21, 0]
    wiersz = {"object_id": 9, "canon": "Cr464", "lights": 167, "hours": 1.62, "nights": 1, "zestawy": 1,
              "n_master_flat": 132, "n_master_dark": 0, "n_raw_flat": 35, "n_pending": 0,
              "pct_master_flat": czesci[0], "pct_master_dark": 0, "pct_raw_flat": czesci[1],
              "pct_pending": czesci[2],
              "last_night": "2023-05-07", "stan": "amber"}
    monkeypatch.setattr(pd_mod.queries, "release_readiness", lambda con: [wiersz])
    con = db.open_db(str(tmp_path / "cr464.db"))
    pick = pd_mod.ObjectPickDialog(con)
    assert pick.table.item(0, 6).text() == "79 % / 21 %"
    con.close()


def test_kropka_stanu_teczki_trzyma_kolor_pod_zaznaczeniem(qapp, tmp_path, monkeypatch):
    """Zaznaczony wiersz okna teczek: Qt maluje tekst `HighlightedText` (biel), więc kropka stanu
    traciła kolor dokładnie na wskazanym obiekcie. Delegat kolumny 0 podstawia kolor roli komórki.
    Falsyfikator: bez delegata `HighlightedText` opcji = paleta widoku (nie kolor stanu)."""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QStyleOptionViewItem
    wiersz = {"object_id": 9, "canon": "Cr464", "lights": 167, "hours": 1.62, "nights": 1, "zestawy": 1,
              "n_master_flat": 167, "n_master_dark": 0, "n_raw_flat": 0, "n_pending": 0,
              "pct_master_flat": 100, "pct_master_dark": 0, "pct_raw_flat": 0, "pct_pending": 0,
              "last_night": "2023-05-07", "stan": "amber"}
    monkeypatch.setattr(pd_mod.queries, "release_readiness", lambda con: [wiersz])
    con = db.open_db(str(tmp_path / "kropka.db"))
    pick = pd_mod.ObjectPickDialog(con)
    try:
        pick.table.selectRow(0)
        idx = pick.table.model().index(0, 0)
        opt = QStyleOptionViewItem()
        pick.table.itemDelegateForColumn(0).initStyleOption(opt, idx)
        assert opt.palette.color(QPalette.HighlightedText) == pd_mod._COLORS["warn"]
    finally:
        pick.close()
        con.close()


def _pokazany(dlg, qapp, szer=640):
    dlg.resize(szer, 520)
    dlg.show()
    qapp.processEvents()
    return dlg.width()


def test_okno_nie_rosnie_od_dlugiej_nazwy_pliku_w_postepie(qapp, tmp_path, ustawienia, monkeypatch):
    """Nota postępu z nazwą pliku z kopii `pf4` (79 znaków) nie rusza szerokości okna ani jego
    minimum; pełna nota w tooltipie, widoczna - ucięta z wielokropkiem przy wąskim miejscu.
    Metryki offscreen nie są natywne, więc porównanie WZGLĘDNE, a falsyfikator wierny: etykieta
    z minimum równym treści (zwykły `QLabel`, na którym okno rosło z 701 do 1011 px - wizytacja
    bg) podnosi minimum okna ponad bieżącą szerokość."""
    from PySide6.QtWidgets import QLabel as _QLabel

    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "postep.db"))
    ids = _seed_files(con, tmp_path, 1)
    root = tmp_path / _SESJA / "_WBPP" / "feed"
    _target(ustawienia, root)
    dlg = _dlg(con, ids)
    w0 = _pokazany(dlg, qapp)
    dlg._apply_begin(167, str(root))
    qapp.processEvents()
    m0 = dlg.minimumSizeHint().width()
    dlg._on_apply_progress(12, 167, str(root / "Cr464" / "R" / _NAZWA_PF4), "linked")
    qapp.processEvents()
    nota = dlg.progress_note.full_text()
    assert nota.startswith("12/167") and nota.endswith(_NAZWA_PF4)
    assert dlg.progress_note.toolTip() == nota
    assert dlg.width() == w0 and dlg.minimumSizeHint().width() == m0
    dlg.progress_note.resize(200, dlg.progress_note.height())
    assert dlg.progress_note.text().startswith("12/167") and dlg.progress_note.text().endswith("…")
    dlg._apply_end()
    qapp.processEvents()
    assert dlg.width() == w0 and dlg.progress_note.full_text() == ""
    # Falsyfikator NA KOŃCU: przeliczenie układu z minimum starej etykiety naprawdę poszerza okno.
    dlg.progress_note.setMinimumWidth(_QLabel(nota).sizeHint().width())   # minimum = treść
    qapp.processEvents()
    assert dlg.minimumSizeHint().width() > w0
    dlg.close()
    con.close()


def test_nota_postepu_dostaje_wolne_miejsce_rzedu(qapp, tmp_path, ustawienia, monkeypatch):
    """Nota w biegu wydania (1310 pozycji, jak wizytacja natywna `B2_pl_nota_postepu_1310.png`)
    jest szeroka co najmniej na licznik z ETA - obok `addStretch(1)` dostawała minimum 40 px
    i pokazywała „123/…". Szerokość tekstu liczona metrykami fontu SAMEJ noty, nie stałą. Przyciski
    stoją przy prawej krawędzi rzędu przed biegiem i w biegu, a widoczny tekst noty zaczyna się
    od licznika z ETA (ucina się co najwyżej nazwa pliku)."""
    import time

    from PySide6.QtWidgets import QPushButton

    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "nota.db"))
    ids = _seed_files(con, tmp_path, 1)
    root = tmp_path / _SESJA / "_WBPP" / "feed"
    _target(ustawienia, root)
    dlg = _dlg(con, ids)
    _pokazany(dlg, qapp)
    zamknij = next(b for b in dlg.findChildren(QPushButton) if b.text() == "Zamknij")
    prawa = dlg.rect().right() - dlg.layout().contentsMargins().right()
    assert zamknij.geometry().right() == prawa             # przed biegiem: przyciski przy krawędzi
    dlg._apply_begin(1310, str(root))
    dlg._apply_started = time.monotonic() - 60.0           # 60 s na 123 pliki - ETA deterministyczne
    dlg._on_apply_progress(123, 1310, str(root / "Cr464" / "R" / _NAZWA_PF4), "linked")
    qapp.processEvents()
    licznik = "123/1310" + pd_mod.eta_text(123, 1310, 60.0)
    assert licznik == "123/1310 · pozostało ~10 min"        # 1187 plików × 60/123 s = 579 s
    fm = dlg.progress_note.fontMetrics()
    assert dlg.progress_note.width() >= fm.horizontalAdvance(licznik)
    assert dlg.progress_note.text().startswith(licznik)
    assert zamknij.geometry().right() == prawa             # w biegu też
    dlg._apply_end()
    dlg.close()
    con.close()


def test_okno_nie_rosnie_od_nierozbijalnej_sciezki_wyjscia(qapp, tmp_path, ustawienia, monkeypatch):
    """„Wyjście WBPP" (najdłuższy kanon z kopii `pf4`, karta o długości ścieżki wizytacji bm) nie
    dyktuje minimum ani wiersza, ani okna: minimum wiersza i okna jest to samo przy ścieżce długiej
    i krótkiej, etykieta tnie ŚRODEK ścieżki (zostaje „Wyjście WBPP:" i koniec `…\\out`), pełna
    ścieżka w tooltipie i w schowku. Offscreen inny wiersz trzyma minimum okna wyżej niż natywnie,
    więc falsyfikator stoi na poziomie WIERSZA: dawna zawijana etykieta z tą ścieżką ma sama
    minimum szersze niż cały dzisiejszy wiersz - natywnie tak rosło okno do 1578 px."""
    from PySide6.QtWidgets import QLabel as _QLabel

    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    con.execute("UPDATE object SET canon = ? WHERE id = 1", (_KANON_PF4,))
    con.commit()
    karta = tmp_path / _SESJA / "scratchpad" / "bramka" / "wiz" / "_WBPP"
    _target(ustawienia, karta)
    dlg = _dlg_obj(con)
    _pokazany(dlg, qapp)
    dlg._on_apply()
    qapp.processEvents()
    w1, m1, r1 = dlg.width(), dlg.minimumSizeHint().width(), dlg.out_box.minimumSizeHint().width()
    pelna = dlg.out_label.full_text()
    assert pelna == f"Wyjście WBPP: {dlg._out_dir}" and dlg._out_dir.endswith(os.sep + "out")
    wydany = dlg._released_root
    dlg._arm_open("X:\\")                                  # krótka ścieżka: to samo minimum
    qapp.processEvents()
    assert dlg.out_label.full_text() == "Wyjście WBPP: X:\\out"
    assert dlg.minimumSizeHint().width() == m1 and dlg.out_box.minimumSizeHint().width() == r1
    dlg._arm_open(wydany)                                  # jedyna droga produktu do etykiety
    qapp.processEvents()
    assert dlg.out_label.full_text() == pelna and dlg.width() == w1
    zawijana = _QLabel(pelna)
    zawijana.setWordWrap(True)
    assert zawijana.minimumSizeHint().width() > r1         # stara etykieta dyktowałaby wiersz
    dlg.out_label.resize(300, dlg.out_label.height())
    widoczna = dlg.out_label.text()
    assert "…" in widoczna and widoczna.startswith("Wyjście WBPP: ") and widoczna.endswith("out")
    assert dlg.out_label.toolTip() == pelna
    QTest.mouseClick(dlg.btn_out_copy, Qt.LeftButton)
    assert QApplication.clipboard().text() == dlg._out_dir   # schowek niesie pełną ścieżkę
    dlg.close()
    con.close()


def test_raport_zawiniety_wiersz_nie_lamie_slupka(qapp, tmp_path, ustawienia, monkeypatch):
    """Wiersz zestawu Cr464 z nocami (liczby z wizytacji bg, `30_Cr464_dry.png`: zawinięty po
    88 znakach, „2023-05-07)" od kolumny 0) zawija się przy tej samej szerokości tekstu, a
    kontynuacja zaczyna się `_REPORT_HANG` znaków głębiej niż własne wcięcie wiersza. Tekst raportu
    (`toPlainText`) zostaje dokładnie tym, co weszło. Szerokość zawijania stała (88 znaków), bo
    metryki offscreen nie są natywne."""
    from PySide6.QtGui import QFontMetricsF
    from PySide6.QtWidgets import QTextEdit

    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "slupek.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    _pokazany(dlg, qapp)
    znak = QFontMetricsF(dlg.report.font()).horizontalAdvance(" ")
    dlg.report.setLineWrapMode(QTextEdit.FixedPixelWidth)
    dlg.report.setLineWrapColumnOrWidth(int(88 * znak))
    info = {"window_days": 30, "zestawy": {"76EDPH_ASI2600MM": {
        "masters": {"flat": list(range(6))}, "flat_raw": list(range(51)),
        "flat_raw_nights": ["2023-05-07"], "lights": list(range(167)), "hours": 1.62,
        "bez_flatu": [], "flat_gaps": {}, "bez_darka": list(range(167)), "pending": []}}}
    wiersze = [w for w, _rola in pd_mod.object_report_lines(info)]
    tekst = "\n".join(["DRY - bez zmian na dysku (układ obiekt do WBPP, kopie):", *wiersze])
    dlg._show_report(tekst)
    qapp.processEvents()
    assert dlg.report.toPlainText() == tekst
    zestaw = dlg.report.document().findBlockByNumber(1)
    assert zestaw.text().startswith("  zestaw 76EDPH_ASI2600MM:") and "(noce: 2023-05-07)" in zestaw.text()
    uklad = zestaw.layout()
    assert uklad.lineCount() >= 2                          # wiersz naprawdę się zawija
    for i in range(1, uklad.lineCount()):
        assert uklad.lineAt(i).x() == pytest.approx(uklad.lineAt(0).x() + (2 + pd_mod._REPORT_HANG) * znak)
    dlg.close()
    con.close()


def test_luki_w_naglowku_i_raporcie_kolorem_roli_warn(qapp, tmp_path, ustawienia, monkeypatch):
    """Liczby luk mają rolę ostrzeżenia, nie kolor liczb tego, co jest: osobny wiersz nagłówka
    (`warn`, znika przy komplecie) i wiersze luk raportu w kolorze roli `warn` z motywu; wiersz
    zestawu zostaje neutralny."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    _target(ustawienia, tmp_path / "_WBPP" / "karta")
    dlg = _dlg_obj(con)
    assert dlg.gaps_label.property("role") == "warn" and not dlg.gaps_label.isHidden()
    warn = pd_mod._COLORS["warn"].name().lower()
    doc = dlg.report.document()
    kolory = {}
    for n in range(doc.blockCount()):
        tekst = doc.findBlockByNumber(n).text()
        f = _block_fmt(dlg.report, n)
        kolory[tekst.strip().split(":")[0]] = (f.foreground().color().name().lower()
                                               if f.foreground().style() != Qt.NoBrush else None)
    assert kolory["bez flatu"] == warn and kolory["bez darka"] == warn
    assert kolory["do przeliczenia w Dostawie"] == warn
    assert kolory["zestaw A140R_ASI2600MM"] is None and kolory["do zlinkowania"] is None
    assert pd_mod.object_gaps_text({"bez_flatu": 0, "bez_darka": 167}) == "bez darka 167"
    assert pd_mod.object_gaps_text({"bez_flatu": 0, "bez_darka": 0}) == ""
    con.close()


def test_waga_zlotej_akcji_idzie_za_eksploratorem(qapp, tmp_path, ustawienia, monkeypatch):
    """Po udanym wydaniu waga (bold, wysokość, Enter) przechodzi z wygaszonego „Utworzono ✓" na
    „Otwórz w Eksploratorze”; po zmianie parametru, do końca świeżej sondy, nie ma jej NIGDZIE -
    „Utwórz” jest wygaszone, a złoto na martwym przycisku wskazywałoby akcję, której nie ma (AR-245);
    świeża sonda nad kompletem i powrót do kompletu (nowe okno) stawiają ją na Eksploratorze."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    _target(ustawienia, tmp_path / "_WBPP" / "karta")

    def waga(b):
        return (b.font().bold(), b.minimumHeight() == pd_mod._GOLD_HEIGHT, b.isDefault())

    dlg = _dlg_obj(con)
    assert waga(dlg.btn_apply) == (True, True, True) and waga(dlg.btn_open) == (False, False, False)
    dlg._on_apply()
    assert dlg.btn_apply.text() == "Utworzono ✓" and not dlg.btn_apply.isEnabled()
    assert waga(dlg.btn_open) == (True, True, True) and waga(dlg.btn_apply) == (False, False, False)
    dlg._invalidate()
    assert not dlg.btn_apply.isEnabled()
    assert waga(dlg.btn_apply) == (False, False, False) and waga(dlg.btn_open) == (False, False, False)
    dlg._on_manual_dry()
    assert waga(dlg.btn_open) == (True, True, True) and waga(dlg.btn_apply) == (False, False, False)
    powrot = _dlg_obj(con)
    assert waga(powrot.btn_open) == (True, True, True) and not powrot.btn_apply.font().bold()
    con.close()


def test_tryb_obiektu_mowi_slownikiem_wydania(qapp, tmp_path, ustawienia, monkeypatch):
    """Bieg wydania obiektu nie mówi „Wydaję na stół", a zdanie na pasek odmienia liczbę plików
    („zlinkowano 1 plik"), nie „1 zlinkowano". EN: „Stop releasing" w trybie obiektu, „Stop
    serving" zostaje wydaniu perspektywy."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    _target(ustawienia, tmp_path / "_WBPP" / "karta")
    w_biegu = []
    _spy_progress(monkeypatch, hook=lambda n, w: w_biegu.append(dlg.report.toPlainText()))
    dlg = _dlg_obj(con)
    dlg.combo_zestaw.setCurrentIndex(2)                    # RC8_ASI2600MM: 3 pozycje
    dlg._on_apply()
    assert w_biegu and all(r.startswith("Wydaję obiekt → ") and "stół" not in r for r in w_biegu)
    assert dlg.summary.startswith("Wydano obiekt NGC 6992: zlinkowano 3 pliki → ")

    i18n.set_lang("en")                                    # język stoi PRZED budową okna (D-L1)
    obj = _dlg_obj(con)
    assert obj.btn_cancel.text() == "Stop releasing"
    obj._apply_begin(11, "X:\\_WBPP\\OBJECTS\\NGC_6992")
    assert obj.report.toPlainText().startswith("Releasing the object → X:\\_WBPP\\OBJECTS\\NGC_6992")
    obj._apply_end()
    persp = _dlg(con, [_ids["la1"]])
    assert persp.btn_cancel.text() == "Stop serving"
    con.close()


def test_zdanie_paska_odmienia_liczbe_plikow():
    """`{files}` zdań na pasek: fraza odmieniona (1, 2-4, 5, 12-14, 22) w obu trybach i językach."""
    oczek = {
        "proj.files_copied": ("skopiowano 1 plik", "skopiowano 2 pliki", "skopiowano 5 plików",
                              "skopiowano 12 plików", "skopiowano 22 pliki"),
        "proj.files_linked": ("zlinkowano 1 plik", "zlinkowano 2 pliki", "zlinkowano 5 plików",
                              "zlinkowano 12 plików", "zlinkowano 22 pliki"),
    }
    for key, formy in oczek.items():
        assert tuple(i18n.t_plural(key, n) for n in (1, 2, 5, 12, 22)) == formy, key
    assert i18n.t("proj.status_summary", files="zlinkowano 2 pliki", root="R") == \
        "Wydano na stół: zlinkowano 2 pliki → R"
    i18n.set_lang("en")
    assert [i18n.t_plural("proj.files_copied", n) for n in (1, 2)] == ["copied 1 file", "copied 2 files"]
    assert [i18n.t_plural("proj.files_linked", n) for n in (1, 5)] == ["linked 1 file", "linked 5 files"]
    assert i18n.t("proj.obj.status_summary", canon="M42", files="copied 1 file", root="R") == \
        "Released object M42: copied 1 file → R"


def test_en_bez_polskich_cudzyslowow_w_oknie_wydania():
    """BRAMKA rejonu: żadne zdanie EN okna wydania (`proj.*`) nie niesie polskiego „ - tłumaczenie
    przepisywało cudzysłów razem z polskim zdaniem („Next”, „Stop serving”)."""
    from horreum.gui.i18n_catalog import CATALOG

    zle = []
    for key, forms in CATALOG.items():
        if key.startswith("proj."):
            en = forms["en"]
            for tekst in (en.values() if isinstance(en, dict) else (en,)):
                if "\u201e" in tekst:
                    zle.append(key)
    assert not zle, zle


def test_uklad_nazwa_z_katalogu_parytet_i_en(qapp, tmp_path, ustawienia, monkeypatch):
    """Każdy układ klingi ma nazwę w katalogu (mapa `_LAYOUT_KEYS` - kolektor literałów jej nie
    widzi); token spoza mapy zostaje sobą. EN raportu wydania obiektu nie niesie tokenu dysku."""
    from horreum.gui.i18n_catalog import CATALOG

    assert set(pd_mod._LAYOUT_KEYS) == set(projection.LAYOUTS) | {projection.OBJECT_LAYOUT}
    for key in pd_mod._LAYOUT_KEYS.values():
        assert CATALOG[key]["pl"] and CATALOG[key]["en"], key
    assert pd_mod.layout_text("nowy-uklad") == "nowy-uklad"
    i18n.set_lang("en")
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    _target(ustawienia, tmp_path / "_WBPP" / "karta")
    dlg = _dlg_obj(con)                                    # referencja: tymczasowe okno ginie z dziećmi
    rep = dlg.report.toPlainText()
    assert rep.startswith("DRY - no disk changes (layout object for WBPP, hardlinks):")
    assert "wbpp-obiekt" not in rep
    con.close()


def test_karty_jednym_stylem_separatora_i_nazwa_folderu_roboczego(qapp, tmp_path, ustawienia, monkeypatch):
    """Karta zapisana sprzed kanonizacji (`/`) stoi na liście, w tooltipie i w „Wyjściu WBPP"
    separatorem systemu, jak karta zapisana dziś; ten sam cel zapisany dwiema pisowniami to jeden
    wiersz. Karta folderu roboczego założona po polsku mówi w UI EN „Working folder". Zapis
    w ustawieniach zostaje bez zmian."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    robocza, druga = tmp_path / "ASTRO_WORK" / "_WBPP", tmp_path / "x" / "_WBPP"
    zapis = json.dumps([{"name": "Folder roboczy", "path": str(robocza).replace("\\", "/")},
                        {"name": "druga", "path": str(druga)},
                        {"name": "druga-2", "path": str(druga).replace("\\", "/") + "/"}])
    ustawienia.setValue("projection/targets", zapis)
    ustawienia.setValue("projection/last_target", str(robocza))
    i18n.set_lang("en")
    dlg = _dlg_obj(con)
    napisy = [c["radio"].text() for c in dlg._cards]
    assert len(napisy) == 2 and napisy[0].startswith("Working folder  -  ")
    assert napisy[1].startswith("druga-2  -  ")           # nazwa późniejszego zapisu
    for c in dlg._cards:
        assert "/" not in c["radio"].text() and "/" not in c["radio"].toolTip()
    assert dlg._current_root() == str(robocza)
    dlg._on_apply()
    assert "/" not in dlg.out_label.full_text() and "/" not in dlg.summary
    assert ustawienia.value("projection/targets") == zapis  # zapis bez zmian
    assert pd_mod.card_name("Working folder") == "Working folder"
    i18n.set_lang("pl")
    assert pd_mod.card_name("Working folder") == "Folder roboczy"
    assert pd_mod.card_name("Moja karta") == "Moja karta"
    con.close()


# ============================================================ AR-197, AR-200: kroki wydania i odmowy w języku UI

_POLSKIE = set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
_SZCZEGOL = r"OSError: [WinError 64] Komunikat systemu: 'X:\L\a.fits'"


@pytest.fixture
def jezyk():
    yield i18n.set_lang
    i18n.set_lang("pl")


def _klik(przycisk):
    assert przycisk.isVisible() and przycisk.isEnabled(), przycisk.text()
    QTest.mouseClick(przycisk, Qt.LeftButton)


def _nazwy_wykluczone():
    from horreum.scan import EXCLUDED_DIR_NAMES
    return " / ".join(sorted(n.upper() for n in EXCLUDED_DIR_NAMES))


@pytest.mark.parametrize("lang", ["pl", "en"])
@pytest.mark.parametrize("krok, kod, nietkniete", [
    ("korzen", "proj_root_failed", 3), ("sonda", "proj_verify_failed", 2),
    ("manifest", "proj_manifest_failed", 0)])
def test_okno_wydania_krok_pada_raport_bledu_z_liczbami(qapp, tmp_path, ustawienia, monkeypatch, jezyk,
                                                      lang, krok, kod, nietkniete):
    """AR-197: krok wydania pada zerwanym udziałem (korzeń, sonda pierwszego linku, manifest) -
    klik „Utwórz” kończy się raportem: zdanie kroku z klasą w języku UI, pod nim liczby tego, co
    zaszło, i nietknięte; szczegół systemu pod kursorem raportu; „Przerwane błędem”, bez „Otwórz
    w Eksploratorze”. Falsyfikator: `_on_apply_done` bez gałęzi `res.error` - raport „Utworzono”."""
    jezyk(lang)
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "k.db"))
    ids = _seed_files(con, tmp_path, 3)
    root = tmp_path / "_WBPP" / "feed"
    _target(ustawienia, root)
    dlg = _dlg(con, ids)
    blad = OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64)

    def _pada(*_a, **_k):
        raise blad
    if krok == "korzen":
        prawdziwy = os.makedirs
        monkeypatch.setattr(projection.os, "makedirs", lambda p, *a, **k: (
            _pada() if os.path.normcase(str(p)) == os.path.normcase(str(root)) else prawdziwy(p, *a, **k)))
    else:
        monkeypatch.setattr(projection, "_verify_content" if krok == "sonda" else "_write_manifest", _pada)
    dlg.show()
    _klik(dlg.btn_apply)
    raport = dlg.report.toPlainText()
    klasa = i18n.t("objchg.item.os_share_lost", os_code="WinError 64")
    zdanie = i18n.t(f"objchg.item.{kod}", inner=klasa)
    rada_odswiez = i18n.t("proj.apply_error", msg="", made="").split("\n\n")[-1]
    if krok == "manifest":
        # Pliki leżą, sonda zobaczy komplet: bez rady „Odśwież podgląd” i bez „nietknięte: 0 … wznów”;
        # zdanie powodu mówi, czego brakuje (manifest) i po co (żniwa, strażnik układu).
        assert raport.startswith(i18n.t("proj.manifest_error_head", msg=zdanie)), raport
        assert rada_odswiez not in raport, raport
        assert i18n.t("proj.untouched", n=0) not in raport, raport
        assert "WBPP" in zdanie and "_PROJEKCJA.json" in zdanie
    else:
        assert raport.startswith(i18n.t("proj.apply_error", msg=zdanie, made="")), raport
        assert i18n.t("proj.untouched", n=nietkniete) in raport, raport
    assert (i18n.t("proj.unverified", n=1) in raport) == (krok == "sonda"), raport
    assert dlg.report.toolTip() == i18n.t("wb.os_detail_tip", detail=_SZCZEGOL)
    assert dlg.btn_apply.text() == i18n.t("proj.btn_error") and not dlg.btn_apply.isEnabled()
    # Ślad po zamknięciu okna (AR-245): zdanie paska ze szczegółem systemu, nie cisza.
    assert dlg.btn_open.isHidden() and dlg.summary == i18n.t("proj.status_failed", msg=zdanie, root=str(root))
    assert dlg.summary.szczegol == dlg.report.toolTip()
    if lang == "en":
        assert not set(raport.split("\n")[0]) & _POLSKIE, raport
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_odmowa_straznika_korzenia_przy_dodaniu_celu_w_jezyku_UI(qapp, tmp_path, monkeypatch, jezyk,
                                                               lang):
    """AR-200: cel bez segmentu wykluczonego - odmowa strażnika mówi kodem w języku UI (dawniej
    zdanie PL rdzenia także w UI EN). Falsyfikator: `proj.add_failed` z `e=exc`."""
    jezyk(lang)
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "g.db"))
    dlg = _dlg(con, _seed_files(con, tmp_path, 1))
    zly = str(tmp_path / "LIGHTS")
    assert dlg._add_target_path(zly, "zly") is False
    oczekiwany = i18n.t("proj.add_failed", e=i18n.t("objchg.item.proj_root_not_excluded", dir=zly,
                                                   name=_nazwy_wykluczone()))
    assert dlg.report.toPlainText() == oczekiwany
    if lang == "en":
        assert not set(oczekiwany) & _POLSKIE, oczekiwany
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_sonda_DRY_na_karcie_bez_segmentu_mowi_kodem(qapp, tmp_path, ustawienia, monkeypatch, jezyk,
                                                     lang):
    """AR-200: karta celu bez segmentu wykluczonego zapisana w ustawieniach (np. przed walidacją
    dodania) - sonda DRY odmawia strażnikiem klingi, raport mówi kodem w języku UI. Falsyfikator:
    `DryWorker` z `str(exc)`."""
    jezyk(lang)
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "d.db"))
    zly = tmp_path / "LIGHTS"
    _target(ustawienia, zly)
    dlg = _dlg(con, _seed_files(con, tmp_path, 1))
    oczekiwany = i18n.t("proj.dry_failed", msg=i18n.t(
        "objchg.item.proj_root_not_excluded", dir=pd_mod._canon_path(zly), name=_nazwy_wykluczone()))
    assert dlg.report.toPlainText() == oczekiwany
    if lang == "en":
        assert not set(oczekiwany) & _POLSKIE, oczekiwany
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_abort_sondy_pierwszego_linku_w_jezyku_UI(qapp, tmp_path, ustawienia, monkeypatch, jezyk, lang):
    """AR-200: sonda pierwszego linku wykazała kopię zamiast hardlinka - „ABORT:” ze zdaniem kodu
    `proj_first_link` w języku UI, nad wynikiem częściowym z liczbą nietkniętych. Falsyfikator:
    `ApplyWorker` z `str(exc)` - zdanie PL w UI EN."""
    jezyk(lang)
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    monkeypatch.setattr(projection, "_verify_content", lambda src, dst, nbytes=65536: False)
    con = db.open_db(str(tmp_path / "a.db"))
    ids = _seed_files(con, tmp_path, 3)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    dlg.show()
    _klik(dlg.btn_apply)
    raport = dlg.report.toPlainText()
    assert raport.startswith(i18n.t("proj.abort_prefix", msg=i18n.t("objchg.item.proj_first_link")))
    assert i18n.t("proj.untouched", n=2) in raport, raport
    assert dlg.btn_apply.text() == i18n.t("proj.btn_not_created")
    if lang == "en":
        assert not set(raport.split("\n")[0]) & _POLSKIE, raport
    dlg.reject()
    con.close()


# ============================================================ AR-214: EXPECT rdzenia w oknie wydania

def _szpieg_reguly(monkeypatch):
    """Wyjątki, które dotarły do reguły wyjątku okna (`powod_okna`) - dowód, że raport mówi
    o wyjątku PRAWDZIWEGO rdzenia, nie o czymś po drodze. Reguła działa dalej bez zmian."""
    wyjatki, regula = [], pd_mod.powod_okna
    monkeypatch.setattr(pd_mod, "powod_okna", lambda exc: wyjatki.append(exc) or regula(exc))
    return wyjatki


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_sonda_DRY_blad_programu_rdzenia_w_jezyku_UI(qapp, tmp_path, ustawienia, monkeypatch, jezyk,
                                                     lang):
    """PRAWDZIWY `plan_object` rzuca goły `ValueError` „nieznany obiekt” (EXPECT: obiekt nie znika
    z bazy, wołający podał zły id) - klik „Odśwież podgląd”: raport „Nie można:” ze zdaniem błędu
    programu w języku UI, proza rdzenia z typem w szczególe technicznym pod kursorem, „Utwórz”
    i Eksplorator wygaszone. Falsyfikator: `DryWorker` z `powod_wyjatku(exc)` - proza PL w raporcie."""
    jezyk(lang)
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    _target(ustawienia, tmp_path / "_WBPP" / "karta")
    dlg = _dlg_obj(con)
    wyjatki = _szpieg_reguly(monkeypatch)
    dlg._object_id = 999
    dlg.show()
    _klik(dlg.btn_dry)
    (exc,) = wyjatki
    assert type(exc) is ValueError and "999" in str(exc), exc
    raport = dlg.report.toPlainText()
    assert raport == i18n.t("proj.dry_failed", msg=i18n.t("objchg.item.prog_error")), raport
    import re                                         # + miejsce w kodzie (AR-237)
    assert re.fullmatch(re.escape(i18n.t("objchg.st.detail_tip", detail=f"ValueError: {exc}")
                                  + " @ horreum/projection.py:") + r"\d+", dlg.report.toolTip())
    assert not dlg.btn_apply.isEnabled() and dlg.btn_open.isHidden()
    if lang == "en":
        assert not set(raport) & _POLSKIE, raport
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_wydanie_blad_programu_rdzenia_w_jezyku_UI(qapp, tmp_path, ustawienia, monkeypatch, jezyk, lang):
    """PRAWDZIWY rdzeń: plan z układem spoza `LAYOUTS` (błąd programu wołającego) - linki powstają,
    a `_write_manifest` pada w `layout_segments` gołym `ValueError` (nie `OSError` kroku, więc nie
    wynik z powodem): raport „Błąd:” ze zdaniem błędu programu w języku UI i liczbą utworzonych
    przed błędem, szczegół techniczny pod kursorem, „Przerwane błędem”. Falsyfikator: `ApplyWorker`
    z `powod_wyjatku(exc)` - proza PL w zdaniu raportu."""
    import dataclasses
    jezyk(lang)
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "bp.db"))
    ids = _seed_files(con, tmp_path, 2)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    dlg._plan = dataclasses.replace(dlg._plan, layout="zly-uklad")
    wyjatki = _szpieg_reguly(monkeypatch)
    dlg.show()
    _klik(dlg.btn_apply)
    (exc,) = wyjatki
    assert type(exc) is ValueError and "zly-uklad" in str(exc), exc
    raport = dlg.report.toPlainText()
    assert raport == i18n.t("proj.apply_error", msg=i18n.t("objchg.item.prog_error"),
                            made=i18n.t("proj.made_before_error", done=2, total=2)), raport
    import re                                         # + miejsce w kodzie (AR-237)
    assert re.fullmatch(re.escape(i18n.t("objchg.st.detail_tip", detail=f"ValueError: {exc}")
                                  + " @ horreum/projection.py:") + r"\d+", dlg.report.toolTip())
    assert dlg.btn_apply.text() == i18n.t("proj.btn_error") and not dlg.btn_apply.isEnabled()
    if lang == "en":
        assert not set(raport.split("\n")[0]) & _POLSKIE, raport
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_wydanie_wyjatek_z_callbacku_postepu_mowi_bledem_programu(qapp, tmp_path, ustawienia,
                                                                  monkeypatch, jezyk, lang):
    """Wyjątek z callbacku, który rdzeń woła w biegu (`progress` workera, `KeyError`) - ta sama
    reguła: zdanie błędu programu w języku UI, `Typ: opis` wyłącznie w szczególe. Falsyfikator:
    gałąź `Exception` bez `powod_okna` - `KeyError: 'postep'` w zdaniu raportu."""
    jezyk(lang)
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "cb.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    wyjatki = _szpieg_reguly(monkeypatch)
    monkeypatch.setattr(pd_mod.ApplyWorker, "_emit_progress", lambda self, *_a: {}["postep"])
    dlg.show()
    _klik(dlg.btn_apply)
    (exc,) = wyjatki
    assert type(exc) is KeyError, exc
    raport = dlg.report.toPlainText()
    assert raport == i18n.t("proj.apply_error", msg=i18n.t("objchg.item.prog_error"), made=""), raport
    import re                                         # + miejsce w kodzie (AR-237)
    assert re.fullmatch(re.escape(i18n.t("objchg.st.detail_tip", detail="KeyError: 'postep'")
                                  + " @ horreum/projection.py:") + r"\d+", dlg.report.toolTip())
    if lang == "en":
        assert not set(raport.split("\n")[0]) & _POLSKIE, raport
    dlg.reject()
    con.close()


# ============================================================ AR-215: jeden ogon zakończenia błędem

@pytest.mark.parametrize("droga, przycisk, z_szczegolem", [
    ("krok_manifestu", "proj.btn_error", True), ("sonda_hardlinka", "proj.btn_not_created", False),
    ("wyjatek_operacji", "proj.btn_error", True)])
def test_trzy_drogi_bledu_wydania_jeden_ogon(qapp, tmp_path, ustawienia, monkeypatch, droga, przycisk,
                                             z_szczegolem):
    """Krok wydania z błędem systemu (`res.error`), werdykt sondy pierwszego linku i wyjątek całej
    operacji kończą się TYM SAMYM ogonem (`_zakoncz_bledem`): pasek schowany i z powrotem
    nieokreślony, nota postępu pusta, „Przerwij” schowany, „Utwórz” widoczny i wygaszony z etykietą
    drogi, parametry odmrożone, pierwszy blok raportu w kolorze błędu, szczegół drogi pod kursorem.
    Falsyfikator: pomocnik bez `_apply_end()` albo bez wygaszenia „Utwórz”."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "ogon.db"))
    ids = _seed_files(con, tmp_path, 3)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    blad = OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64)

    def _pada(*_a, **_k):
        raise blad
    if droga == "krok_manifestu":
        monkeypatch.setattr(projection, "_write_manifest", _pada)
    elif droga == "sonda_hardlinka":
        monkeypatch.setattr(projection, "_verify_content", lambda src, dst, nbytes=65536: False)
    else:
        monkeypatch.setattr(projection, "apply", _pada)
    dlg.show()
    _klik(dlg.btn_apply)
    assert dlg.busy.isHidden() and (dlg.busy.minimum(), dlg.busy.maximum()) == (0, 0)
    assert not dlg.busy.isTextVisible() and dlg.progress_note.full_text() == ""
    assert dlg.btn_cancel.isHidden() and not dlg.btn_apply.isHidden()
    assert not dlg.btn_apply.isEnabled() and dlg.btn_apply.text() == i18n.t(przycisk)
    assert all(w.isEnabled() for w in (dlg.combo_layout, dlg.chk_copy, dlg.btn_add, dlg.btn_dry))
    assert all(c["holder"].isEnabled() for c in dlg._cards)
    glowa = _block_fmt(dlg.report, 0)
    assert glowa.foreground().color().name() == pd_mod._COLORS["error"].name()
    assert dlg.report.toolTip() == (i18n.t("wb.os_detail_tip", detail=_SZCZEGOL) if z_szczegolem else "")
    dlg.reject()
    con.close()


def test_ogon_bledu_wygasza_utworz_niezaleznie_od_wejscia_w_bieg(qapp, tmp_path, ustawienia, monkeypatch):
    """Kontrakt ogona (`_zakoncz_bledem`): slot porażki SAM wygasza „Utwórz”, a nie polega na tym,
    że wejście w bieg (`_apply_begin`) już je wygasiło - uzbrojony przycisk po porażce obiecywałby
    akcję nad drzewem zmienionym częściowo. Falsyfikator: ogon bez `setEnabled(False)`."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "kontrakt.db"))
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, _seed_files(con, tmp_path, 1))
    dlg.btn_apply.setEnabled(True)
    dlg._apply_seen = (0, 1)
    dlg._on_apply_failed(pd_mod.powod_okna(OSError("dysk odpięty")))   # ładunek jak z workera
    assert not dlg.btn_apply.isEnabled() and dlg.btn_apply.text() == i18n.t("proj.btn_error")
    dlg.reject()
    con.close()


# ============================================================ AR-213: „Zapisz manifest” z okna wydania

def _zegar():
    """Zegar okna: każde wołanie to kolejna sekunda - wydanie i naprawa mają RÓŻNE czasy."""
    licznik = iter(range(100_000))

    def teraz():
        n = next(licznik)
        return f"2026-07-17T{n // 3600:02d}:{n // 60 % 60:02d}:{n % 60:02d}+00:00"
    return teraz


def _okno_rc8(con, ustawienia, card, *, off_thread=False):
    """Okno wydania obiektu NGC 6992 na zestawie RC8 (bez klatek bez kopii) z zegarem `_zegar`."""
    _target(ustawienia, card)
    dlg = ProjectionDialog(con, object_id=1, now_fn=_zegar(), off_thread=off_thread)
    dlg.show()
    return dlg


def _czekaj(pred, s=10.0):
    """Pętla zdarzeń + krótki sen, aż `pred()` - wynik wątku tła dolatuje sygnałem kolejkowanym."""
    import time
    koniec = time.monotonic() + s
    while not pred():
        if time.monotonic() > koniec:
            return False
        QApplication.processEvents()
        time.sleep(0.01)
    return True


def _manifest_okna(root):
    return json.loads((root / projection.MANIFEST_NAME).read_text(encoding="utf-8"))


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_manifest_skasowany_sonda_proponuje_drugie_klikniecie_zapisuje(qapp, tmp_path, ustawienia,
                                                                       monkeypatch, jezyk, lang):
    """Wydanie (zegar okna), manifest skasowany razem z `out`; klik „Odśwież podgląd” - raport mówi
    lukę manifestu rolą ostrzeżenia i zapowiada datę wydania z drzewa (AR-240), „Utwórz” staje się
    „Zapisz manifest” ze ZŁOTĄ wagą (Eksplorator zwykły); klik - `ManifestWorker`: treść wydania
    (etykieta okna, listy, nazwy), `ts` = czas założenia folderu zestawu z `ts_source: "tree"`
    i `repaired_at` z późniejszego zegara, drzewo bez zmian (`out` nie wraca), raport z linią daty
    z drzewa, przycisk i zdanie paska naprawy; świeża sonda - już bez oferty. Falsyfikator: `_on_apply`
    przez `ApplyWorker` (zakłada `out`), złoto na Eksploratorze, data z drzewa bez słowa w oknie."""
    import shutil
    from test_projection import _bez_ts, _migawka
    if not hasattr(os.stat("."), "st_birthtime"):
        pytest.skip("czas założenia folderu (`st_birthtime`) - Windows, Python 3.12+")
    jezyk(lang)
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card)
    dlg.combo_zestaw.setCurrentIndex(2)                    # RC8_ASI2600MM
    _klik(dlg.btn_apply)
    root = card / "OBJECTS" / "NGC_6992"
    stary = _manifest_okna(root)
    (root / projection.MANIFEST_NAME).unlink()
    shutil.rmtree(root / projection.OUTPUT_DIR)
    przed = _migawka(str(root))
    _klik(dlg.btn_dry)
    raport = dlg.report.toPlainText()
    assert i18n.t("proj.obj.manifest_missing") in raport, raport
    assert i18n.t("proj.obj.manifest_ts_tree") in raport, raport
    assert i18n.t("proj.obj.manifest_no_ts") not in raport, raport
    assert dlg.btn_apply.text() == i18n.t("proj.obj.btn_write_manifest") and dlg.btn_apply.isEnabled()
    assert dlg.btn_apply.font().bold() and not dlg.btn_open.isHidden() and not dlg.btn_open.font().bold()
    _klik(dlg.btn_apply)
    nowy = _manifest_okna(root)
    assert _migawka(str(root)) == przed and not (root / projection.OUTPUT_DIR).exists()
    assert nowy["ts"] == projection._czas_z_drzewa(str(root), "RC8_ASI2600MM") is not None
    assert nowy["ts_source"] == projection.TS_SOURCE_TREE and nowy["repaired_at"] > stary["ts"]
    assert nowy["etykieta"] == stary["etykieta"] == "NGC 6992 / RC8_ASI2600MM"
    assert _bez_ts(nowy["zestawy"]) == _bez_ts(stary["zestawy"])
    assert dlg.report.toPlainText().startswith(i18n.t("proj.obj.manifest_written"))
    assert i18n.t("proj.obj.manifest_ts_tree") in dlg.report.toPlainText().split("\n")
    assert dlg.btn_apply.text() == i18n.t("proj.obj.btn_manifest_written") and not dlg.btn_apply.isEnabled()
    assert dlg.summary == i18n.t("proj.obj.status_manifest", canon="NGC 6992", root=str(root))
    if lang == "en":
        for klucz in ("proj.obj.manifest_missing", "proj.obj.manifest_written", "proj.obj.manifest_ts_tree",
                      "proj.obj.btn_write_manifest", "proj.obj.btn_manifest_written"):
            assert not set(i18n.t(klucz)) & _POLSKIE, klucz
        assert not set(dlg.summary) & _POLSKIE - set(str(root)), dlg.summary
    _klik(dlg.btn_dry)
    assert dlg.btn_apply.text() != i18n.t("proj.obj.btn_write_manifest") and not dlg.btn_apply.isEnabled()
    assert i18n.t("proj.obj.manifest_missing") not in dlg.report.toPlainText()
    dlg.reject()
    con.close()


def _pada_krok_manifestu(monkeypatch):
    """Krok manifestu wydania pada zerwanym udziałem; zwraca prawdziwy `_write_manifest`."""
    prawdziwy = projection._write_manifest

    def _pada(*_a, **_k):
        raise OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64)
    monkeypatch.setattr(projection, "_write_manifest", _pada)
    return prawdziwy


def _glowa_awarii_manifestu():
    klasa = i18n.t("objchg.item.os_share_lost", os_code="WinError 64")
    return i18n.t("proj.manifest_error_head", msg=i18n.t("objchg.item.proj_manifest_failed", inner=klasa))


def test_awaria_kroku_manifestu_sama_sonduje_a_naprawa_bierze_czas_proby(qapp, tmp_path, ustawienia,
                                                                         monkeypatch):
    """Krok manifestu pada zerwanym udziałem: okno SAMO uruchamia świeżą sondę i pod głową błędu
    (bez obietnicy) stawia jej werdykt - lukę manifestu i „Zapisz manifest” ze złotą wagą, pierwszy
    blok w kolorze błędu, szczegół awarii pod kursorem. Oferta liczy się TYM SAMYM czasem próby co
    zapis (`czas_proby_dla`, AR-245) - bez zapowiedzi daty z drzewa ani braku daty. Klik stempluje
    manifest czasem TEJ próby wydania (`ts`), nie chwilą naprawy - z niego żniwa liczą datę wydania.
    Falsyfikatory: głowa z przepowiednią bez sondy („Przerwane błędem” do ręcznego „Odśwież
    podgląd”); `ts` z `now_fn`; oferta sondy bez czasu próby."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card)
    dlg.combo_zestaw.setCurrentIndex(2)
    prawdziwy = _pada_krok_manifestu(monkeypatch)
    _klik(dlg.btn_apply)
    czas_proby = dlg._apply_now
    raport = dlg.report.toPlainText()
    sonda = i18n.t("proj.dry_head_complete", layout=pd_mod.layout_text(projection.OBJECT_LAYOUT),
                   mode=i18n.t("proj.mode_links"))
    assert raport.startswith(_glowa_awarii_manifestu() + sonda), raport
    assert i18n.t("proj.obj.manifest_missing") in raport.split("\n"), raport
    assert i18n.t("proj.obj.manifest_ts_tree") not in raport and i18n.t("proj.obj.manifest_no_ts") not in raport
    assert _block_fmt(dlg.report, 0).foreground().color().name() == pd_mod._COLORS["error"].name()
    assert dlg.report.toolTip() == i18n.t("wb.os_detail_tip", detail=_SZCZEGOL)
    assert dlg.btn_apply.text() == i18n.t("proj.obj.btn_write_manifest") and dlg.btn_apply.isEnabled()
    assert dlg.btn_apply.font().bold() and dlg.btn_apply.isDefault() and not dlg.btn_open.font().bold()
    monkeypatch.setattr(projection, "_write_manifest", prawdziwy)
    _klik(dlg.btn_apply)
    nowy = _manifest_okna(card / "OBJECTS" / "NGC_6992")
    assert nowy["ts"] == czas_proby and "repaired_at" not in nowy
    assert {z["ts"] for z in nowy["zestawy"].values()} == {czas_proby}
    assert i18n.t("proj.obj.manifest_no_ts") not in dlg.report.toPlainText()
    dlg.reject()
    con.close()


def test_awaria_kroku_manifestu_z_klatka_bez_kopii_daje_oferte_jak_wydanie(qapp, tmp_path, ustawienia,
                                                                          monkeypatch):
    """„Wszystkie” zestawy z klatką bez obecnej kopii (`la_gone`): krok manifestu pada, świeża sonda
    po awarii mówi pod głową błędu OFERTĘ „Zapisz manifest” z linią klatek bez kopii (AR-240: naprawa
    pisze to, co wydanie - nie odmawia), złota waga na ofercie; klik zapisuje manifest z listami
    wydania (z `la_gone`, jak `object_manifest`) i czasem TEJ próby. Falsyfikator: odmowa przy
    klatkach planu bez kopii (dawny kontrakt `proj_manifest_skipped`)."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card)
    assert dlg.combo_zestaw.currentData() is None and dlg._plan.skipped
    prawdziwy = _pada_krok_manifestu(monkeypatch)
    _klik(dlg.btn_apply)
    czas_proby = dlg._apply_now
    raport = dlg.report.toPlainText()
    assert raport.startswith(_glowa_awarii_manifestu()), raport
    assert i18n.t("proj.obj.manifest_no_copy", n=1) in raport.split("\n"), raport
    assert dlg.btn_apply.text() == i18n.t("proj.obj.btn_write_manifest") and dlg.btn_apply.isEnabled()
    assert dlg.btn_apply.font().bold() and dlg.btn_apply.isDefault() and not dlg.btn_open.font().bold()
    monkeypatch.setattr(projection, "_write_manifest", prawdziwy)
    _klik(dlg.btn_apply)
    nowy = _manifest_okna(card / "OBJECTS" / "NGC_6992")
    wydanie = projection.object_manifest(dlg._plan)
    assert ids["la_gone"] in nowy["zestawy"]["A140R_ASI2600MM"]["lights"]
    assert {s: (z["lights"], z["flat_raw"], z["masters"]) for s, z in nowy["zestawy"].items()} == {
        s: (z["lights"], z["flat_raw"], z["masters"]) for s, z in wydanie["zestawy"].items()}
    assert nowy["ts"] == czas_proby and dlg.btn_apply.text() == i18n.t("proj.obj.btn_manifest_written")
    assert i18n.t("proj.obj.manifest_no_copy", n=1) in dlg.report.toPlainText().split("\n")
    dlg.reject()
    con.close()


def test_zajety_plik_roboczy_manifestu_w_wydaniu_tez_sonduje(qapp, tmp_path, ustawienia, monkeypatch):
    """Cudzy `.part` obok manifestu w chwili wydania: krok manifestu odmawia `proj_manifest_busy`
    (pliki leżą, plik roboczy nietknięty) - okno traktuje to jak awarię kroku manifestu: głowa błędu,
    czas próby czeka na naprawę, świeża sonda sama mówi pod głową tę samą odmowę z radą.
    Falsyfikator: gałąź awarii manifestu tylko dla `proj_manifest_failed`."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card)
    dlg.combo_zestaw.setCurrentIndex(2)
    root = card / "OBJECTS" / "NGC_6992"
    part = root / (projection.MANIFEST_NAME + projection.PART_SUFFIX)
    root.mkdir(parents=True)
    part.write_bytes(b"cudzy")
    _klik(dlg.btn_apply)
    zdanie = i18n.t("objchg.item.proj_manifest_busy", path=str(part))
    raport = dlg.report.toPlainText()
    assert raport.startswith(i18n.t("proj.manifest_error_head", msg=zdanie)), raport
    assert i18n.t("proj.obj.manifest_refused", msg=zdanie) in raport.split("\n"), raport
    assert dlg._ts_po_awarii == (str(root), dlg._apply_now) and part.read_bytes() == b"cudzy"
    assert not (root / projection.MANIFEST_NAME).exists()
    dlg.reject()
    con.close()


@pytest.mark.parametrize("przypadek", ["opisany", "uszkodzony", "obcy", "rozjazd", "bez_nazw_z_obcym"])
def test_komplet_bez_oferty_zapisu_manifestu(qapp, tmp_path, ustawienia, monkeypatch, przypadek):
    """Sonda nad kompletem NIE proponuje zapisu, gdy manifest opisuje drzewo (`current`), także bez
    `names`, gdy w `LIGHT` leży plik spoza klatek, a manifest zna light spoza planu bez kopii (mapa
    z drzewa niepełna, a sama mapa planu obok niego byłaby częściowa - reguła wydania jej nie pisze),
    gdy jest uszkodzony albo należy do innego wydania (linia z powodem i radą „usuń ręcznie”, bez
    przycisku) i gdy układ drzewa się rozjechał (linia rozjazdu, bez diagnozy manifestu); bajty
    manifestu po sondzie = przed. Falsyfikator: oferta przy każdym komplecie."""
    import hashlib
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card)
    dlg.combo_zestaw.setCurrentIndex(2)
    _klik(dlg.btn_apply)
    root = card / "OBJECTS" / "NGC_6992"
    sciezka = root / projection.MANIFEST_NAME
    linia = None
    if przypadek == "uszkodzony":
        sciezka.write_bytes(b"{")
        linia = i18n.t("proj.obj.manifest_refused", msg=i18n.t("objchg.item.proj_manifest_damaged",
                                                               detail="JSON"))
    elif przypadek in ("obcy", "rozjazd"):
        m = _manifest_okna(root)
        m.update({"object_id": 999} if przypadek == "obcy" else {"segments": [["inny"]]})
        sciezka.write_text(json.dumps(m), encoding="utf-8")
        if przypadek == "obcy":
            linia = i18n.t("proj.obj.manifest_refused", msg=i18n.t("objchg.item.proj_manifest_foreign",
                                                                   detail="object_id"))
    elif przypadek == "bez_nazw_z_obcym":
        m = _manifest_okna(root)
        del m["zestawy"]["RC8_ASI2600MM"]["names"]
        m["zestawy"]["RC8_ASI2600MM"]["lights"] = sorted(m["zestawy"]["RC8_ASI2600MM"]["lights"]
                                                         + [_ids["la_gone"]])
        sciezka.write_text(json.dumps(m), encoding="utf-8")
        (root / "RC8_ASI2600MM" / "LIGHT" / "Ha" / "obcy.fits").write_bytes(b"nie klatka")
    przed = hashlib.sha256(sciezka.read_bytes()).hexdigest()
    _klik(dlg.btn_dry)
    raport = dlg.report.toPlainText()
    assert hashlib.sha256(sciezka.read_bytes()).hexdigest() == przed
    assert dlg.btn_apply.text() != i18n.t("proj.obj.btn_write_manifest") and not dlg.btn_apply.isEnabled()
    if linia is not None:
        assert linia in raport and "usuń ręcznie" in linia and "„Odśwież podgląd”" in linia, raport
    else:
        assert i18n.t("proj.obj.manifest_refused", msg="").strip() not in raport, raport
        assert i18n.t("proj.obj.manifest_stale").strip() not in raport, raport
    assert (i18n.t("proj.drift", was="wbpp-obiekt: inny") in raport) == (przypadek == "rozjazd"), raport
    dlg.reject()
    con.close()


def test_klikniecie_zapisu_sprawdza_drzewo_od_nowa(qapp, tmp_path, ustawienia, monkeypatch):
    """Między sondą a kliknięciem z drzewa zniknął plik - „Zapisz manifest” sprawdza komplet od nowa
    i odmawia (`proj_manifest_incomplete`) ogonem zakończenia błędem; manifestu nie ma dalej, a złota
    waga i Enter schodzą z wygaszonego „Przerwane błędem” na uzbrojony Eksplorator (jedna funkcja
    wagi ze stanu). Falsyfikator: zapis z wyniku sondy (`sonda=`) zamiast świeżego sprawdzenia;
    waga zostawiona przez sondę na przycisku oferty."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card)
    dlg.combo_zestaw.setCurrentIndex(2)
    _klik(dlg.btn_apply)
    root = card / "OBJECTS" / "NGC_6992"
    (root / projection.MANIFEST_NAME).unlink()
    _klik(dlg.btn_dry)
    assert dlg.btn_apply.text() == i18n.t("proj.obj.btn_write_manifest")
    (root / "RC8_ASI2600MM" / "LIGHT" / "Ha" / "lb1.fits").unlink()
    _klik(dlg.btn_apply)
    assert dlg.report.toPlainText().startswith(i18n.t(
        "proj.obj.manifest_error", msg=i18n.t("objchg.item.proj_manifest_incomplete", n=1)))
    assert dlg.btn_apply.text() == i18n.t("proj.btn_error") and not dlg.btn_apply.isEnabled()
    assert not (root / projection.MANIFEST_NAME).exists()
    assert dlg.btn_open.font().bold() and dlg.btn_open.isDefault()
    assert not dlg.btn_apply.font().bold() and not dlg.btn_apply.isDefault()
    dlg.reject()
    con.close()


def test_zapis_manifestu_na_prawdziwym_qthread(qapp, tmp_path, ustawienia, monkeypatch):
    """`ManifestWorker` na PRAWDZIWYM `QThread` (własne połączenie po ścieżce bazy, sygnał
    kolejkowany, sprzątanie `_cleanup_apply_thread`): manifest zapisany, wątek zebrany."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card, off_thread=True)
    assert _czekaj(lambda: dlg._dry_worker is None and dlg._plan is not None)
    dlg.combo_zestaw.setCurrentIndex(2)
    assert _czekaj(lambda: dlg._dry_worker is None and dlg.btn_apply.isEnabled())
    _klik(dlg.btn_apply)
    assert _czekaj(lambda: dlg._apply_thread is None and dlg._apply_worker is None)
    root = card / "OBJECTS" / "NGC_6992"
    (root / projection.MANIFEST_NAME).unlink()
    _klik(dlg.btn_dry)
    assert _czekaj(lambda: dlg._dry_worker is None and dlg.btn_apply.text()
                   == i18n.t("proj.obj.btn_write_manifest"))
    _klik(dlg.btn_apply)
    assert _czekaj(lambda: dlg._apply_thread is None and dlg._apply_worker is None)
    assert (root / projection.MANIFEST_NAME).exists()
    assert dlg.btn_apply.text() == i18n.t("proj.obj.btn_manifest_written")
    dlg.done(0)
    con.close()


def test_wydanie_z_okna_scala_manifest_bez_utraty(qapp, tmp_path, ustawienia, monkeypatch):
    """Ponowne wydanie z okna (nowy light) po wycofaniu `la2`, którego plik skasowano z drzewa: sonda
    liczy świadków starego manifestu (`manifest_sources`), wydanie dostaje je (`extra_sources`) -
    `la2` schodzi z `lights` i raport mówi to linią `proj.manifest_dropped`, a wycofany `la1`, którego
    plik leży, zostaje. Falsyfikator: `ApplyWorker` bez `extra_sources` (la2 zostałby - niepewny)."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card)
    dlg.combo_zestaw.setCurrentIndex(1)                    # A140R_ASI2600MM
    _klik(dlg.btn_apply)
    root = card / "OBJECTS" / "NGC_6992"
    (root / "A140R_ASI2600MM" / "LIGHT" / "OIII" / "la2.fits").unlink()
    con.execute("UPDATE frame SET retired_at = ? WHERE id IN (?, ?)", (NOW, ids["la1"], ids["la2"]))
    src = tmp_path / "lib" / "la9.fits"
    src.write_bytes(b"la9")
    fid = con.execute("INSERT INTO frame (sha1_data, kind, filetype, camera_id, config_id, object_id, "
                      "filter_canon, first_seen_at) VALUES ('la9', 'light', 'fits', 1, 10, 1, 'Ha', ?)",
                      (NOW,)).lastrowid
    con.execute("INSERT INTO header (frame_id, raw_json, date_obs, exptime, xbinning) "
                "VALUES (?, '{}', '2024-03-01T23:00:00', 300.0, 1)", (fid,))
    con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                (fid, str(src)))
    con.commit()
    _klik(dlg.btn_dry)
    assert dlg.btn_apply.isEnabled() and dlg.btn_apply.text() != i18n.t("proj.obj.btn_write_manifest")
    _klik(dlg.btn_apply)
    lights = _manifest_okna(root)["zestawy"]["A140R_ASI2600MM"]["lights"]
    assert fid in lights and ids["la1"] in lights and ids["la2"] not in lights
    assert i18n.t("proj.manifest_dropped", n=1) in dlg.report.toPlainText()
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_wiersze_oferty_manifestu_mowia_czym_zapis_sie_rozni(jezyk, lang):
    """Oferta „Zapisz manifest” (`manifest_offer_lines`, Qt-wolne): brak manifestu; listy albo
    zestawy (ogólne „dopisze brakujące”); same nazwy plików; sam czas próby; liczby zachowanych
    i zapominanych id, brak daty wydania i foldery korzenia bez zeznania - każde osobnym wierszem,
    w języku UI. Falsyfikator: „dopisze brakujące” za sam brak nazw; liczby dopiero po kliknięciu."""
    jezyk(lang)
    t = i18n.t

    def oferta(**kw):
        payload = kw.pop("payload", {"ts": "T1", "zestawy": {"A": {}}})
        return projection.ManifestRepair("would-write", payload=payload, **kw)
    linie = pd_mod.manifest_offer_lines
    assert linie(oferta(stan="missing")) == [t("proj.obj.manifest_missing")]
    assert linie(oferta(stan="stale", roznice=("ids", "names"))) == [t("proj.obj.manifest_stale")]
    assert linie(oferta(stan="stale", roznice=("names", "ts"))) == [t("proj.obj.manifest_stale_names")]
    assert linie(oferta(stan="stale", roznice=("ts",))) == [t("proj.obj.manifest_stale_ts")]
    pelna = linie(oferta(stan="stale", roznice=("sets",), kept=2, dropped=1, obce_foldery=("C",),
                         payload={"ts": None, "zestawy": {"A": {}, "B": {}}}))
    assert pelna == [t("proj.obj.manifest_stale"), t("proj.obj.manifest_will_keep", kept=2, dropped=1),
                     t("proj.obj.manifest_no_ts"), t("proj.obj.manifest_only_sets", sets="A, B", other="C")]
    if lang == "en":
        for w in pelna + linie(oferta(stan="stale", roznice=("names",))) + linie(
                oferta(stan="stale", roznice=("ts",))):
            assert not set(w) & _POLSKIE, w


def test_oferta_po_samych_nazwach_i_z_liczbami_zachowanych(qapp, tmp_path, ustawienia, monkeypatch):
    """Sonda nad kompletem: manifest bez samych nazw - linia „nie zna nazw plików”, nie ogólne
    „dopisze brakujące”; manifest z surowymi flatami wcześniejszego wydania (jeden plik leży, drugiego
    nie ma) - ogólna linia luki i PRZED kliknięciem liczby: zachowa 1, zapomni 1. Falsyfikator:
    jedna linia `stale` na każdą lukę, liczby dopiero w raporcie po zapisie."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card)
    dlg.combo_zestaw.setCurrentIndex(2)
    _klik(dlg.btn_apply)
    root = card / "OBJECTS" / "NGC_6992"
    m = _manifest_okna(root)
    del m["zestawy"]["RC8_ASI2600MM"]["names"]
    (root / projection.MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")
    _klik(dlg.btn_dry)
    raport = dlg.report.toPlainText().split("\n")
    assert i18n.t("proj.obj.manifest_stale_names") in raport and i18n.t("proj.obj.manifest_stale") not in raport
    assert dlg.btn_apply.text() == i18n.t("proj.obj.btn_write_manifest")
    m["zestawy"]["RC8_ASI2600MM"]["flat_raw"] = sorted([ids["f1"], ids["f2"]])
    (root / projection.MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")
    flat = root / "RC8_ASI2600MM" / "FLAT_RAW" / "OIII" / "f1.fits"
    flat.parent.mkdir(parents=True)
    os.link(tmp_path / "lib" / "f1.fits", flat)
    _klik(dlg.btn_dry)
    raport = dlg.report.toPlainText().split("\n")
    assert i18n.t("proj.obj.manifest_stale") in raport, raport
    assert i18n.t("proj.obj.manifest_will_keep", kept=1, dropped=1) in raport, raport
    dlg.reject()
    con.close()


def test_manifest_opisany_w_miedzyczasie_daje_bez_zmian(qapp, tmp_path, ustawienia, monkeypatch):
    """Między sondą z ofertą a kliknięciem inny zapis położył manifest opisujący komplet - zapis
    mówi `current`: raport „już opisuje komplet”, przycisk „Bez zmian ✓”, nie „Manifest zapisany ✓”
    nad niezapisanym plikiem, a pasek - własne zdanie „bez zmian” (AR-245). Falsyfikator: jedna
    etykieta przycisku dla `written` i `current`."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card)
    dlg.combo_zestaw.setCurrentIndex(2)
    _klik(dlg.btn_apply)
    sciezka = card / "OBJECTS" / "NGC_6992" / projection.MANIFEST_NAME
    bajty, po_wydaniu = sciezka.read_bytes(), dlg.summary
    sciezka.unlink()
    _klik(dlg.btn_dry)
    assert dlg.btn_apply.text() == i18n.t("proj.obj.btn_write_manifest")
    sciezka.write_bytes(bajty)
    _klik(dlg.btn_apply)
    assert dlg.report.toPlainText() == i18n.t("proj.obj.manifest_current")
    assert dlg.btn_apply.text() == i18n.t("proj.btn_nothing_new") and not dlg.btn_apply.isEnabled()
    # Pasek mówi „bez zmian” tego biegu (AR-245), nie zdanie wydania sprzed niego ani o zapisie.
    assert sciezka.read_bytes() == bajty and dlg.summary != po_wydaniu
    assert dlg.summary == i18n.t("proj.obj.status_manifest_current", canon="NGC 6992",
                                 root=str(sciezka.parent))
    dlg.reject()
    con.close()


def test_esc_w_biegu_zapisu_manifestu_zamyka_okno_po_zapisie(qapp, tmp_path, ustawienia, monkeypatch):
    """Esc w biegu `ManifestWorker` na PRAWDZIWYM QThread: zapis jednego pliku jest nieprzerywalny -
    okno zostaje, nota mówi, że zamknie się po zapisie (nie „Anulowanie… po bieżącym pliku”),
    a po zapisie i sprzątnięciu wątku okno zamyka się samo: manifest na dysku, zdanie na pasek,
    wynik `Rejected`. Falsyfikator: `done()` przez `_on_cancel_apply` - nota anulowania i okno
    otwarte po zapisie."""
    import threading
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card, off_thread=True)
    assert _czekaj(lambda: dlg._dry_worker is None and dlg._plan is not None)
    dlg.combo_zestaw.setCurrentIndex(2)
    assert _czekaj(lambda: dlg._dry_worker is None and dlg.btn_apply.isEnabled())
    _klik(dlg.btn_apply)
    assert _czekaj(lambda: dlg._apply_thread is None and dlg._apply_worker is None)
    root = card / "OBJECTS" / "NGC_6992"
    (root / projection.MANIFEST_NAME).unlink()
    _klik(dlg.btn_dry)
    assert _czekaj(lambda: dlg._dry_worker is None and dlg.btn_apply.text()
                   == i18n.t("proj.obj.btn_write_manifest"))
    puszczony = threading.Event()
    prawdziwa = projection.repair_manifest

    def _czeka_na_esc(*a, **k):
        if k.get("do_write"):
            assert puszczony.wait(10)
        return prawdziwa(*a, **k)
    monkeypatch.setattr(projection, "repair_manifest", _czeka_na_esc)
    _klik(dlg.btn_apply)
    assert isinstance(dlg._apply_worker, pd_mod.ManifestWorker)
    QTest.keyClick(dlg, Qt.Key_Escape)
    assert dlg.isVisible() and dlg.progress_note.full_text() == i18n.t("proj.obj.closing_after_manifest")
    assert not (root / projection.MANIFEST_NAME).exists()
    puszczony.set()
    assert _czekaj(lambda: not dlg.isVisible())
    assert dlg._apply_thread is None and dlg._apply_worker is None
    assert (root / projection.MANIFEST_NAME).exists() and dlg.result() == QDialog.Rejected
    assert dlg.summary == i18n.t("proj.obj.status_manifest", canon="NGC 6992", root=str(root))
    con.close()


def test_czas_awarii_zerowany_tylko_dla_tego_samego_korzenia(qapp, tmp_path, ustawienia, monkeypatch):
    """Czas nieudanej próby (`_ts_po_awarii`) czeka na naprawę SWOJEGO korzenia: udane wydanie i zapis
    manifestu na innym korzeniu go nie zerują, na tym samym - tak. Falsyfikator: zerowanie przy
    każdym sukcesie (naprawa korzenia A po wydaniu na B stempluje czasem naprawy)."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card)
    dlg.combo_zestaw.setCurrentIndex(2)
    inny = (str(tmp_path / "inna" / "OBJECTS" / "NGC_6992"), "T-awarii")
    dlg._ts_po_awarii = inny
    _klik(dlg.btn_apply)
    root = str(card / "OBJECTS" / "NGC_6992")
    assert dlg._apply_root == root and dlg._ts_po_awarii == inny
    dlg._on_manifest_done(projection.ManifestRepair("current"))
    assert dlg._ts_po_awarii == inny
    dlg._ts_po_awarii = (root, "T-awarii")
    dlg._on_apply_done(projection.ApplyResult(root, projection.OBJECT_LAYOUT, True, False, [], False))
    assert dlg._ts_po_awarii is None
    dlg.reject()
    con.close()


def test_sonda_anulowana_nie_diagnozuje_manifestu(qapp, tmp_path, monkeypatch):
    """Diagnoza manifestu słucha anulowania sondy (zamknięcie okna w biegu): anulowanie przed
    diagnozą - diagnozy nie ma; w trakcie - rdzeń dostaje `should_cancel`, a wynik `cancelled` to
    „brak diagnozy”, nie odmowa w raporcie. Falsyfikator: diagnoza bez `_cancel` - Esc w sondzie
    czeka na świadka drzewa."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = str(tmp_path / "_WBPP" / "karta")
    plan = projection.plan_object(con, 1, config_id=20)
    root = projection.object_root(card, plan)
    projection.apply(plan, root, do_apply=True, now=NOW, manifest=projection.object_manifest(plan))
    os.remove(os.path.join(root, projection.MANIFEST_NAME))
    worker = pd_mod.DryWorker(None, [], None, card, False, NOW, 0, con=con, object_id=1, config_id=20)
    sluchacze, prawdziwa = [], projection.repair_manifest
    monkeypatch.setattr(projection, "repair_manifest",
                        lambda *a, **k: sluchacze.append(k["should_cancel"]) or prawdziwa(*a, **k))
    assert worker._compute()["manifest"].status == "would-write" and sluchacze[-1]() is False
    prawdziwe_zrodla = projection.manifest_sources

    def _esc_w_sondzie(*a):
        worker.request_cancel()
        return prawdziwe_zrodla(*a)
    monkeypatch.setattr(projection, "manifest_sources", _esc_w_sondzie)
    assert worker._compute()["manifest"] is None and len(sluchacze) == 1
    worker._cancel = False
    monkeypatch.setattr(projection, "manifest_sources", prawdziwe_zrodla)
    monkeypatch.setattr(projection, "repair_manifest", lambda *a, **k: projection.ManifestRepair("cancelled"))
    assert worker._compute()["manifest"] is None
    con.close()


# ============================================================ AR-245 / AR-240 / AR-234: domknięcia okna wydania

def _oferta_zapisu_na_qthread(tmp_path, ustawienia, monkeypatch):
    """Okno RC8 na PRAWDZIWYM QThread po wydaniu, manifest skasowany, świeża sonda z ofertą
    „Zapisz manifest” → `(con, dlg, korzeń wydania)`."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card, off_thread=True)
    assert _czekaj(lambda: dlg._dry_worker is None and dlg._plan is not None)
    dlg.combo_zestaw.setCurrentIndex(2)
    assert _czekaj(lambda: dlg._dry_worker is None and dlg.btn_apply.isEnabled())
    _klik(dlg.btn_apply)
    assert _czekaj(lambda: dlg._apply_thread is None and dlg._apply_worker is None)
    root = card / "OBJECTS" / "NGC_6992"
    (root / projection.MANIFEST_NAME).unlink()
    _klik(dlg.btn_dry)
    assert _czekaj(lambda: dlg._dry_worker is None and dlg.btn_apply.text()
                   == i18n.t("proj.obj.btn_write_manifest"))
    return con, dlg, root


@pytest.mark.parametrize("droga", ["odmowa", "wyjatek"])
def test_esc_w_biegu_zapisu_manifestu_zamyka_okno_takze_po_odmowie(qapp, tmp_path, ustawienia, monkeypatch,
                                                                   droga):
    """AR-245: Esc w biegu `ManifestWorker` na PRAWDZIWYM QThread, a zapis kończy się ODMOWĄ
    (plik zniknął z drzewa - `proj_manifest_incomplete`) albo WYJĄTKIEM (zerwany udział): okno
    zamyka się po sprzątnięciu wątku jak po zapisie, a odmowa ma dokąd trafić - zdanie paska
    gospodarza (`summary`) z powodem w języku UI i szczegółem systemu. Falsyfikator: zerowanie
    zamknięcia odłożonego w gałęzi odmowy albo wyjątku (okno zostaje wbrew Esc)."""
    import threading
    from horreum.item_reasons import blad_systemu
    con, dlg, root = _oferta_zapisu_na_qthread(tmp_path, ustawienia, monkeypatch)
    puszczony = threading.Event()
    prawdziwa = projection.repair_manifest
    blad = OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64)

    def _czeka_na_esc(*a, **k):
        if k.get("do_write"):
            assert puszczony.wait(10)
            if droga == "wyjatek":
                raise blad
        return prawdziwa(*a, **k)
    monkeypatch.setattr(projection, "repair_manifest", _czeka_na_esc)
    _klik(dlg.btn_apply)
    assert isinstance(dlg._apply_worker, pd_mod.ManifestWorker)
    QTest.keyClick(dlg, Qt.Key_Escape)
    assert dlg.isVisible() and dlg.progress_note.full_text() == i18n.t("proj.obj.closing_after_manifest")
    if droga == "odmowa":
        (root / "RC8_ASI2600MM" / "LIGHT" / "Ha" / "lb1.fits").unlink()
    puszczony.set()
    assert _czekaj(lambda: not dlg.isVisible())
    assert dlg._apply_thread is None and dlg._apply_worker is None and dlg.result() == QDialog.Rejected
    assert not (root / projection.MANIFEST_NAME).exists()
    powod = (pd_mod.tekst_powodu(blad_systemu(blad)) if droga == "wyjatek"
             else i18n.t("objchg.item.proj_manifest_incomplete", n=1))
    assert dlg.summary == i18n.t("proj.obj.status_manifest_failed", canon="NGC 6992", msg=powod, root=str(root))
    assert dlg.summary.szczegol == (i18n.t("proj.manifest_folder_tip", dir=str(root)) if droga == "odmowa"
                                    else pd_mod.wiersz_systemu(blad_systemu(blad)))
    con.close()


def test_esc_w_sondzie_przed_swiadkami_nie_czyta_manifestu(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-245: Esc w trakcie sondy DRY wydania obiektu na PRAWDZIWYM QThread - sonda kończy się
    anulowana, a świadkowie scalenia (`manifest_sources`: baza i manifest) NIE są czytani: okno
    zamyka się bez czekania na zbędny odczyt. Falsyfikator: `manifest_sources` przed sprawdzeniem
    anulowania."""
    import threading
    import time
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    dlg = _okno_rc8(con, ustawienia, tmp_path / "_WBPP" / "karta", off_thread=True)
    assert _czekaj(lambda: dlg._dry_worker is None and dlg._plan is not None)
    w_sondzie, czytane = threading.Event(), []
    prawdziwy_apply, prawdziwe_zrodla = projection.apply, projection.manifest_sources

    def _sonda_czeka_na_esc(*a, **k):
        if not k.get("do_apply"):
            w_sondzie.set()
            koniec = time.monotonic() + 10
            while not k["should_cancel"]() and time.monotonic() < koniec:
                time.sleep(0.01)
        return prawdziwy_apply(*a, **k)
    monkeypatch.setattr(projection, "apply", _sonda_czeka_na_esc)
    monkeypatch.setattr(projection, "manifest_sources", lambda *a: czytane.append(a) or prawdziwe_zrodla(*a))
    _klik(dlg.btn_dry)
    assert _czekaj(w_sondzie.is_set)
    QTest.keyClick(dlg, Qt.Key_Escape)
    assert not dlg.isVisible() and czytane == []
    assert _czekaj(lambda: dlg._dry_thread is None)              # wątek sondy sprzątnięty przed `close`
    con.close()


def test_brak_zlotej_akcji_na_wygaszonym_przycisku(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-245: złota waga (bold, wysokość, Enter) stoi WYŁĄCZNIE na aktywnym przycisku - po
    awarii wydania perspektywy, po udanym wydaniu perspektywy („Utworzono ✓” wygaszone) i po
    anulowanym wydaniu obiektu bez kompletu w celu nie ma jej nigdzie; świeża sonda z robotą stawia
    ją na „Utwórz”. Falsyfikator: `_waga_akcji` bez pytania o `isEnabled`."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")

    def waga(b):
        return (b.font().bold(), b.minimumHeight() == pd_mod._GOLD_HEIGHT, b.isDefault())

    def zadna(d):
        return waga(d.btn_apply) == waga(d.btn_open) == (False, False, False)
    con = db.open_db(str(tmp_path / "w.db"))
    ids = _seed_files(con, tmp_path, 2)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    dlg.show()
    assert dlg.btn_apply.isEnabled() and waga(dlg.btn_apply) == (True, True, True)
    prawdziwy_apply = projection.apply

    def _pada_w_wydaniu(*a, **k):
        if k.get("do_apply"):
            raise OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64)
        return prawdziwy_apply(*a, **k)
    monkeypatch.setattr(projection, "apply", _pada_w_wydaniu)
    _klik(dlg.btn_apply)                                 # wyjątek całej operacji (`_on_apply_failed`)
    assert dlg.btn_apply.text() == i18n.t("proj.btn_error") and zadna(dlg)
    monkeypatch.setattr(projection, "apply", prawdziwy_apply)
    _klik(dlg.btn_dry)
    assert waga(dlg.btn_apply) == (True, True, True)
    _klik(dlg.btn_apply)
    assert dlg.btn_apply.text() == i18n.t("proj.btn_created_ok") and zadna(dlg)
    dlg.reject()
    con.close()
    (tmp_path / "obj").mkdir()
    con, _ids = _obiekt_wydania(tmp_path / "obj")
    obj = _okno_rc8(con, ustawienia, tmp_path / "_WBPP" / "karta")
    assert obj.btn_apply.isEnabled() and obj._released_root is None
    w_biegu = []
    # Prawdziwe anulowanie w biegu (szpieg postępu `ApplyWorker`): po pierwszym pliku żądanie
    # przerwania, a waga w biegu - zapisana z wnętrza biegu.
    _spy_progress(monkeypatch, hook=lambda n, w: (w_biegu.append(zadna(obj)), w.request_cancel())
                  if n == 1 else None)
    _klik(obj.btn_apply)
    assert w_biegu == [True]                             # w biegu nie ma akcji ze złotem
    assert obj.btn_apply.text() == i18n.t("proj.btn_cancelled") and zadna(obj)
    obj.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_oferta_mowi_liczby_dopisania_bez_kopii_niepewnych_i_date_z_drzewa(jezyk, lang):
    """AR-245 i AR-240 (Qt-wolne `manifest_offer_lines`): zapis, który tylko zapomina id, ma
    neutralną głowę i NIE obiecuje dopisania; `dodane` daje własny wiersz z liczbą; klatki planu
    bez kopii i id bez dowodu - wiersze z liczbą zamiast odmowy; data z drzewa - wiersz źródła daty
    (nie „bez daty”), a manifest bez daty z samą różnicą `ts` - głowa „dopisze datę z drzewa”.
    EN bez polskich znaków. Falsyfikatory: głowa „dopisze brakujące” przy samym zapominaniu;
    `dodane` bez wiersza."""
    jezyk(lang)
    t = i18n.t
    drzewo = {"ts": "2026-10-09T14:57:23+00:00", "ts_source": projection.TS_SOURCE_TREE, "zestawy": {"A": {}}}

    def oferta(**kw):
        return projection.ManifestRepair("would-write", payload=kw.pop("payload", {"ts": "T1", "zestawy": {"A": {}}}),
                                         **kw)
    linie = pd_mod.manifest_offer_lines
    assert linie(oferta(stan="stale", roznice=("ids",), dropped=2)) == [
        t("proj.obj.manifest_stale"), t("proj.obj.manifest_will_keep", kept=0, dropped=2)]
    assert linie(oferta(stan="stale", roznice=("ids",), dodane=3)) == [
        t("proj.obj.manifest_stale"), t("proj.obj.manifest_will_add", n=3)]
    pelna = linie(oferta(stan="missing", bez_kopii=1, niepewne=2, payload=drzewo))
    assert pelna == [t("proj.obj.manifest_missing"), t("proj.obj.manifest_no_copy", n=1),
                     t("proj.obj.manifest_unproven_kept", n=2), t("proj.obj.manifest_ts_tree")]
    assert linie(oferta(stan="stale", roznice=("ts",), payload=drzewo)) == [
        t("proj.obj.manifest_stale_ts_tree"), t("proj.obj.manifest_ts_tree")]
    if lang == "en":
        for w in pelna + linie(oferta(stan="stale", roznice=("ids",), dodane=1)) + [t("proj.obj.manifest_stale_ts_tree")]:
            assert not set(w) & _POLSKIE, w


def test_wydanie_nad_uszkodzonym_manifestem_odmawia_ze_sciezka_pod_kursorem(qapp, tmp_path, ustawienia,
                                                                            monkeypatch):
    """AR-234: wydanie obiektu nad starym manifestem uszkodzonym (JSON) - krok
    manifestu odmawia `proj_manifest_damaged` (pliki leżą, stary plik bajt w bajt), głowa błędu z radą,
    pod kursorem ścieżka manifestu, zdanie paska ze szczegółem (AR-245), a świeża sonda po awarii mówi tę
    samą odmowę naprawy. Falsyfikator: tolerancyjny odczyt w kroku manifestu (nadpis uszkodzonego)."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card)
    dlg.combo_zestaw.setCurrentIndex(2)
    root = card / "OBJECTS" / "NGC_6992"
    root.mkdir(parents=True)
    (root / projection.MANIFEST_NAME).write_bytes(b"{")
    _klik(dlg.btn_dry)
    _klik(dlg.btn_apply)
    sciezka = str(root / projection.MANIFEST_NAME)
    zdanie = i18n.t("objchg.item.proj_manifest_damaged", detail="JSON")
    raport = dlg.report.toPlainText()
    assert raport.startswith(i18n.t("proj.manifest_error_head", msg=zdanie)), raport
    assert i18n.t("proj.obj.manifest_refused", msg=zdanie) in raport.split("\n"), raport
    assert dlg.report.toolTip() == i18n.t("proj.manifest_path_tip", path=sciezka)
    assert (root / projection.MANIFEST_NAME).read_bytes() == b"{"
    assert (root / "RC8_ASI2600MM" / "LIGHT" / "Ha" / "lb1.fits").exists()
    assert dlg.summary == i18n.t("proj.obj.status_failed", canon="NGC 6992", msg=zdanie, root=str(root))
    assert dlg.summary.szczegol == i18n.t("proj.manifest_path_tip", path=sciezka)
    dlg.reject()
    con.close()


def test_stojacy_manifest_po_awarii_oferta_mowi_czas_proby(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-245: manifest z wcześniejszego wydania STOI, a ponowne wydanie (brakujący plik) pada na kroku
    manifestu - świeża sonda po awarii liczy ofertę czasem TEJ próby (`czas_proby_dla`): głowa „niesie
    czas wcześniejszego wydania”, bez daty z drzewa; zapis stawia czas próby. Falsyfikator: sonda bez
    `ts=` (oferta `current` albo z datą z drzewa, a zapis z czasem próby)."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card)
    dlg.combo_zestaw.setCurrentIndex(2)
    _klik(dlg.btn_apply)
    root = card / "OBJECTS" / "NGC_6992"
    pierwszy = _manifest_okna(root)["ts"]
    (root / "RC8_ASI2600MM" / "LIGHT" / "Ha" / "lb1.fits").unlink()
    _klik(dlg.btn_dry)
    prawdziwy = _pada_krok_manifestu(monkeypatch)
    _klik(dlg.btn_apply)
    czas_proby = dlg._apply_now
    raport = dlg.report.toPlainText().split("\n")
    assert i18n.t("proj.obj.manifest_stale_ts") in raport, raport
    assert i18n.t("proj.obj.manifest_ts_tree") not in raport and i18n.t("proj.obj.manifest_no_ts") not in raport
    monkeypatch.setattr(projection, "_write_manifest", prawdziwy)
    _klik(dlg.btn_apply)
    nowy = _manifest_okna(root)
    assert nowy["ts"] == czas_proby != pierwszy and "ts_source" not in nowy
    dlg.reject()
    con.close()


_DROGI_KONCA = ["sukces", "anulowanie", "abort", "blad_kroku", "wyjatek", "manifest_zapisany",
                "manifest_odmowa", "manifest_blad", "manifest_bez_zmian"]


@pytest.mark.parametrize("droga", _DROGI_KONCA)
def test_zapadka_paska_kazdy_koniec_biegu_mowi_o_tym_biegu(qapp, tmp_path, ustawienia, monkeypatch, droga):
    """AR-245: zdanie paska gospodarza (`summary`) po KAŻDYM końcu biegu zapisu mówi o TYM biegu - wejście
    w bieg zeruje zdanie poprzedniego, a każdy slot końca (sukces, anulowanie, abort sondy, błąd kroku,
    wyjątek operacji, manifest zapisany / odmowa / błąd / bez zmian) stawia własne. Falsyfikator:
    `_apply_begin` bez zerowania albo slot końca bez zdania (pasek po zamknięciu mówiłby o poprzednim
    biegu)."""
    from horreum.item_reasons import blad_systemu
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card)
    dlg.combo_zestaw.setCurrentIndex(2)
    root = card / "OBJECTS" / "NGC_6992"
    blad = OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64)
    if droga.startswith("manifest_"):
        _klik(dlg.btn_apply)
        bajty = (root / projection.MANIFEST_NAME).read_bytes()
        (root / projection.MANIFEST_NAME).unlink()
        _klik(dlg.btn_dry)
        assert dlg.btn_apply.text() == i18n.t("proj.obj.btn_write_manifest")
    dlg.summary = "zdanie poprzedniego biegu"
    if droga == "anulowanie":
        _spy_progress(monkeypatch, hook=lambda n, w: w.request_cancel() if n == 1 else None)
    elif droga == "abort":
        monkeypatch.setattr(projection, "_verify_content", lambda src, dst, nbytes=65536: False)
    elif droga == "blad_kroku":
        _pada_krok_manifestu(monkeypatch)
    elif droga == "wyjatek":
        prawdziwy_apply = projection.apply
        monkeypatch.setattr(projection, "apply", lambda *a, **k: (_ for _ in ()).throw(blad) if k.get("do_apply")
                            else prawdziwy_apply(*a, **k))
    elif droga == "manifest_odmowa":
        (root / "RC8_ASI2600MM" / "LIGHT" / "Ha" / "lb1.fits").unlink()
    elif droga == "manifest_blad":
        prawdziwa = projection.repair_manifest

        def _pada_zapis(*a, **k):
            if k.get("do_write"):
                raise blad
            return prawdziwa(*a, **k)
        monkeypatch.setattr(projection, "repair_manifest", _pada_zapis)
    elif droga == "manifest_bez_zmian":
        (root / projection.MANIFEST_NAME).write_bytes(bajty)
    _klik(dlg.btn_apply)
    kanon, korzen = "NGC 6992", str(root)
    klasa = pd_mod.tekst_powodu(blad_systemu(blad))
    oczekiwane = {
        "sukces": i18n.t("proj.obj.status_summary", canon=kanon, files=i18n.t_plural("proj.files_linked", 3),
                         root=korzen),
        "anulowanie": i18n.t("proj.obj.status_cancelled", canon=kanon, word=i18n.t("proj.word_link_done"),
                             n=1, total=3, root=korzen),
        "abort": i18n.t("proj.obj.status_failed", canon=kanon, root=korzen,
                        msg=i18n.t("objchg.item.proj_first_link")),
        "blad_kroku": i18n.t("proj.obj.status_failed", canon=kanon, root=korzen,
                             msg=i18n.t("objchg.item.proj_manifest_failed", inner=klasa)),
        "wyjatek": i18n.t("proj.obj.status_failed", canon=kanon, root=korzen, msg=klasa),
        "manifest_zapisany": i18n.t("proj.obj.status_manifest", canon=kanon, root=korzen),
        "manifest_odmowa": i18n.t("proj.obj.status_manifest_failed", canon=kanon, root=korzen,
                                  msg=i18n.t("objchg.item.proj_manifest_incomplete", n=1)),
        "manifest_blad": i18n.t("proj.obj.status_manifest_failed", canon=kanon, root=korzen, msg=klasa),
        "manifest_bez_zmian": i18n.t("proj.obj.status_manifest_current", canon=kanon, root=korzen),
    }
    assert dlg.summary == oczekiwane[droga], (droga, dlg.summary)
    if droga == "manifest_odmowa":
        assert dlg.summary.szczegol == i18n.t("proj.manifest_folder_tip", dir=korzen)
    dlg.reject()
    con.close()


def test_wynik_zapisu_manifestu_spoza_kontraktu_to_blad_programu(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-245: slot wyniku zapisu manifestu zna `written`, `current`, odmowę i błąd - inny status
    (zapis bez `should_cancel` nie zwraca `cancelled`) to EXPECT, nie cichy „Bez zmian”."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    dlg = _okno_rc8(con, ustawienia, tmp_path / "_WBPP" / "karta")
    with pytest.raises(AssertionError, match="cancelled"):
        dlg._on_manifest_done(projection.ManifestRepair("cancelled"))
    dlg.reject()
    con.close()


def test_anulowane_wydanie_na_stol_nie_mowi_wydano_a_bieg_zeruje_zdanie(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-245: wejście w bieg zeruje zdanie paska poprzedniego biegu (w biegu `summary` None), a anulowane
    wydanie perspektywy mówi „Przerwano wydanie na stół … z …, reszta nietknięta”, nie „Wydano na stół”.
    Falsyfikatory: `_apply_begin` bez zerowania; anulowanie ze zdaniem sukcesu."""
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "an.db"))
    ids = _seed_files(con, tmp_path, 3)
    root = tmp_path / "_WBPP" / "feed"
    _target(ustawienia, root)
    w_biegu = []
    _spy_progress(monkeypatch, hook=lambda n, w: (w_biegu.append(dlg.summary), w.request_cancel())
                  if n == 1 else None)
    dlg = _dlg(con, ids)
    dlg.summary = "zdanie poprzedniego biegu"
    dlg._on_apply()
    assert w_biegu == [None]
    assert dlg.summary == i18n.t("proj.status_cancelled", word=i18n.t("proj.word_link_done"), n=1, total=3,
                                 root=str(root))
    con.close()
