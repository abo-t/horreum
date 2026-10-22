"""Etap faktów kopii mówi o dwóch robotach osobno (AR-315): kopie czekające na fakty i kopie FITS
czekające WYŁĄCZNIE na jednorazowe sprawdzenie bajtów nagłówka (po aktualizacji programu - migracja
0046). Napis gestu, podpowiedź, linia powodu, czas (szacunek przed biegiem i czas pozostały w biegu)
i raport etapu. Okno offscreen, bazy i pliki syntetyczne w `tmp_path`."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from horreum import db, repo, scan
from horreum.gui import i18n
from horreum.gui.pipeline import (REASON_COPY_FACTS, PipelineView, PipelineWorker, sekundy_pozostale,
                                  zdanie_czasu)

from test_copy_facts import NOW, _FLAT, _baza_sprzed_0021, _fits, _xisf

_POLSKIE = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ„")     # „ - polski cudzysłów otwierający (EN: “…”)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _baza_syntetyczna(tmp_path, fakty, bajty):
    """Baza bez plików: `fakty` pojedynczych kopii XISF (klasa faktów) i `bajty` pojedynczych kopii FITS
    niezbadanych (same bajty - pojedynczego FITS-a faktów nie ma z czym porównać)."""
    path = str(tmp_path / "s.db")
    con = db.open_db(path)
    for i in range(fakty):
        fid, _ = repo.upsert_frame(con, sha1_data=f"x{i:039d}", kind="light", filetype="xisf",
                                   camera_id=None, now=NOW)
        repo.add_location(con, frame_id=fid, volume="V", path=f"X:\\L\\x{i}.xisf",
                          header_hash=f"hx{i}", now=NOW)
    for i in range(bajty):
        fid, _ = repo.upsert_frame(con, sha1_data=f"f{i:039d}", kind="light", filetype="fits",
                                   camera_id=None, now=NOW)
        repo.add_location(con, frame_id=fid, volume="V", path=f"X:\\L\\f{i}.fits",
                          header_hash=f"hf{i}", now=NOW)
    con.close()
    return path


def _czekaj_na_etap(view, timeout_ms=20000):
    """Odczekaj etap w wątku: pętla kończy się na `running_changed(False)` - czyli po sprzątnięciu."""
    petla = QEventLoop()
    view.running_changed.connect(lambda r: petla.quit() if r is False else None)
    QTimer.singleShot(timeout_ms, petla.quit)
    petla.exec()


# Odmiana 1/2/5/12/22 dosłownie (PL: one/few/many, 12 zawsze many, 22 few) - zdania z katalogu.
_PL_FAKTY = {1: "1 kopia czeka na fakty", 2: "2 kopie czekają na fakty", 3: "3 kopie czekają na fakty",
             5: "5 kopii czeka na fakty", 12: "12 kopii czeka na fakty", 22: "22 kopie czekają na fakty"}
_PL_BAJTY = {1: "1 kopia FITS czeka na jednorazowe", 2: "2 kopie FITS czekają na jednorazowe",
             3: "3 kopie FITS czekają na jednorazowe", 5: "5 kopii FITS czeka na jednorazowe",
             12: "12 kopii FITS czeka na jednorazowe", 22: "22 kopie FITS czekają na jednorazowe"}
_PL_POWOD_BAJTY = {1: "1 kopia FITS czeka na jednorazowe sprawdzenie",
                   3: "3 kopie FITS czekają na jednorazowe sprawdzenie",
                   5: "5 kopii FITS czeka na jednorazowe sprawdzenie",
                   12: "12 kopii FITS czeka na jednorazowe sprawdzenie",
                   2: "2 kopie FITS czekają na jednorazowe sprawdzenie",
                   22: "22 kopie FITS czekają na jednorazowe sprawdzenie"}


def _en_fakty(n):
    return "1 copy is waiting for its facts" if n == 1 else f"{n} copies are waiting for their facts"


def _en_bajty(n):
    return ("1 FITS copy is waiting for a one-time check" if n == 1
            else f"{n} FITS copies are waiting for a one-time check")


@pytest.mark.parametrize("jezyk", ["pl", "en"])
@pytest.mark.parametrize("fakty, bajty", [(1, 22), (2, 12), (5, 5), (12, 2), (22, 1), (0, 3), (3, 0)])
def test_przycisk_podpowiedz_powod_rozdzielaja_fakty_od_bajtow(qapp, tmp_path, fakty, bajty, jezyk):
    """Napis gestu mówi, co gest zrobi (fakty / bajty / oba), podpowiedź i linia powodu - ile kopii
    czeka na którą robotę (odmiana PL 1/2/5/12/22), że sprawdzenie bajtów jest jednorazowe po
    aktualizacji, i ile to potrwa; człon roboty, która nie czeka, nie występuje.
    Falsyfikator: podpowiedź bez członu bajtów; `t` zamiast `t_plural`; stały napis gestu."""
    i18n.set_lang(jezyk)
    view = PipelineView(_baza_syntetyczna(tmp_path, fakty, bajty), now_fn=lambda: NOW)
    try:
        napis = view.btn_copy_facts.text()
        tip = view.btn_copy_facts.toolTip()
        view.show_reason(REASON_COPY_FACTS)
        powod = view.lbl_reason.text()
        assert not view.btn_copy_facts.isHidden() and not view.lbl_reason.isHidden()
        if jezyk == "pl":
            assert napis == {(True, True): f"Zbierz fakty kopii ({fakty}) i sprawdź bajty ({bajty})",
                             (False, True): f"Sprawdź bajty nagłówków ({bajty})",
                             (True, False): f"Zbierz fakty kopii ({fakty})"}[(fakty > 0, bajty > 0)]
            czlon_fakty, czlon_bajty = _PL_FAKTY.get(fakty, "\0"), _PL_BAJTY.get(bajty, "\0")
            jak, czas = "Gest czyta same nagłówki (poniżej minuty)", "poniżej minuty"
            powod_fakty = f"Zebrać fakty kopii: {czlon_fakty.replace(' na fakty', '')}"
            powod_bajty = "Sprawdzić bajty nagłówków: " + _PL_POWOD_BAJTY.get(bajty, "\0")
            assert ("wiersz „Nagłówek z bajtem spoza ASCII” w Porządkach mówi „?”" in powod) == (bajty > 0)
        else:
            assert napis == {(True, True): f"Collect copy facts ({fakty}) and check bytes ({bajty})",
                             (False, True): f"Check header bytes ({bajty})",
                             (True, False): f"Collect copy facts ({fakty})"}[(fakty > 0, bajty > 0)]
            czlon_fakty, czlon_bajty = _en_fakty(fakty), _en_bajty(bajty)
            jak, czas = "This reads headers only (under a minute)", "under a minute"
            powod_fakty = f"Collect copy facts: {fakty} cop"
            powod_bajty = (f"Check header bytes: {bajty} FITS cop")
            assert not set(tip + powod + napis) & _POLSKIE, (tip, powod, napis)
        assert (czlon_fakty in tip) == (fakty > 0), tip
        assert (czlon_bajty in tip) == (bajty > 0), tip
        assert tip.endswith("."), tip
        assert jak in tip and tip.index(jak) > max(
            tip.find(czlon_fakty) if fakty else -1, tip.find(czlon_bajty) if bajty else -1), tip
        if fakty:
            assert powod.startswith(powod_fakty), powod
        else:
            assert powod.startswith(powod_bajty), powod
        assert (powod_bajty in powod) == (bajty > 0), powod
        assert powod.endswith(f"„{napis}” zrobi to bez skanu ({czas})." if jezyk == "pl"
                              else f"“{napis}” does it with no scan ({czas})."), powod
    finally:
        view.close()


def test_szacunek_czasu_ze_stalej_i_z_tempa():
    """Do 200 zrobionych kopii czas pozostały liczy stała pomiaru (30 ms na kopię), od 200 - tempo tego
    biegu; zdanie zaokrągla do pełnych minut (połowa w górę), poniżej pół minuty mówi „poniżej minuty”.
    Falsyfikator: zawsze stała; próg `>` zamiast `>=`; stała 25 ms."""
    assert sekundy_pozostale(199, 1199, 100.0) == pytest.approx(30.0)
    assert sekundy_pozostale(200, 1200, 100.0) == pytest.approx(500.0)
    assert sekundy_pozostale(0, 15598, 0.0) == pytest.approx(467.94)
    assert sekundy_pozostale(5, 3, 1.0) == 0
    i18n.set_lang("pl")
    assert [zdanie_czasu(s) for s in (0, 29, 30, 89, 90, 468)] == [
        "poniżej minuty", "poniżej minuty", "ok. 1 min", "ok. 1 min", "ok. 2 min", "ok. 8 min"]
    i18n.set_lang("en")
    assert [zdanie_czasu(s) for s in (29, 468)] == ["under a minute", "about 8 min"]


def _same_bajty_na_dysku(tmp_path, n):
    """`n` pojedynczych kopii FITS na dysku, wciągniętych bez zbadania bajtów (jak sprzed 0046)."""
    root = tmp_path / "ARCH"
    pliki = [_fits(root / f"k{i}.fits", "Ha", n=i + 1) for i in range(n)]
    _baza_sprzed_0021(tmp_path, pliki).close()
    return str(tmp_path / "h.db"), root, pliki


def test_postep_etapu_mowi_czas_pozostaly(qapp, tmp_path):
    """Prawdziwy etap z gestu: linia postępu mówi, ile zostało („zostało poniżej minuty”). Teksty linii
    zbierane podmianą `setText` NA INSTANCJI etykiety (metoda niepodpięta pod sygnał, wołana ze slotu
    postępu w wątku okna). Falsyfikator: gałąź postępu faktów kopii bez `{eta}`."""
    i18n.set_lang("pl")
    db_path, _root, _pliki = _same_bajty_na_dysku(tmp_path, 3)
    view = PipelineView(db_path, now_fn=lambda: NOW)
    teksty = []
    prawdziwy = view.lbl_counts.setText

    def _set_text(tekst):
        teksty.append(tekst)
        prawdziwy(tekst)
    view.lbl_counts.setText = _set_text
    try:
        assert view.btn_copy_facts.text() == "Sprawdź bajty nagłówków (3)"
        view.btn_copy_facts.click()
        _czekaj_na_etap(view)
        postep = [t for t in teksty if t.startswith("Nagłówki kopii ")]
        assert postep and postep[0].startswith("Nagłówki kopii 1/3 · uzupełnione 1 · zostało poniżej "
                                               "minuty · "), teksty
        assert postep[-1].startswith("Nagłówki kopii 3/3 · uzupełnione 3 · zostało poniżej minuty · "), teksty
    finally:
        view.close()


def test_raport_etapu_mowi_sprawdzone_bajty(qapp, tmp_path):
    """Gest na kopii XISF (fakty) i dwóch kopiach FITS sprzed 0046 (same bajty): log mówi o faktach
    i o bajtach osobno; formater mówi też o kopii, której bajtów nie sprawdzono (dalszy HDU), w obu
    językach. Falsyfikator: raport bez członu bajtów - „uzupełniono 3 z 3”."""
    i18n.set_lang("pl")
    root = tmp_path / "ARCH"
    x = _xisf(root / "x.xisf", _FLAT)
    pliki = [x, _fits(root / "a.fits", "Ha", n=1), _fits(root / "b.fits", "Ha", n=2)]
    _baza_sprzed_0021(tmp_path, pliki).close()
    view = PipelineView(str(tmp_path / "h.db"), now_fn=lambda: NOW)
    try:
        assert view.btn_copy_facts.text() == "Zbierz fakty kopii (1) i sprawdź bajty (2)"
        view.btn_copy_facts.click()
        _czekaj_na_etap(view)
        assert view.lbl_summary.text().split("\n")[0] == (
            "[fakty kopii] uzupełniono 1 z 1 · sprawdzono bajty nagłówka 2 z 2"), view.lbl_summary.text()
        s = scan.CopyFactsSummary(rows=4, read=4, written=3, rows_bytes=4, bytes_checked=3,
                                  bytes_unchecked=1, remaining=1)
        assert view._format_result("copy_facts", s) == (
            "[fakty kopii] sprawdzono bajty nagłówka 3 z 4 · bajtów nie sprawdzono 1 (dalszy HDU nie "
            "do doczytania - czeka) · czeka 1")
        i18n.set_lang("en")
        assert view._format_result("copy_facts", s) == (
            "[copy facts] header bytes checked 3 of 4 · bytes not checked 1 (a further HDU cannot be "
            "read - waiting) · waiting 1")
    finally:
        view.close()


def test_zlota_akcja_bada_bajty_tym_samym_etapem(qapp, tmp_path):
    """„Przyjmij nowe” na korzeniu z kopiami FITS sprzed 0046 (skan je pomija - ta sama brama
    przyrostowa) bada ich bajty tym samym etapem faktów kopii, a raport etapu mówi to tym samym
    formaterem co gest."""
    i18n.set_lang("pl")
    db_path, root, _pliki = _same_bajty_na_dysku(tmp_path, 2)
    w = PipelineWorker(db_path, now_fn=lambda: NOW)
    w.configure("all", root=str(root), volume="V", drive_letter=None, tier=None)
    done, failed = {}, []
    w.stage_done.connect(lambda n, r: done.setdefault(n, r))
    w.failed.connect(lambda n, m: failed.append((n, m)))
    w.run()
    assert failed == []
    assert list(done)[:2] == ["scan", "copy_facts"], list(done)
    assert done["scan"].frames_new == 0
    s = done["copy_facts"]
    assert (s.rows_bytes, s.bytes_checked, s.rows_facts) == (2, 2, 0)
    view = PipelineView(db_path, now_fn=lambda: NOW)
    try:
        assert view._format_result("copy_facts", s) == "[fakty kopii] sprawdzono bajty nagłówka 2 z 2"
        assert view.btn_copy_facts.isHidden()
    finally:
        view.close()


@pytest.mark.parametrize("jezyk", ["pl", "en"])
def test_kopia_fits_czekajaca_na_obie_roboty_liczy_sie_w_obu(qapp, tmp_path, jezyk):
    """Klatka FITS o dwóch kopiach (fakty I bajty), pojedynczy FITS (same bajty) i XISF (same fakty):
    napis, podpowiedź i linia powodu mówią o PEŁNYCH robotach - 3 na fakty i 3 na bajty - a gest czyta
    4 kopie (każdą raz). Falsyfikator: bajty bez kopii czekających też na fakty → „sprawdź bajty (1)”;
    liczba kopii jako suma robót → 6."""
    i18n.set_lang(jezyk)
    path = _baza_syntetyczna(tmp_path, 1, 1)
    con = db.open_db(path)
    fid, _ = repo.upsert_frame(con, sha1_data="p" * 40, kind="light", filetype="fits", camera_id=None, now=NOW)
    for nazwa in ("pa", "pb"):
        repo.add_location(con, frame_id=fid, volume="V", path=f"X:\\L\\{nazwa}.fits", header_hash=f"h{nazwa}",
                          now=NOW)
    con.close()
    view = PipelineView(path, now_fn=lambda: NOW)
    try:
        view.show_reason(REASON_COPY_FACTS)
        napis, tip, powod = view.btn_copy_facts.text(), view.btn_copy_facts.toolTip(), view.lbl_reason.text()
        assert view._copy_facts_waiting == 4 and not view.btn_copy_facts.isHidden()
        if jezyk == "pl":
            assert napis == "Zbierz fakty kopii (3) i sprawdź bajty (3)"
            assert "3 kopie czekają na fakty" in tip and "3 kopie FITS czekają na jednorazowe sprawdzenie" in tip
            assert "Sprawdzić bajty nagłówków: 3 kopie FITS czekają" in powod, powod
        else:
            assert napis == "Collect copy facts (3) and check bytes (3)"
            assert "3 copies are waiting for their facts" in tip and "3 FITS copies are waiting for" in tip
            assert "Check header bytes: 3 FITS copies" in powod, powod
    finally:
        view.close()
