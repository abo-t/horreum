"""Kopie bez zebranych faktów (0021) na powierzchniach GUI: zero wierszy Porządków, które porównują
zeznania kopii, znaczy przed pierwszą Dostawą „nie wiem" i ma tak mówić, a podpowiedź kopii bez
zeznania ma wskazywać drogę także wtedy, gdy pliku nie ma już na dysku. Okno offscreen, pliki
syntetyczne w `tmp_path`."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from horreum import db, repo, scan
from horreum.gui import grid as grid_mod, i18n, rows, tasks as tasks_mod
from horreum.gui.i18n_catalog import CATALOG

from test_copy_facts import NOW, _dwie_kopie


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def sprzed_migracji(tmp_path):
    """Jedna klatka, dwie kopie (CLS / L-Pro) wciągnięte „sprzed 0021": bez faktów kopii."""
    root, a, b = _dwie_kopie(tmp_path)
    con = db.open_db(str(tmp_path / "h.db"))
    for p in (a, b):
        rec = scan.scan_file(str(p))
        fid, _ = repo.upsert_frame(con, sha1_data=rec.sha1_data, kind="master_flat",
                                   filetype="xisf", camera_id=None, now=NOW)
        repo.add_location(con, frame_id=fid, volume="V", path=rec.path,
                          header_hash=rec.header_hash, now=NOW)
    yield con, fid, a, b
    con.close()


def _wiersz(tv, klucz):
    return next(tv.tasks.item(i) for i in range(tv.tasks.count())
                if tv.tasks.item(i).data(Qt.UserRole) == klucz)


def _podpowiedz_sciezki(view, frame_id):
    wiersz = next(i for i, r in enumerate(view.model._rows) if r.get("frame_id") == frame_id)
    kol = [k for _, k in grid_mod.BASE_COLS].index("path")
    return view.model.data(view.model.index(wiersz, kol), Qt.ToolTipRole)


def test_podpowiedz_kopii_bez_zeznania_wskazuje_obie_drogi(qapp, sprzed_migracji):
    """Kopia „obecna" w bazie może już nie mieć pliku na dysku - wtedy „Przyjmij nowe" jej nie
    uzupełni nigdy, a recepta z samą Dostawą prowadziła w ślepy zaułek. Zdanie mówi obie drogi,
    bo podpowiedź nie sprawdza dysku (udział SMB pod kursorem). Tu jedna z kopii zniknęła z dysku,
    a baza jeszcze o tym nie wie - dokładnie przypadek, którego dawne zdanie nie obejmowało.

    Nazwy miejsca i przycisku idą z katalogu, więc zdanie nie rozjedzie się z ekranem.
    Falsyfikator: wróć do zdania bez drugiej drogi → asercja o „Oznacz zniknięte" pada."""
    con, fid, a, _b = sprzed_migracji
    os.remove(a)
    view = grid_mod.FramesView(con, now_fn=None)
    try:
        tip = _podpowiedz_sciezki(view, fid)
        assert tip.count("zeznanie nagłówka jeszcze niezebrane") == 2
        droga = (f"jeśli pliku nie ma już na dysku - {i18n.t('nav.dostawa')} → "
                 f"„{i18n.t('pipeline.btn.mark_vanished')}”")
        assert tip.count(droga) == 2, tip
        # Dostawa jest drogą WARUNKOWĄ, nie obietnicą: przy kopii bez pliku „uzupełni je" było
        # nieprawdą (firsthand: po „Przyjmij nowe" skasowane kopie dalej bez zeznania).
        assert tip.count(f"gdy plik jest na dysku - {i18n.t('nav.dostawa')} → „Przyjmij nowe”") == 2
        assert "uzupełni" not in tip, tip
    finally:
        view.close()


def test_podpowiedz_kopii_bez_zeznania_parytet_EN(qapp, sprzed_migracji):
    """Wersja angielska niesie te same dwie drogi i te same pola wstawiane z katalogu."""
    con, fid, _a, _b = sprzed_migracji
    wpis = CATALOG["grid.tip.copy_unread"]
    for pole in ("{place}", "{mark}"):
        assert pole in wpis["pl"] and pole in wpis["en"]
    i18n.set_lang("en")
    view = grid_mod.FramesView(con, now_fn=None)
    try:
        tip = _podpowiedz_sciezki(view, fid)
        assert "header testimony not collected yet" in tip
        assert "Intake → “Mark vanished”" in tip, tip
        assert "if the file is on disk - Intake → “Take new”" in tip, tip
        assert "will fill" not in tip, tip
    finally:
        view.close()


def test_zero_porzadkow_przed_Dostawa_mowi_nie_wiem(qapp, sprzed_migracji):
    """Przed pierwszą Dostawą po migracji wiersze, które porównują zeznania kopii, nie mają czego
    porównać - ich zero znaczy „nie wiem". Wiersz mówi „?" i ile kopii jest bez zeznania (liczba
    WOŁANA z predykatu etapu, `scan.copy_facts_candidates`), nie pogrubia się i NIE wchodzi do
    plakietki: robotą jest Dostawa albo „Oznacz zniknięte", nie ten wiersz. Po zebraniu faktów wraca
    zwykła liczba - tu 1, bo kopie mówią różne FILTER, a wiersz drugi wraca do szarego „0".

    Falsyfikator: zdejmij gałąź „?" z `refresh_counts` → pierwsza asercja widzi „0  ›"."""
    con, _fid, _a, _b = sprzed_migracji
    tv = tasks_mod.TasksView(con)
    try:
        assert len(scan.copy_facts_candidates(con)) == 2
        plakietka = tv.refresh_counts()
        czeka = i18n.t_plural("tasks.copies_unread", 2)
        assert czeka == "? · 2 kopie bez zeznania"
        for klucz in ("copy_conflict_frames", "orphan_testimony_frames"):
            w = _wiersz(tv, klucz)
            assert w.data(rows.SECONDARY) == f"{czeka}  ›", klucz
            assert w.data(rows.STRONG) is False, "„?” nie krzyczy jak robota"
            assert w.foreground().color() != tasks_mod._DIM["fg"], "„?” nie udaje „nic do zrobienia”"
        zywe = [tv.tasks.item(i).data(Qt.UserRole) for i in range(tv.tasks.count())
                if tv.tasks.item(i).data(rows.STRONG)]
        assert plakietka == len(zywe) and "copy_conflict_frames" not in zywe

        s = scan.backfill_copy_facts(con, now=NOW)
        assert (s.written, s.remaining) == (2, 0)
        plakietka_po = tv.refresh_counts()
        konflikt = _wiersz(tv, "copy_conflict_frames")
        assert konflikt.data(rows.SECONDARY) == "1  ›" and konflikt.data(rows.STRONG) is True
        sierota = _wiersz(tv, "orphan_testimony_frames")
        assert sierota.data(rows.SECONDARY) == "0  ›"
        assert sierota.foreground().color() == tasks_mod._DIM["fg"]
        assert not sierota.toolTip(), "podpowiedź dróg gaśnie razem ze stanem „?”"
        assert plakietka_po == plakietka + 1, "zebrany rozjazd kopii jest robotą"
    finally:
        tv.close()


def test_wiersz_przy_kopiach_bez_pliku_nie_obiecuje_Dostawy(qapp, sprzed_migracji):
    """Firsthand: po „Przyjmij nowe" dwie skasowane kopie dalej bez zeznania, a wiersze mówiły, że
    „czekają na Dostawę" - Dostawa nie uzupełni kopii, której pliku nie ma, więc zdanie było
    nieprawdą, która prowadziła w pętlę. Wiersz mówi STAN („bez zeznania"), a podpowiedź obie drogi,
    obie WARUNKOWE: wiersz nie sprawdza dysku, rozstrzyga pass obecności. Tu oba pliki zniknęły
    z dysku, a baza jeszcze o tym nie wie.

    Falsyfikator: wróć do „czekają na Dostawę" → asercja o członie drugim pada; zdejmij podpowiedź
    → asercje o drogach padają."""
    con, _fid, a, b = sprzed_migracji
    os.remove(a)
    os.remove(b)
    tv = tasks_mod.TasksView(con)
    try:
        tv.refresh_counts()
        dostawa, oznacz = i18n.t("nav.dostawa"), i18n.t("pipeline.btn.mark_vanished")
        for klucz in ("copy_conflict_frames", "orphan_testimony_frames"):
            w = _wiersz(tv, klucz)
            assert "Dostaw" not in w.data(rows.SECONDARY), w.data(rows.SECONDARY)
            assert w.data(rows.SECONDARY).startswith("? · "), klucz
            tip = w.toolTip()
            assert f"Gdy plik jest na dysku - {dostawa} → „Przyjmij nowe”" in tip, tip
            assert f"Jeśli pliku nie ma już na dysku - {dostawa} → „{oznacz}”" in tip, tip
            # kolejność pytań człowieka: najpierw „plik jest", potem „pliku nie ma"
            assert tip.index("Gdy plik jest") < tip.index("Jeśli pliku nie ma"), tip
    finally:
        tv.close()


def test_wiersz_bez_zeznania_parytet_EN(qapp, sprzed_migracji):
    """Wersja angielska niesie ten sam stan i te same dwie drogi, a pola wstawiane z katalogu stoją
    w KAŻDEJ formie mnogiej obu języków (forma bez `{mark}` zgubiłaby drugą drogę dla jednej liczby)."""
    con, _fid, _a, _b = sprzed_migracji
    wpis = CATALOG["tasks.copies_unread_tip"]
    for jezyk in ("pl", "en"):
        for forma, tekst in wpis[jezyk].items():
            for pole in ("{n}", "{place}", "{mark}"):
                assert pole in tekst, (jezyk, forma, pole)
    i18n.set_lang("en")
    tv = tasks_mod.TasksView(con)
    try:
        tv.refresh_counts()
        w = _wiersz(tv, "copy_conflict_frames")
        assert w.data(rows.SECONDARY) == "? · 2 copies not yet read  ›"
        assert "If the file is on disk - Intake → “Take new”" in w.toolTip(), w.toolTip()
        assert "If the file is no longer on disk - Intake → “Mark vanished”" in w.toolTip()
    finally:
        tv.close()


def test_czlon_drugi_bez_zeznania_nie_szerszy_niz_dawny(qapp):
    """Człon drugi listy zadań nie jest elidowany i zabiera miejsce NAZWIE (lista ≤ 400 px), więc
    poprawka zdania nie ma prawa go poszerzyć. Porównanie WZGLĘDNE z dawnym członem, tym samym
    fontem, co delegat (pogrubiony, `strong=True`) - bez stałych pikseli."""
    from PySide6.QtGui import QFont, QFontMetrics
    tv = tasks_mod.TasksView(db.open_db(":memory:"))
    try:
        font = QFont(tv.tasks.font())
        font.setBold(True)
        fm = QFontMetrics(font)
        dawne = {"pl": "? · 22 kopie czekają na Dostawę  ›", "en": "? · 22 copies await Intake  ›"}
        for jezyk, stare in dawne.items():
            i18n.set_lang(jezyk)
            nowe = f"{i18n.t_plural('tasks.copies_unread', 22)}  ›"
            assert fm.horizontalAdvance(nowe) <= fm.horizontalAdvance(stare), (jezyk, nowe)
    finally:
        tv.close()


def test_niewiadome_zero_odmienia_liczbe_kopii():
    """Człon „?" jest frazą odmienianą (PL: one/few/many), bo mówi o liczbie kopii."""
    assert i18n.t_plural("tasks.copies_unread", 1) == "? · 1 kopia bez zeznania"
    assert i18n.t_plural("tasks.copies_unread", 5) == "? · 5 kopii bez zeznania"
    assert i18n.t_plural("tasks.copies_unread", 22) == "? · 22 kopie bez zeznania"
