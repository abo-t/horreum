"""Ogon szuflady zapisu i recept Zbiorów (AR-207, AR-205, AR-195, AR-196) - testy sterujące realnym
oknem Qt (offscreen), kliki prawdziwe.

Pilnujemy: kolumna podglądu chowa się od razu po zapisie szuflady i nie wraca przy przyłożeniu ani
przy sorcie w trakcie składu, a świeży podgląd nie jest schowany; uchwyt zapisu w biegu odpowiada
`False` każdemu odbiorcy, a odbiorcy bez sygnatury odmawia `TypeError`; zdjęcie i stawianie podglądu
zostawiają zaznaczenie (całego widoku i części) - cel gestu się nie zmienia, a „Wyczyść podgląd” bez
podglądu nie przebudowuje tabeli; licznik paska liczy klatki po obu stronach; etykieta celu panelu
nazw i podpowiedź blokady stagingu w języku UI; cofnięcie uwag poza widokiem jednym członem recepty;
cel na następny obraz po geście w perspektywie „Rodowód do potwierdzenia”."""
import os
import time
from functools import partial

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QThread, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from horreum import db, repo
from horreum.gui import grid as grid_mod, i18n, queries
from horreum.gui.note_dialog import NoteIntent
from horreum.gui.wb_worker import WritebackRunner, WritebackWorker

from test_gui_pola_w_tle import _klik_komorki, _klik_przycisku, _odczekaj_debounce, _zaznaczone
from test_gui_zaznaczenie_przebudowy import _klik_naglowka, nazwy, pliki  # noqa: F401
from test_gui_znajdz import con, okno, recepty, strona  # noqa: F401

NOW = "2026-10-16T12:00:00"
_POLSKIE = set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def jezyk():
    yield i18n.set_lang
    i18n.set_lang("pl")


def _czekaj(warunek, opis, s=30):
    """Pętla zdarzeń do warunku (skład zbioru w tle) - `processEvents` + `sleep`, nie `qWait`."""
    koniec = time.monotonic() + s
    while not warunek():
        if time.monotonic() > koniec:
            raise AssertionError(f"bezpiecznik {s} s: {opis}")
        QCoreApplication.processEvents(QEventLoop.AllEvents, 50)
        time.sleep(0.005)


def _przycisk(pasek, klucz):
    """Przycisk paska po napisie z katalogu („Wyczyść podgląd” nie jest atrybutem paska)."""
    return next(b for b in pasek.findChildren(QPushButton) if b.text() == i18n.t(klucz))


def _staging_makra(view):
    _klik_przycisku(view.sel_bar.btn_macro)
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_expr.setText("EQ6")
    _klik_przycisku(view.macro_bar.btn_stage)


# ============================================================ AR-207 - podgląd po zapisie


@pytest.fixture
def w_tle(qapp, tmp_path, monkeypatch):
    """Widok gospodarza (skład zbioru w `ZbiorWorker`, `pola_poza_watkiem=True`) nad trzema lightami
    FITS, zapis szuflady inline. Brama na składzie (`grid_workers._sklad_zbioru`): uzbrojona trzyma
    skład po zapisie w drodze, aż test ją otworzy - okno między zapisem a przyłożeniem jest stałe."""
    import threading
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    from horreum.gui import grid_workers
    from test_gui_pola_w_tle import _czekaj_na_pola
    con = db.open_db(str(tmp_path / "t.db"))
    for i in (1, 2, 3):
        p = tmp_path / f"t{i}.fits"
        hdu = fits.PrimaryHDU(data=np.full((4, 4), i, dtype=np.int16))
        hdu.header["TELESCOP"] = "RC8"
        hdu.header["IMAGETYP"] = "Light"
        hdu.writeto(str(p))
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary(),
                           pochodzenie=repo.ZEWNETRZNE)
    brama, uzbrojona = threading.Event(), threading.Event()
    prawdziwy = grid_workers._sklad_zbioru

    def _sklad(c, stan, przerwij=lambda: None):
        if uzbrojona.is_set():
            brama.wait(30)
        return prawdziwy(c, stan, przerwij)
    monkeypatch.setattr(grid_workers, "_sklad_zbioru", _sklad)
    view = grid_mod.FramesView(con, now_fn=lambda: NOW, pola_poza_watkiem=True)
    view._writeback_async = False
    view.resize(1400, 800)
    view.show()
    _czekaj_na_pola(view)
    yield view, brama, uzbrojona
    brama.set()
    _czekaj(lambda: not view._zbior_w_drodze(), "skład zbioru po teście")
    view.zatrzymaj_pola()
    view.close()
    con.close()


def test_po_zapisie_kolumna_podgladu_znika_od_razu_i_nie_wraca_przy_sorcie(w_tle):
    """„Zapisz” w szufladzie: zaraz po zapisie (skład zbioru w drodze) kolumna podglądu jest schowana -
    mówiłaby „do zapisania” o tym, co commit zapisał; sort klikiem w nagłówek w trakcie składu jej
    nie odsłania; po przyłożeniu podgląd zdjęty. Falsyfikatory: bez schowania w `_after_commit`;
    `_ukryj_kolumny` bez podglądu zapisanego (sort odsłania kolumnę)."""
    view, brama, uzbrojona = w_tle
    _staging_makra(view)
    kolumna = view.model._preview_col()
    assert kolumna is not None and not view.table.isColumnHidden(kolumna)
    uzbrojona.set()
    _klik_przycisku(view.drawer.btn_commit)
    assert view._zbior_w_drodze(), "skład po zapisie w drodze - test mierzy okno przed przyłożeniem"
    assert view.model._preview_active() and view.table.isColumnHidden(view.model._preview_col())
    resety = []
    view.model.modelReset.connect(lambda: resety.append(1))
    _klik_naglowka(view, view.model.base_col("path"))
    assert resety, "sort nie przebudował modelu - test nic by nie mierzył"
    assert view.model._preview_active() and view.table.isColumnHidden(view.model._preview_col())
    brama.set()
    _czekaj(lambda: not view._zbior_w_drodze(), "przyłożenie zbioru po zapisie")
    assert not view.model._preview_active()


def test_po_zapisie_wyczysc_i_nowy_staging_pokazuje_kolumne(w_tle):
    """Zapis, „Wyczyść podgląd” w trakcie składu, potem nowy staging: świeży podgląd STOI widoczny -
    schowany jest wyłącznie podgląd zapisany (obiekt podglądu modelu), nie każdy następny.
    Falsyfikator: flaga schowania bez tożsamości podglądu (zostaje do końca sesji)."""
    view, brama, uzbrojona = w_tle
    _staging_makra(view)
    uzbrojona.set()
    _klik_przycisku(view.drawer.btn_commit)
    _klik_przycisku(_przycisk(view.macro_bar, "grid.action.clear_preview"))
    uzbrojona.clear()
    brama.set()
    _czekaj(lambda: not view._zbior_w_drodze(), "przyłożenie zbioru po zapisie")
    view.macro_bar.asg_expr.setText("EQ8")
    _klik_przycisku(view.macro_bar.btn_stage)
    kolumna = view.model._preview_col()
    assert kolumna is not None and not view.table.isColumnHidden(kolumna)


# ============================================================ AR-207 - uchwyt zapisu


def test_uchwyt_w_biegu_odmawia_bez_wyjatku_kazdemu_odbiorcy(qapp):
    """Operacja w biegu: `start` odpowiada `False` także odbiorcy porażki ze złą arnością - wołający
    nie dostaje wtedy callbacków, więc sprawdzenie arności stoi za zajętością. Falsyfikator: `bind`
    przed sprawdzeniem `_thread` (`TypeError` zamiast `False`)."""
    uchwyt = WritebackRunner("", now_fn=lambda: NOW)
    uchwyt._thread = object()                        # atrapa operacji w biegu (`is_busy` → `_thread`)
    try:
        assert uchwyt.start("commit", "R", on_progress=lambda *a: None, on_done=lambda *a: None,
                            on_failed=lambda op, msg: None) is False
    finally:
        uchwyt._thread = None


def test_uchwyt_odbiorca_bez_sygnatury_TypeError_a_poprawni_przechodza(qapp, tmp_path, monkeypatch):
    """Odbiorca porażki bez sygnatury do sprawdzenia (wbudowany `max`) - `TypeError`, nie `ValueError`
    introspekcji w kliku; odbiorcy poprawni (`partial`, `*args`, parametr domyślny) startują.
    Falsyfikator: `inspect.signature` bez owinięcia `ValueError`."""
    sciezka = str(tmp_path / "w.db")
    db.open_db(sciezka).close()
    uchwyt = WritebackRunner(sciezka, now_fn=lambda: NOW)
    uchwyt.async_ok = False
    with pytest.raises(TypeError, match="sygnatury"):
        uchwyt.start("commit", "R", on_progress=lambda *a: None, on_done=lambda *a: None,
                     on_failed=max)
    assert not uchwyt.is_busy
    monkeypatch.setitem(WritebackWorker._OPS, "commit", lambda *a: "wynik")
    wyniki = []
    for odbiorca in (partial(lambda _x, op, z, p: None, 1), lambda *a: None,
                     lambda op, z, p, dodatkowy=None: None):
        assert uchwyt.start("commit", "R", on_progress=lambda *a: None,
                            on_done=lambda op, res: wyniki.append(res), on_failed=odbiorca)
    assert wyniki == ["wynik"] * 3


# ============================================================ AR-207 - zdjęcie podglądu zostawia cel


def test_zdjecie_podgladu_calego_widoku_zostawia_zaznaczenie_bez_czlonu(nazwy):
    """Ctrl+A, „Podgląd” nazw (stawianie - zaznaczenie wraca, cel gestu), „Wyczyść podgląd”: zdjęcie
    przy zaznaczeniu CAŁEGO widoku też je odtwarza (AR-202: bez progu kosztu), licznik je liczy,
    a zdanie gestu to samo zdanie zdjęcia. Falsyfikator: reset zdjęcia bez odtworzenia (zaznaczenie
    puste)."""
    view, _con = nazwy
    zdania = []
    view.status_message.connect(zdania.append)
    _klik_przycisku(view.sel_bar.btn_rename)
    QTest.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
    assert len(_zaznaczone(view)) == 3
    _klik_przycisku(view.rename_bar.btn_prev)
    assert view.model._preview_active() and len(_zaznaczone(view)) == 3
    _klik_przycisku(_przycisk(view.rename_bar, "grid.action.clear_preview"))
    assert not view.model._preview_active() and len(_zaznaczone(view)) == 3
    assert view.count_label.text().endswith(i18n.t_plural("grid.selected", 3))
    assert zdania[-1] == i18n.t("grid.rename.preview_cleared")


def test_staging_przy_calym_widoku_zostawia_zaznaczenie(nazwy):
    """„Do stagingu” nazw przy zaznaczeniu całego widoku: STAWIANIE podglądu odtwarza zaznaczenie
    (zakres stagingu musi być prawdziwy). Falsyfikator: reset podglądu bez odtworzenia."""
    view, _con = nazwy
    _klik_przycisku(view.sel_bar.btn_rename)
    QTest.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
    _klik_przycisku(view.rename_bar.btn_stage)
    assert view.model._preview_active() and len(_zaznaczone(view)) == 3


def test_zdjecie_podgladu_czesci_zostawia_cel_stagingu(nazwy):
    """Dwie z trzech klatek zaznaczone: „Podgląd” nazw, „Wyczyść podgląd”, „Do stagingu” - zdjęcie
    podglądu zostawia zaznaczenie CZĘŚCI widoku, więc staging bierze te dwie, nie cały widok.
    Falsyfikator: zdjęcie podglądu bez odtworzenia zaznaczenia (staging bierze cały widok)."""
    from horreum import writeback as wb
    view, con = nazwy
    ids = [r["frame_id"] for r in view.model._rows if "_group" not in r]
    _klik_komorki(view, ids[0], 1)
    _klik_komorki(view, ids[2], 1, Qt.ControlModifier)
    cel = sorted([ids[0], ids[2]])
    _klik_przycisku(view.sel_bar.btn_rename)
    _klik_przycisku(view.rename_bar.btn_prev)
    _klik_przycisku(_przycisk(view.rename_bar, "grid.action.clear_preview"))
    assert _zaznaczone(view) == cel
    _klik_przycisku(view.rename_bar.btn_stage)
    zakres = sorted(queries.frame_for_location(con, r["location_id"])
                    for r in wb.renames_for_run(con, view._rename_run_id))
    assert zakres == cel


def test_wyczysc_bez_podgladu_nie_przebudowuje_tabeli(nazwy):
    """Ctrl+A i „Wyczyść podgląd”, gdy podglądu nie ma: nie ma czego zdjąć, więc model się nie
    resetuje (zero `modelAboutToBeReset` - bez przebudowy, odtworzenia i przemalowania kadru),
    a zaznaczenie całego widoku zostaje. Falsyfikator: `set_preview({})` resetujący model także przy
    pustym podglądzie."""
    view, _con = nazwy
    _klik_przycisku(view.sel_bar.btn_rename)
    QTest.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
    assert not view.model._preview_active() and len(_zaznaczone(view)) == 3
    resety = []
    view.model.modelAboutToBeReset.connect(lambda: resety.append(1))
    _klik_przycisku(_przycisk(view.rename_bar, "grid.action.clear_preview"))
    assert resety == []
    assert len(_zaznaczone(view)) == 3


# ============================================================ AR-207 - licznik paska


def test_base_rows_wiersz_na_klatke_przy_dwoch_obecnych_kopiach(tmp_path):
    """Kontrakt read-modelu, na którym stoi zaznaczenie i licznik: `queries.base_rows` daje JEDEN
    wiersz na klatkę także przy dwóch obecnych kopiach (`n_present` = 2). Falsyfikator: łączenie
    lokacji bez zwinięcia do klatki (dwa wiersze)."""
    from test_gui_object_change import _lighty
    con = db.open_db(str(tmp_path / "k.db"))
    _lighty(tmp_path / "ASTRO_", con, "NGC7635", 1, baza=3)
    fid = con.execute("SELECT id FROM frame").fetchone()[0]
    con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V2', ?, 1)",
                (fid, str(tmp_path / "kopia.fits")))
    con.commit()
    wiersze = queries.base_rows(con, [fid])
    assert len(wiersze) == 1 and wiersze[0]["n_present"] == 2
    con.close()


def test_licznik_paska_liczy_klatki_po_obu_stronach(pliki, monkeypatch):
    """Duplikat wiersza klatki w składzie zbioru (stan, którego read-model dziś nie daje - kontrakt
    wyżej) nie zmienia osi licznika: „3 klatki”, nie „4 klatki”, a po Ctrl+A „3 zaznaczone”.
    Falsyfikator: `_n_total` liczony po wierszach (`len(base)`)."""
    view, _tmp = pliki
    prawdziwe = queries.base_rows

    def z_duplikatem(c, ids, *a, **k):
        wiersze = prawdziwe(c, ids, *a, **k)
        return wiersze + [dict(wiersze[0])] if wiersze else wiersze
    monkeypatch.setattr(queries, "base_rows", z_duplikatem)
    view.refresh()
    assert len(view.model._data_rows) == 4
    assert view.count_label.text() == i18n.t_plural("grid.frames", 3)
    QTest.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
    assert view.count_label.text() == (i18n.t_plural("grid.frames", 3) + "  ·  "
                                       + i18n.t_plural("grid.selected", 3))


# ============================================================ AR-205 - panel nazw w języku UI


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_etykieta_celu_i_blokada_stagingu_w_jezyku_UI(qapp, tmp_path, jezyk, lang):
    """Etykieta celu panelu nazw („Cel: …” / „Target: …”) bez i z zaznaczeniem i podpowiedź
    zablokowanego „Do stagingu” nazw przy kartach makra w szufladzie - z katalogu, z odmianą
    liczebnika (1 / 2-4 / 5+). Falsyfikatory: literał „Cel:” (UI EN po polsku), literał
    „staging makra w toku ({n} zmian)” („1 zmian”)."""
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    jezyk(lang)
    con = db.open_db(str(tmp_path / "c.db"))
    for i in (1, 2):
        p = tmp_path / f"c{i}.fits"
        hdu = fits.PrimaryHDU(data=np.full((4, 4), i, dtype=np.int16))
        hdu.header["TELESCOP"] = "RC8"
        hdu.header["IMAGETYP"] = "Light"
        hdu.writeto(str(p))
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary(),
                           pochodzenie=repo.ZEWNETRZNE)
    view = grid_mod.FramesView(con, now_fn=lambda: NOW)
    view._writeback_async = False
    view.resize(1400, 800)
    view.show()
    QApplication.processEvents()
    etykieta = view.rename_bar.target_lbl
    assert etykieta.text() == i18n.t("grid.rename.target", what=i18n.t_plural("grid.visible", 2))
    _klik_komorki(view, view.model._data_rows[0]["frame_id"], 1)
    assert etykieta.text() == i18n.t("grid.rename.target", what=i18n.t_plural("grid.selected", 1))
    if lang == "en":
        assert not set(etykieta.text()) & _POLSKIE and not etykieta.text().startswith("Cel")
    _staging_makra(view)
    n = view._pending_count()
    assert n >= 1
    assert view.rename_bar.btn_stage.toolTip() == i18n.t_plural("grid.macro.staging_busy_tip", n)
    for k in (1, 2, 5, 12, 22):
        tekst = i18n.t_plural("grid.macro.staging_busy_tip", k)
        assert f"({k} " in tekst
    if lang == "pl":
        assert i18n.t_plural("grid.macro.staging_busy_tip", 1).endswith("(1 zmiana)")
        assert i18n.t_plural("grid.rename.staging_busy_tip", 2).endswith("(2 zmiany)")
        assert i18n.t_plural("grid.rename.staging_busy_tip", 12).endswith("(12 zmian)")
    view.close()
    con.close()


# ============================================================ AR-195 - cofnięcie uwag bez odsłaniania


def test_cofniecie_uwag_poza_widokiem_jednym_czlonem(strona, con, okno, recepty):
    """Znajdź „uwagi:x”, zdjęcie uwagi z klatki 1 wypycha ją z widoku: recepta ma JEDEN wykonalny
    człon „Cofnij uwagi” (bez odsłaniania - cel z migawki); po jego wykonaniu uwaga wraca, klatka
    wraca do widoku i jest zaznaczona - zaznaczenie to klatki cofnięte. Falsyfikatory:
    `_ODWROT_UWAG` bez `bez_widoku` (dwa człony, cofnięcie bez wykonawcy); cel przeładowania z
    zaznaczenia z chwili klika (klatka wraca niezaznaczona)."""
    repo.set_frame_note(con, frame_ids=[1, 2], body="x", now=NOW)
    v = strona.frames_view
    strona.show_find("uwagi:x")
    v.table.clearSelection()
    v._przywroc_zaznaczenie([1])
    okno.intencja = NoteIntent("clear", None)
    v.sel_bar.act_notes.trigger()
    assert sorted(v._frame_ids) == [2]
    rec = recepty[-1]
    assert [c.tekst for c in rec.czlony] == [i18n.t("grid.notes.undo", menu=i18n.t("grid.notes.action"),
                                                    action=i18n.t("grid.notes.action"))]
    assert rec.czlony[0].wykonaj is not None
    rec.czlony[0].wykonaj()
    assert queries.notes_for(con, [1, 2]) == {1: "x", 2: "x"}
    assert sorted(v._frame_ids) == [1, 2]
    assert _zaznaczone(v) == [1]


def test_czesciowe_cofniecie_uwag_zaznacza_tylko_cofniete(strona, con, okno, recepty):
    """Gest uwag na klatkach 1 i 2, potem klatka 1 dostaje inną uwagę ręką: „Cofnij uwagi” cofa tylko
    2, a po przeładowaniu zaznaczona jest wyłącznie 2 - zaznaczenie to klatki cofnięte, nie cel recepty
    postawiony przed cofnięciem. Falsyfikator: cel przeładowania z zaznaczenia z chwili klika (1 i 2)."""
    v = strona.frames_view
    v.table.clearSelection()
    v._przywroc_zaznaczenie([1, 2])
    okno.intencja = NoteIntent("set", "x")
    v.sel_bar.act_notes.trigger()
    repo.set_frame_note(con, frame_ids=[1], body="inna", now=NOW)
    v.ponow_recepte()
    recepty[-1].czlony[0].wykonaj()
    assert queries.notes_for(con, [1, 2]) == {1: "inna"}
    assert _zaznaczone(v) == [2]


# ============================================================ AR-196 - cel na następny w potwierdzaniu


@pytest.fixture
def kolejka(qapp, tmp_path):
    """Perspektywa „Rodowód do potwierdzenia” z dwoma stosami: 40 (okno zdegenerowane, kandydaci
    z propozycji - `_seed_kandydaci`) i 24 (karta teleskopu - `_seed_stany`). Fikstura z
    `test_gui_rodowod_tabela` (ten sam seed i strona Znajdź)."""
    from horreum.gui.flows.znajdz_view import ZnajdzView
    from test_gui_rodowod_tabela import NOW as NOW_R, _seed, _seed_kandydaci, _seed_stany
    c = db.open_db(str(tmp_path / "k.db"))
    _seed(c)
    _seed_stany(c)
    _seed_kandydaci(c)
    v = grid_mod.FramesView(c, now_fn=lambda: NOW_R)
    v._writeback_async = False
    s = ZnajdzView(v)
    s.resize(1400, 900)
    s.show()
    yield s, c
    if not any(t.isRunning() for t in v.findChildren(QThread)):
        s.close()
        s.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    c.close()


def test_po_gescie_w_perspektywie_potwierdzania_cel_przechodzi_na_nastepny(kolejka):
    """Klik stosu 40 w perspektywie „Rodowód do potwierdzenia” (panel „Rodowód” otwiera samo wejście,
    AR-219), klik kandydata, „Potwierdź”: wejście ręki wietrzy powód stosu, więc 40 wypada
    z perspektywy, a zaznaczenie i panel przechodzą na następny obraz (24) - gest na nim jest o klik
    bliżej. Falsyfikator: cel na następny tylko w perspektywie „Rodowód z klatkami nowszymi”
    (zaznaczenie puste)."""
    from test_gui_rodowod_tabela import _klik, _klik_wiersza
    s, c = kolejka
    v = s.frames_view
    assert queries.lineage_pending_frame_ids(c) == {24, 40}
    v.apply_perspective(grid_mod.PRESET_LINEAGE)
    _czekaj(lambda: not v._zbior_w_drodze(), "zbiór perspektywy")
    assert sorted(v._frame_ids) == [24, 40]
    _klik_komorki(v, 40, 1)
    _odczekaj_debounce()
    assert v._lineage_panel_open() and v._lineage_frame_id == 40
    _klik_wiersza(v.lineage_bar.items, 42)
    _klik(v.lineage_bar.btn_confirm)
    _czekaj(lambda: not v._zbior_w_drodze(), "przyłożenie zbioru po werdykcie")
    assert sorted(v._frame_ids) == [24]
    assert _zaznaczone(v) == [24] and v._lineage_frame_id == 24
