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
        # AR-28 (a): „Oznacz zniknięte" pojawia się dopiero po sprawdzeniu obecności - recepta
        # ma oba kroki, inaczej w świeżej sesji wskazuje przycisk, którego nie ma.
        droga = (f"jeśli pliku nie ma już na dysku - {i18n.t('nav.dostawa')} → "
                 f"„{i18n.t('pipeline.btn.presence')}” → "
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
    for pole in ("{place}", "{check}", "{mark}"):
        assert pole in wpis["pl"] and pole in wpis["en"]
    i18n.set_lang("en")
    view = grid_mod.FramesView(con, now_fn=None)
    try:
        tip = _podpowiedz_sciezki(view, fid)
        assert "header testimony not collected yet" in tip
        assert "Intake → “Check presence” → “Mark vanished”" in tip, tip
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
        sprawdz = i18n.t("pipeline.btn.presence")
        for klucz in ("copy_conflict_frames", "orphan_testimony_frames"):
            w = _wiersz(tv, klucz)
            assert "Dostaw" not in w.data(rows.SECONDARY), w.data(rows.SECONDARY)
            assert w.data(rows.SECONDARY).startswith("? · "), klucz
            tip = w.toolTip()
            assert f"Gdy plik jest na dysku - {dostawa} → „Przyjmij nowe”" in tip, tip
            assert (f"Jeśli pliku nie ma już na dysku - {dostawa} → „{sprawdz}” → „{oznacz}”"
                    in tip), tip
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
        assert ("If the file is no longer on disk - Intake → “Check presence” → “Mark vanished”"
                in w.toolTip())
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


def _bez_faktow_kopii(con, pliki):
    """Kopie wciągnięte klingą bez faktów (jak sprzed 0021): frame per sha1 danych."""
    for p in pliki:
        rec = scan.scan_file(str(p))
        fid, _ = repo.upsert_frame(con, sha1_data=rec.sha1_data, kind="master_flat",
                                   filetype=scan._filetype(rec.path), camera_id=None, now=NOW)
        repo.add_location(con, frame_id=fid, volume="V", path=rec.path, mtime=rec.mtime,
                          header_hash=rec.header_hash, now=NOW)


def test_pojedynczy_XISF_bez_faktow_nie_zamienia_zera_w_nie_wiem(qapp, tmp_path):
    """Kopia XISF o JEDNEJ lokacji jest kandydatem uzupełnienia (liczba obrazów), ale jej fakty nie
    zmienią żadnej z dwóch liczb, które porównują kopie jednej klatki. Licznik „?" pyta więc
    predykat porównywalnych kandydatów u jego właściciela (`scan.copy_facts_candidates(...,
    porownywalne=True)`) - na kopii archiwum 412 z 550 kandydatów to takie XISF.

    Falsyfikator: licz `len(scan.copy_facts_candidates(con))` → wiersze pokazują „?"."""
    from test_copy_facts import _FLAT, _xisf
    con = db.open_db(str(tmp_path / "s.db"))
    _bez_faktow_kopii(con, [_xisf(tmp_path / "S" / "solo.xisf", _FLAT, payload=b"\x09" * 32)])
    tv = tasks_mod.TasksView(con)
    try:
        assert len(scan.copy_facts_candidates(con)) == 1
        tv.refresh_counts()
        for klucz in ("copy_conflict_frames", "orphan_testimony_frames"):
            w = _wiersz(tv, klucz)
            assert w.data(rows.SECONDARY) == "0  ›", (klucz, w.data(rows.SECONDARY))
            assert not w.toolTip(), klucz
    finally:
        tv.close()
    con.close()


def test_czesciowe_fakty_licza_dolna_granice_N_plus(qapp, tmp_path):
    """Jedna klatka ma już fakty obu kopii (i niezgodne FILTER - liczba 1), druga czeka z dwiema
    kopiami bez faktów. „1" udawało liczbę dokładną, a jest dolną granicą: wiersz mówi „1+" i ile
    kopii jest bez zeznania, z tą samą receptą dróg co „?" - a klik prowadzi do perspektywy, bo
    tam JEST jedna klatka do obejrzenia. Wiersz, którego liczba to zero, zostaje przy „?".

    Falsyfikator: zawęź człon do `n == 0` → pierwsza asercja widzi „1  ›"."""
    from test_copy_facts import _FLAT, _xisf
    root, a, b = _dwie_kopie(tmp_path)
    con = db.open_db(str(tmp_path / "c.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)                    # fakty: CLS / L-Pro
    _bez_faktow_kopii(con, [
        _xisf(tmp_path / "Q" / "A" / "q.xisf", _FLAT, payload=b"\x0b" * 32),
        _xisf(tmp_path / "Q" / "B" / "q.xisf", _FLAT, payload=b"\x0b" * 32)])
    tv = tasks_mod.TasksView(con)
    try:
        assert len(scan.copy_facts_candidates(con, porownywalne=True)) == 2
        tv.refresh_counts()
        w = _wiersz(tv, "copy_conflict_frames")
        assert w.data(rows.SECONDARY) == "1+ · 2 kopie bez zeznania  ›", w.data(rows.SECONDARY)
        assert w.data(rows.STRONG) is True, "jest klatka do obejrzenia - to robota"
        tip = w.toolTip()
        assert f"Gdy plik jest na dysku - {i18n.t('nav.dostawa')} → „Przyjmij nowe”" in tip, tip
        assert f"„{i18n.t('pipeline.btn.stacks')}”" in tip, tip
        assert tip.splitlines()[-1].endswith(f"{i18n.t('nav.zbiory')}."), tip
        perspektywy = []
        tv.open_collection.connect(perspektywy.append)
        tv._on_task_clicked(w)
        assert perspektywy == [grid_mod.PRESET_COPY_CONFLICT]
        sierota = _wiersz(tv, "orphan_testimony_frames")
        assert sierota.data(rows.SECONDARY).startswith("? · 2 kopie"), sierota.data(rows.SECONDARY)
        assert sierota.toolTip().splitlines()[-1].endswith(f"{i18n.t('nav.dostawa')}.")
    finally:
        tv.close()
    con.close()


def test_recepta_wymienia_droge_Stosy(qapp, sprzed_migracji):
    """Kopie stosów spod korzenia stosów dostają fakty WYŁĄCZNIE drogą „Stosy" (`_stacks` →
    `_copy_facts` na korzeniu stosów) - „Przyjmij nowe" chodzi po archiwum. Recepta wymienia obie
    drogi warunkowo (wiersz nie zna korzenia stosów), nazwę gestu bierze z katalogu w KAŻDEJ formie
    obu języków."""
    for jezyk in ("pl", "en"):
        for forma, tekst in CATALOG["tasks.copies_unread_tip"][jezyk].items():
            assert "{stacks}" in tekst and "{dest}" in tekst, (jezyk, forma)
    con, _fid, _a, _b = sprzed_migracji
    tv = tasks_mod.TasksView(con)
    try:
        tv.refresh_counts()
        tip = _wiersz(tv, "copy_conflict_frames").toolTip()
        assert (f"Gdy kopia leży pod korzeniem stosów - {i18n.t('nav.dostawa')} → "
                f"„{i18n.t('pipeline.btn.stacks')}”") in tip, tip
    finally:
        tv.close()


def test_niewiadome_zero_odmienia_liczbe_kopii():
    """Człon „?" jest frazą odmienianą (PL: one/few/many), bo mówi o liczbie kopii."""
    assert i18n.t_plural("tasks.copies_unread", 1) == "? · 1 kopia bez zeznania"
    assert i18n.t_plural("tasks.copies_unread", 5) == "? · 5 kopii bez zeznania"
    assert i18n.t_plural("tasks.copies_unread", 22) == "? · 22 kopie bez zeznania"
    assert i18n.t_plural("tasks.copies_partial", 1, m=3) == "3+ · 1 kopia bez zeznania"
    assert i18n.t_plural("tasks.copies_partial", 5, m=1) == "1+ · 5 kopii bez zeznania"


def test_kopia_nowszej_reguly_nie_obiecuje_odpowiedzi_po_Dostawie(qapp, sprzed_migracji):
    """AR-50 (3): kopia z faktami reguły NOWSZEJ niż binarka (AR-33) liczy się w „?”, ale Dostawa
    tej wersji jej nie uzupełni. Podpowiedź mówi to osobnym zdaniem z liczbą takich kopii; bez
    takich kopii zdania nie ma.

    Falsyfikator: zdejmij dopisek z `grid.zdanie_kopii_bez_zeznania` → pierwsza asercja pada."""
    from horreum.resolve.headers import COPY_TESTIMONY_RULE
    con, _fid, _a, _b = sprzed_migracji
    tv = tasks_mod.TasksView(con)
    try:
        tv.refresh_counts()
        nowsza = i18n.t_plural("tasks.copies_newer_rule_tip", 1)
        assert nowsza not in _wiersz(tv, "copy_conflict_frames").toolTip()
        scan.backfill_copy_facts(con, now=NOW)
        with con:
            con.execute("UPDATE location SET hdr_rule = ? WHERE id = (SELECT min(id) FROM location)",
                        (COPY_TESTIMONY_RULE + 1,))
        tv.refresh_counts()
        w = _wiersz(tv, "copy_conflict_frames")
        assert w.data(rows.SECONDARY).startswith("? · 1 "), w.data(rows.SECONDARY)
        assert w.toolTip().endswith("\n" + nowsza), w.toolTip()
        assert len(scan.copy_facts_candidates(con)) == 0, "sterownik jej nie nadpisuje"
    finally:
        tv.close()
