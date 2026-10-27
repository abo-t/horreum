"""Szuflada Zbiorów - „Cofnij” OSTATNIEGO zapisu szuflady: wraca po „Odrzuć” i po zwolnieniu cudzej blokady (AR-381),
obejmuje ostatnią zmianę NAZW (AR-382, z datą zapisu nazw ze zdarzeń i jawną odmową wyboru przy historii
niejednoznacznej), a krótka forma powodu mówi nazwy plików zamiast ścieżek (AR-387, zdania szuflady w
`test_gui_szuflada_przebieg.py`). Kliki prawdziwe (`QTest.mouseClick` na widżecie), zapisy z poprzedniej sesji
prawdziwym rdzeniem (jak okno kart albo CLI), wątek zapisu prawdziwy tam, gdzie gest go ma."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from horreum import db, repo, writeback
from horreum.gui import i18n, queries

from test_gui_grid_szuflada import (_aktywacja, _baza_szuflady, _blokada_obca, _klik_w, _makro_przyciskiem,
                                    _restart, _trzyma_blokade, _zamknij_widok)
from test_gui_szuflada_przebieg import _DZIEN, _bez_cofnij, _karta_zapisana, _koniec_biegu


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


_POLSKIE = set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


def _cofnij():
    return i18n.t("grid.action.undo")


def _karta(con, run_id, wiersz, now, wartosc="EQ6"):
    """Przebieg kart `run_id` z kartą TELESCOP na pliku nr `wiersz`, zapisany rdzeniem w chwili `now`. Zwraca commit."""
    lid, hh = con.execute("SELECT id, header_hash FROM location ORDER BY id LIMIT 1 OFFSET ?", (wiersz,)).fetchone()
    repo.stage_pending(con, run_id=run_id, location_id=lid, keyword="TELESCOP", idx=0, op="set", old_value="RC8",
                       new_value=wartosc, new_type="str", new_comment=None, expected_header_hash=hh)
    writeback.commit(con, run_id, now=now, inplace=True)
    return con.execute("SELECT max(id) FROM commits WHERE run_id = ?", (run_id,)).fetchone()[0]


def _nazwy(con, run_id, wiersze, now, *, wstecz=False):
    """Zmiana nazw `run_id` plików nr `wiersze` zapisana rdzeniem w chwili `now` (jak CLI `rename`): nazwa + `.x`,
    albo - `wstecz` - bez końcówki `.x` (zmiana odwrotna). Zwraca wiersze stagingu przebiegu."""
    for w in wiersze:
        lid, p, mt = con.execute("SELECT id, path, mtime FROM location ORDER BY id LIMIT 1 OFFSET ?", (w,)).fetchone()
        repo.stage_rename(con, run_id=run_id, location_id=lid, old_path=p,
                          new_path=p[:-2] if wstecz else p + ".x", expected_mtime=mt)
    wynik = writeback.commit_renames(con, run_id, now=now)
    assert len(wynik.applied) == len(wiersze), wynik
    return writeback.renames_for_run(con, run_id)


# ============================================================ AR-381 - „Cofnij” ostatniego zapisu wraca


def test_odrzuc_stagingu_przywraca_cofnij_ostatniego_zapisu(qapp, tmp_path):
    """Restart po zapisie kart: „Cofnij” ostatniego zapisu stoi. Makro przyciskiem zdejmuje je (nowy staging), „Odrzuć”
    klikiem oddaje je z tym samym zakresem, a zdanie mówi odrzucenie i ostatni zapis; blokada szuflady oddana. Klik
    „Cofnij” przywraca bajty pliku. Falsyfikator: „Odrzuć” bez ponowienia ostatniego zapisu (pustostan do restartu)."""
    path, con, pliki = _baza_szuflady(tmp_path, 2)
    przed = pliki[0].read_bytes()
    c1 = _karta_zapisana(con, "R", 0)
    con.close()
    con, v = _restart(path)
    try:
        assert v._undo_btn.isVisible() and v._undo_commity == (c1,)
        _makro_przyciskiem(v, "TELESCOP", "EQ8")
        n = v._pending_count()
        assert n and _bez_cofnij(v)
        _klik_w(v.drawer.btn_reject)
        assert v._undo_btn.isVisible() and v._undo_mode == "macro" and v._undo_commity == (c1,)
        assert v.drawer.result.text() == (
            i18n.t_plural("grid.wb.rejected", n) + " · "
            + i18n.t_plural("grid.drawer.last_write", 1, day=_DZIEN, undo=_cofnij())
            + i18n.t("grid.wb.commit_id", id=c1)), v.drawer.result.text()
        assert not v.drawer.btn_commit.isVisible() and not _trzyma_blokade(v)
        _klik_w(v._undo_btn)
        _koniec_biegu(v, "cofnięcie ostatniego zapisu")
        assert pliki[0].read_bytes() == przed
    finally:
        _zamknij_widok(v)
        con.close()


def test_odrzuc_stagingu_nazw_przywraca_cofnij_ostatniego_zapisu(qapp, tmp_path):
    """To samo dla klingi nazw: „Do stagingu” panelu nazw klikiem zdejmuje „Cofnij” ostatniego zapisu kart, „Odrzuć”
    je oddaje. Falsyfikator: `_on_reject_rename` bez ponowienia."""
    path, con, _pliki = _baza_szuflady(tmp_path, 2)
    c1 = _karta_zapisana(con, "R", 0)
    con.close()
    con, v = _restart(path)
    try:
        if not v.rename_bar.isVisible():
            _klik_w(v.sel_bar.btn_rename)
        _klik_w(v.rename_bar.btn_stage)
        assert v._rename_pending_count() == 2 and _bez_cofnij(v)
        _klik_w(v.drawer.btn_reject)
        assert v._undo_btn.isVisible() and v._undo_mode == "macro" and v._undo_commity == (c1,)
        assert v.drawer.result.text().startswith(i18n.t_plural("grid.rename.rejected", 2) + " · "), \
            v.drawer.result.text()
        assert v._rename_run_id is None and not _trzyma_blokade(v)
    finally:
        _zamknij_widok(v)
        con.close()


def test_cudza_blokada_przy_budowie_cofnij_po_zwolnieniu(qapp, tmp_path):
    """Szufladę bazy prowadzi inny proces przy budowie widoku: bez „Cofnij”, także po aktywacji okna, dopóki blokada
    stoi. Po jej zwolnieniu aktywacja okna stawia „Cofnij” ostatniego zapisu, a widok NIE trzyma blokady.
    Falsyfikatory: odmowa bez odroczenia (dawniej `return` bez śladu); odroczenie gaszone przy pierwszej nieudanej
    próbie; blokada wzięta przy ponowieniu i nieoddana."""
    path, con, _p = _baza_szuflady(tmp_path, 1)
    c1 = _karta_zapisana(con, "R", 0)
    con.close()
    blokada = _blokada_obca(path)
    con, v = _restart(path)
    try:
        assert _bez_cofnij(v)
        _aktywacja(v)
        assert _bez_cofnij(v)
        blokada.unlock()
        _aktywacja(v)
        assert v._undo_btn.isVisible() and v._undo_commity == (c1,) and not _trzyma_blokade(v)
        assert v.drawer.result.text() == (i18n.t_plural("grid.drawer.last_write", 1, day=_DZIEN, undo=_cofnij())
                                          + i18n.t("grid.wb.commit_id", id=c1)), v.drawer.result.text()
    finally:
        if blokada.isLocked():
            blokada.unlock()
        _zamknij_widok(v)
        con.close()


def test_zapis_samych_blokad_nie_stawia_cofnij_starszego_zapisu(qapp, tmp_path):
    """Restart z „Cofnij” zapisu R, makro na drugim pliku, plik zmieniony z zewnątrz, „Zatwierdź”: wszystko
    zablokowane, wiersza `commits` nie ma (commit powstaje przy pierwszym ruszonym pliku). Szuflada mówi wynik
    zapisu bez „Cofnij” - także po aktywacji okna. Falsyfikator: ponowienie ostatniego zapisu w każdym `_pusta`
    („Cofnij” STARSZEGO R w miejscu zdania porażki)."""
    from astropy.io import fits
    path, con, pliki = _baza_szuflady(tmp_path, 2)
    _karta_zapisana(con, "R", 0)
    con.close()
    con, v = _restart(path)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ8")
        for p in pliki:                                  # każdy plik zmieniony od stagingu - zapis go zablokuje
            fits.setval(str(p), "OBSERVER", value="obcy")
        _klik_w(v.drawer.btn_commit)
        _koniec_biegu(v, "zapis samych blokad")
        assert con.execute("SELECT count(*) FROM commits").fetchone()[0] == 1
        zdanie = v.drawer.result.text()
        assert _bez_cofnij(v) and v._undo_mode is None and zdanie
        _aktywacja(v)
        assert _bez_cofnij(v) and v.drawer.result.text() == zdanie
    finally:
        _zamknij_widok(v)
        con.close()


def test_odroczenie_gasnie_przy_ponownym_stagingu_do_zera(qapp, tmp_path):
    """Budowa pod cudzą blokadą (odroczenie), blokada zwolniona BEZ aktywacji okna, makro (przebieg tej sesji), potem
    makro bez żadnej zmiany - przebieg wyczyszczony do zera zamyka się. Aktywacja okna nie stawia „Cofnij” starszego
    zapisu obok zdania stagingu. Asercja prywatnej flagi odroczenia jest świadoma: zdanie gestu w polu i tak wstrzymuje
    ponowienie (warunek pola w `_pusta`), więc bez niej test nie rozdzieliłby warstw - flaga mierzy punkt przejęcia
    (`_dismiss_undo`) osobno. Falsyfikator: odroczenie żywe po przejęciu szuflady przez własny staging."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _karta_zapisana(con, "R", 0)
    con.close()
    blokada = _blokada_obca(path)
    con, v = _restart(path)
    try:
        assert _bez_cofnij(v) and v._cofnij_ostatniego_odlozone
        blokada.unlock()
        _makro_przyciskiem(v, "TELESCOP", "EQ8")
        assert v._pending_count() and v._run_id is not None
        _makro_przyciskiem(v, "EXPTIME", "abc")          # same pominięcia - przebieg do zera
        assert v._run_id is None and v._pending_count() == 0
        zdanie = v.drawer.result.text()
        _aktywacja(v)
        assert _bez_cofnij(v) and not v._cofnij_ostatniego_odlozone and v.drawer.result.text() == zdanie
    finally:
        if blokada.isLocked():
            blokada.unlock()
        _zamknij_widok(v)
        con.close()


def test_odroczenie_gasnie_przy_awarii_zamykajacej_przebieg(qapp, tmp_path, monkeypatch):
    """Budowa pod cudzą blokadą, blokada zwolniona bez aktywacji, makro, plik zmieniony z zewnątrz, „Zatwierdź” blokuje
    plik i operacja pada wyjątkiem - przebieg zamyka się bez zapisu. Aktywacja okna nie stawia „Cofnij” starszego
    zapisu. Falsyfikator: odroczenie żywe po własnym stagingu."""
    from astropy.io import fits
    from horreum.gui.wb_worker import WritebackWorker
    path, con, pliki = _baza_szuflady(tmp_path, 2)
    _karta_zapisana(con, "R", 0)
    con.close()
    blokada = _blokada_obca(path)
    con, v = _restart(path)
    try:
        blokada.unlock()
        _makro_przyciskiem(v, "TELESCOP", "EQ8")
        for p in pliki:                                  # każdy plik zmieniony od stagingu - zapis go zablokuje
            fits.setval(str(p), "OBSERVER", value="obcy")
        prawdziwe = WritebackWorker._OPS["commit"]

        def _blokuje_i_pada(c, t, now, pr, sc):
            prawdziwe(c, t, now, pr, sc)
            raise ValueError("złamany inwariant po zapisie")
        monkeypatch.setitem(WritebackWorker._OPS, "commit", _blokuje_i_pada)
        _klik_w(v.drawer.btn_commit)
        _koniec_biegu(v, "awaria zapisu")
        assert v._run_id is None and _bez_cofnij(v)
        _aktywacja(v)
        assert _bez_cofnij(v)
    finally:
        if blokada.isLocked():
            blokada.unlock()
        _zamknij_widok(v)
        con.close()


def test_odroczenie_gasnie_przy_podjeciu_zwolnionego_przebiegu(qapp, tmp_path, monkeypatch):
    """Budowa pod cudzą blokadą po zapisie kart (odroczenie). Drugie połączenie zakłada zmianę nazw z otwartym
    zamiarem (szuflada mówi o niej przy aktywacji), rekoncyliacja oddaje wiersz do czekających (plik pod starą
    nazwą), blokada schodzi - aktywacja PODEJMUJE przebieg nazw w tej sesji: odroczenie gaśnie. „Zatwierdź” (skan
    widział plik zmieniony od stagingu - zapis go blokuje) pada wyjątkiem i zamyka przebieg bez zapisu: aktywacja
    nie stawia „Cofnij” starszych kart, zdanie awarii stoi. Asercje prywatnej flagi są świadome - mierzą punkty przejęcia
    osobno (podjęcie; zapis tej sesji - flaga podniesiona ręcznie po podjęciu), bo zdanie w polu i tak wstrzymuje
    ponowienie. Falsyfikatory: podjęcie zwolnionego przebiegu bez gaszenia odroczenia; zapis tej sesji bez niego."""
    from horreum.gui.wb_worker import WritebackWorker
    from test_gui_grid_szuflada import NOW
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _karta_zapisana(con, "K", 0)
    con.close()
    blokada = _blokada_obca(path)
    con, v = _restart(path)
    try:
        assert _bez_cofnij(v) and v._cofnij_ostatniego_odlozone
        con2 = db.connect(path)
        try:
            lid, p, mt = con2.execute("SELECT id, path, mtime FROM location ORDER BY id LIMIT 1 OFFSET 1").fetchone()
            rid = repo.stage_rename(con2, run_id="N", location_id=lid, old_path=p, new_path=p + ".x",
                                    expected_mtime=mt)
            repo.open_rename_intent(con2, rename_id=rid, direction="commit")
        finally:
            con2.close()
        _aktywacja(v)                                    # zamiar otwarty - szuflada zapamiętuje przebieg nazw
        assert v._rename_run_id is None and v._cofnij_ostatniego_odlozone
        con2 = db.connect(path)
        try:
            assert [f.status for f in writeback.reconcile_renames(con2, now=NOW)] == ["reconciled"]
        finally:
            con2.close()
        blokada.unlock()
        _aktywacja(v)
        assert v._rename_run_id == "N" and v._rename_pending_count() == 1
        assert not v._cofnij_ostatniego_odlozone
        v._cofnij_ostatniego_odlozone = True             # punkt przejęcia przez zapis tej sesji - osobno
        with con:                                        # skan widział plik zmieniony od stagingu - zapis go blokuje
            con.execute("UPDATE location SET mtime = mtime + 60 WHERE id = ?", (lid,))
        prawdziwe = WritebackWorker._OPS["commit_rename"]

        def _blokuje_i_pada(c, t, now, pr, sc):
            prawdziwe(c, t, now, pr, sc)
            raise ValueError("złamany inwariant po zapisie")
        monkeypatch.setitem(WritebackWorker._OPS, "commit_rename", _blokuje_i_pada)
        _klik_w(v.drawer.btn_commit)
        assert not v._cofnij_ostatniego_odlozone
        _koniec_biegu(v, "awaria zapisu nazw")
        zdanie = v.drawer.result.text()
        assert v._rename_run_id is None and _bez_cofnij(v) and zdanie, zdanie
        _aktywacja(v)
        assert _bez_cofnij(v) and v.drawer.result.text() == zdanie
    finally:
        if blokada.isLocked():
            blokada.unlock()
        _zamknij_widok(v)
        con.close()


def test_odmowa_stagingu_przy_odroczeniu_schodzi_po_zwolnieniu_blokady(qapp, tmp_path):
    """Odroczenie po budowie pod cudzą blokadą, makro przyciskiem: szufladę prowadzi inny proces - zdanie odmowy. Pod
    trwającą blokadą aktywacja zostawia to zdanie. Po zwolnieniu blokady aktywacja zdejmuje je i stawia „Cofnij”
    ostatniego zapisu. Falsyfikatory: zdanie odmowy jako zdanie gestu (ponowienie wstrzymane do restartu); ponowienie
    odmówione blokadą zdejmuje zdanie o niej (puste pole pod trwającą blokadą)."""
    from test_gui_grid_szuflada import _obcy
    path, con, _p = _baza_szuflady(tmp_path, 2)
    c1 = _karta_zapisana(con, "K", 0)
    con.close()
    blokada = _blokada_obca(path)
    con, v = _restart(path)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ8")
        assert v._run_id is None and v.drawer.result.text() == _obcy(), v.drawer.result.text()
        _aktywacja(v)
        assert _bez_cofnij(v) and v.drawer.result.text() == _obcy(), v.drawer.result.text()
        blokada.unlock()
        _aktywacja(v)
        assert v._undo_btn.isVisible() and v._undo_commity == (c1,) and not _trzyma_blokade(v)
        assert v.drawer.result.text() == (i18n.t_plural("grid.drawer.last_write", 1, day=_DZIEN, undo=_cofnij())
                                          + i18n.t("grid.wb.commit_id", id=c1)), v.drawer.result.text()
    finally:
        if blokada.isLocked():
            blokada.unlock()
        _zamknij_widok(v)
        con.close()


def test_zapis_innej_powierzchni_przy_odroczeniu_bez_cofnij_starszego(qapp, tmp_path):
    """Odroczenie po budowie pod cudzą blokadą, blokada zwolniona bez aktywacji. Druga powierzchnia zapisu tej sesji
    (okno „Napraw nagłówek…” - `set_writeback_busy`) zapisuje same blokady: plik zmieniony od stagingu, wiersza
    `commits` nie ma. Aktywacja nie stawia „Cofnij” STARSZEGO zapisu kart. Pole jest puste, więc test mierzy sam
    punkt przejęcia. Falsyfikator: `set_writeback_busy(True)` bez gaszenia odroczenia."""
    from astropy.io import fits
    path, con, pliki = _baza_szuflady(tmp_path, 2)
    _karta_zapisana(con, "K", 0)
    con.close()
    blokada = _blokada_obca(path)
    con, v = _restart(path)
    try:
        blokada.unlock()
        assert _bez_cofnij(v) and not v.drawer.result.text()
        v.set_writeback_busy(True)
        lid, hh = con.execute("SELECT id, header_hash FROM location ORDER BY id LIMIT 1 OFFSET 1").fetchone()
        repo.stage_pending(con, run_id="N", location_id=lid, keyword="TELESCOP", idx=0, op="set", old_value="RC8",
                           new_value="EQ8", new_type="str", new_comment=None, expected_header_hash=hh)
        fits.setval(str(pliki[1]), "OBSERVER", value="obcy")
        writeback.commit(con, "N", now="2026-07-03T15:00:00", inplace=True)
        assert con.execute("SELECT count(*) FROM commits").fetchone()[0] == 1
        v.set_writeback_busy(False)
        _aktywacja(v)
        assert _bez_cofnij(v) and v._undo_mode is None
    finally:
        if blokada.isLocked():
            blokada.unlock()
        _zamknij_widok(v)
        con.close()


def test_odroczenie_przezywa_odczyt_bez_kandydata(qapp, tmp_path):
    """Odroczenie po budowie pod cudzą blokadą. Drugie połączenie zostawia porzucony staging kart - aktywacja czyta
    ostatni zapis bez blokady i nie widzi kandydata (w szufladzie coś czeka). Staging porzucony zostaje odrzucony
    tamtym połączeniem, blokada schodzi - aktywacja stawia „Cofnij” ostatniego zapisu: odroczenie gasi wyłącznie
    decyzja pod blokadą. Falsyfikator: odroczenie gaszone przy pierwszym odczycie bez blokady."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    c1 = _karta_zapisana(con, "K", 0)
    con.close()
    blokada = _blokada_obca(path)
    con, v = _restart(path)
    try:
        con2 = db.connect(path)
        try:
            lid, hh = con2.execute("SELECT id, header_hash FROM location ORDER BY id LIMIT 1 OFFSET 1").fetchone()
            repo.stage_pending(con2, run_id="X", location_id=lid, keyword="TELESCOP", idx=0, op="set",
                               old_value="RC8", new_value="EQ8", new_type="str", new_comment=None,
                               expected_header_hash=hh)
        finally:
            con2.close()
        _aktywacja(v)
        assert _bez_cofnij(v) and queries.ostatni_zapis_szuflady(con) is None
        con2 = db.connect(path)
        try:
            assert repo.discard_staging(con2, run_id="X", klinga="karty", now="2026-07-03T15:00:00") == 1
        finally:
            con2.close()
        blokada.unlock()
        _aktywacja(v)
        assert v._undo_btn.isVisible() and v._undo_commity == (c1,) and not _trzyma_blokade(v)
    finally:
        if blokada.isLocked():
            blokada.unlock()
        _zamknij_widok(v)
        con.close()


def test_odroczenie_czeka_na_zdanie_gestu_bez_przebiegu(qapp, tmp_path):
    """Odroczenie po budowie pod cudzą blokadą, blokada zwolniona bez aktywacji, makro bez żadnej zmiany (same
    pominięcia) - przebiegu nie ma, szuflady nikt nie przejął, w polu stoi zdanie gestu. Aktywacja go nie zdejmuje i
    nie stawia „Cofnij” w jego miejscu. Falsyfikator: ponowienie odroczenia bez warunku pola."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _karta_zapisana(con, "K", 0)
    con.close()
    blokada = _blokada_obca(path)
    con, v = _restart(path)
    try:
        blokada.unlock()
        _makro_przyciskiem(v, "EXPTIME", "abc")
        zdanie = v.drawer.result.text()
        assert v._run_id is None and zdanie and v._cofnij_ostatniego_odlozone
        _aktywacja(v)
        assert _bez_cofnij(v) and v.drawer.result.text() == zdanie
    finally:
        if blokada.isLocked():
            blokada.unlock()
        _zamknij_widok(v)
        con.close()


# ============================================================ AR-382 - „Cofnij” ostatniej zmiany NAZW


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_restart_po_zmianie_nazw_stawia_cofnij_nazw(qapp, tmp_path, lang):
    """Zmiana nazw trzech plików panelem nazw (klik „Do stagingu”, „Zatwierdź”), zamknięcie okna, nowy widok: szuflada
    stawia „Cofnij” nazw przebiegu z etykietą „Przemianowano: 3”, zdaniem z datą i identyfikatorem przebiegu; blokada
    oddana; EN bez polskich znaków. Klik przywraca stare nazwy. Falsyfikator: odczyt ostatniego zapisu bez klingi nazw
    (dawniej pusta szuflada, droga tylko `rename --undo`)."""
    i18n.set_lang(lang)
    from test_gui_grid_szuflada import _widok_szuflady
    from test_gui_pasek_szczegol import _czekaj
    path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    try:
        _czekaj(lambda: not v._zbior_w_drodze(), "pierwszy zbiór")   # staging nazw działa na widocznych klatkach
        if not v.rename_bar.isVisible():
            _klik_w(v.sel_bar.btn_rename)
        _klik_w(v.rename_bar.btn_stage)
        _klik_w(v.drawer.btn_commit)
        _koniec_biegu(v, "zapis nazw")
        run = v._undo_rename_run_id
        assert run and not any(p.exists() for p in pliki)
    finally:
        _zamknij_widok(v)
        con.close()
    con, v = _restart(path)
    try:
        assert v._undo_btn.isVisible() and v._undo_mode == "rename" and v._undo_rename_run_id == run
        assert v.drawer.label.text() == i18n.t("grid.rename.renamed_label", n=3)
        assert v.drawer.result.text() == (i18n.t_plural("grid.drawer.last_rename", 3, day=_DZIEN, undo=_cofnij())
                                          + i18n.t("grid.wb.run_id", id=run)), v.drawer.result.text()
        assert not _trzyma_blokade(v)
        if lang == "en":
            assert not set(v.drawer.result.text()) & _POLSKIE, v.drawer.result.text()
        _klik_w(v._undo_btn)
        _koniec_biegu(v, "cofnięcie nazw")
        assert all(p.exists() for p in pliki)
    finally:
        i18n.set_lang("pl")
        _zamknij_widok(v)
        con.close()


@pytest.mark.parametrize("nowsze", ["karty", "nazwy"])
def test_nowsza_klinga_wygrywa_po_dacie_zapisu(qapp, tmp_path, nowsze):
    """Zapis kart i zmiana nazw różnych plików w różnych chwilach (rdzeń, jak CLI): po restarcie „Cofnij” dostaje
    klinga NOWSZEGO zapisu. Falsyfikator: wybór klingi bez porównania chwil zapisu (zawsze karty albo zawsze nazwy)."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    t_karty, t_nazwy = (("2026-07-03T15:00:00", "2026-07-03T14:00:00") if nowsze == "karty"
                        else ("2026-07-03T14:00:00", "2026-07-03T15:00:00"))
    c1 = _karta(con, "K", 0, t_karty)
    _nazwy(con, "N", [1], t_nazwy)
    con.close()
    con, v = _restart(path)
    try:
        if nowsze == "karty":
            assert v._undo_mode == "macro" and v._undo_commity == (c1,)
        else:
            assert v._undo_mode == "rename" and v._undo_rename_run_id == "N"
            assert v.drawer.label.text() == i18n.t("grid.rename.renamed_label", n=1)
    finally:
        _zamknij_widok(v)
        con.close()


def test_data_nazw_z_zapisu_nie_z_kolejnosci_stagingu(qapp, tmp_path):
    """Przebieg nazw A zastagingowany PRZED B (niższe `id` wierszy), ale zapisany PO nim: „Cofnij” dostaje A - data ze
    zdarzenia zapisu, nie z kolejności stagingu. Falsyfikator: najnowszy przebieg po `max(id)` wiersza."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    for run_id, w in (("A", 0), ("B", 1)):
        lid, p, mt = con.execute("SELECT id, path, mtime FROM location ORDER BY id LIMIT 1 OFFSET ?", (w,)).fetchone()
        repo.stage_rename(con, run_id=run_id, location_id=lid, old_path=p, new_path=p + ".x", expected_mtime=mt)
    assert len(writeback.commit_renames(con, "B", now="2026-07-03T14:00:00").applied) == 1
    assert len(writeback.commit_renames(con, "A", now="2026-07-03T15:00:00").applied) == 1
    con.close()
    con, v = _restart(path)
    try:
        assert v._undo_mode == "rename" and v._undo_rename_run_id == "A"
    finally:
        _zamknij_widok(v)
        con.close()


def test_cofnieta_ostatnia_zmiana_nazw_bez_cofnij_starszych_kart(qapp, tmp_path):
    """Zapis kart, potem zmiana nazw, potem jej cofnięcie (rdzeń): ostatni zapis szuflady jest cofnięty - bez „Cofnij”,
    także bez „Cofnij” starszych kart (lustro reguły kart AR-367). Falsyfikator: cofnięty przebieg nazw pomijany i
    spadek na karty."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _karta(con, "K", 0, "2026-07-03T14:00:00")
    _nazwy(con, "N", [1], "2026-07-03T15:00:00")
    writeback.undo_renames(con, "N", now="2026-07-03T16:00:00")
    con.close()
    con, v = _restart(path)
    try:
        assert _bez_cofnij(v) and v._undo_mode is None
        assert v.drawer.label.text() == i18n.t("grid.drawer.empty")
    finally:
        _zamknij_widok(v)
        con.close()


def test_zmiana_nazw_z_otwartym_zamiarem_bez_cofnij(qapp, tmp_path):
    """Najnowsza zmiana nazw ma wiersz z otwartym zamiarem cofnięcia (cofnięcie w biegu w innym procesie albo
    przerwane - rozstrzyga rekoncyliacja): bez „Cofnij”. Falsyfikator: przebieg z otwartym zamiarem jako kandydat."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _karta(con, "K", 0, "2026-07-03T14:00:00")
    (wiersz,) = _nazwy(con, "N", [1], "2026-07-03T15:00:00")
    repo.open_rename_intent(con, rename_id=wiersz["id"], direction="undo")
    con.close()
    con, v = _restart(path)
    try:
        assert _bez_cofnij(v) and v._undo_mode is None
    finally:
        _zamknij_widok(v)
        con.close()


def test_historia_nazw_tam_i_z_powrotem_cofnij_drugiej_zmiany(qapp, tmp_path):
    """Plik przemianowany A→B (przebieg `tam`), potem B→A (przebieg `powrot`), bez nowszych kart: para odwrotna to
    zapis DRUGIEGO wiersza, nie niejednoznaczność - „Cofnij” nazw przebiegu `powrot`. Po jego cofnięciu (rdzeń)
    ostatni zapis jest cofnięty - bez „Cofnij”, także bez „Cofnij” przebiegu `tam`. Falsyfikatory: para odwrotna
    jako konflikt (odmowa wyboru); spadek do starszego zapisu nazw po cofnięciu ostatniego."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _nazwy(con, "tam", [0], "2026-07-03T13:00:00")
    _nazwy(con, "powrot", [0], "2026-07-03T14:00:00", wstecz=True)
    con.close()
    con, v = _restart(path)
    try:
        assert v._undo_mode == "rename" and v._undo_rename_run_id == "powrot"
    finally:
        _zamknij_widok(v)
        con.close()
    con = db.connect(path)
    writeback.undo_renames(con, "powrot", now="2026-07-03T16:00:00")
    con.close()
    con, v = _restart(path)
    try:
        assert _bez_cofnij(v) and v._undo_mode is None
        assert queries.ostatni_zapis_szuflady(con) is None
    finally:
        _zamknij_widok(v)
        con.close()


def test_historia_nazw_tam_i_z_powrotem_po_cofnieciu_cofnij_nowszych_kart(qapp, tmp_path):
    """A→B (`tam`), B→A (`powrot`), zapis kart C na innym pliku, cofnięcie `powrot` (plik znów pod B): zdarzenie
    cofnięcia ma parę zapisu `tam`, ale przychodzi po zapisie `powrot` - to jego cofnięcie. Zapis kart jest najnowszy
    przed cofnięciem i po nim - „Cofnij” kart. Falsyfikator: cofnięcie drugiego wiersza wzięte za ponowny zapis
    pierwszego (odmowa wyboru)."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _nazwy(con, "tam", [0], "2026-07-03T13:00:00")
    _nazwy(con, "powrot", [0], "2026-07-03T14:00:00", wstecz=True)
    c = _karta(con, "C", 1, "2026-07-03T15:00:00")
    con.close()
    con, v = _restart(path)
    try:
        assert v._undo_mode == "macro" and v._undo_commity == (c,)
    finally:
        _zamknij_widok(v)
        con.close()
    con = db.connect(path)
    writeback.undo_renames(con, "powrot", now="2026-07-03T16:00:00")
    con.close()
    con, v = _restart(path)
    try:
        assert v._undo_mode == "macro" and v._undo_commity == (c,)
    finally:
        _zamknij_widok(v)
        con.close()


def test_ponowiona_identyczna_zmiana_nazw_cofnij_ostatniej(qapp, tmp_path):
    """Zapis kart, zmiana nazw A→B (`pierwsza`), jej cofnięcie, ta sama zmiana A→B nowym przebiegiem (`ponowna`): dwa
    wiersze tej samej pary na jednej lokacji, a zdarzenia po kolei - zapis, cofnięcie, zapis - przypisują ostatni zapis
    przebiegowi `ponowna`. „Cofnij” nazw tego przebiegu. Falsyfikator: para powtórzona jako niejednoznaczność."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _karta(con, "K", 1, "2026-07-03T12:00:00")
    _nazwy(con, "pierwsza", [0], "2026-07-03T13:00:00")
    writeback.undo_renames(con, "pierwsza", now="2026-07-03T14:00:00")
    _nazwy(con, "ponowna", [0], "2026-07-03T15:00:00")
    con.close()
    con, v = _restart(path)
    try:
        assert v._undo_mode == "rename" and v._undo_rename_run_id == "ponowna"
    finally:
        _zamknij_widok(v)
        con.close()


def test_wiersz_cofniety_sprzed_kodow_powodu_poznany_po_prozie(qapp, tmp_path):
    """Wiersze sprzed kodów powodu (migracja bez uzupełnienia - kopia pf4: 62 wiersze 'skipped' z samą prozą
    „cofnięto (undo)”): wiersz cofnięty poznany po prozie. Scena ponowionej zmiany nazw z cofniętym wierszem w formie
    sprzed kodów - ostatni zapis to `ponowna`. Falsyfikator: proza pominięta (wiersz cofnięty wzięty za kopię, która
    zniknęła przed zapisem - jego zapis i cofnięcie cudze w oknie ponownej zmiany, odmowa wyboru)."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _karta(con, "K", 1, "2026-07-03T12:00:00")
    _nazwy(con, "pierwsza", [0], "2026-07-03T13:00:00")
    writeback.undo_renames(con, "pierwsza", now="2026-07-03T14:00:00")
    _nazwy(con, "ponowna", [0], "2026-07-03T15:00:00")
    with con:
        assert con.execute("UPDATE pending_renames SET reason_code = NULL, reason_args = NULL "
                           "WHERE status = 'skipped'").rowcount == 1
    try:
        zapis = queries.ostatni_zapis_szuflady(con)
        assert zapis is not None and zapis["klinga"] == "nazwy" and zapis["run_id"] == "ponowna"
    finally:
        con.close()


def test_rekoncyliacja_z_identyfikatorem_wiersza_wygrywa(qapp, tmp_path, monkeypatch):
    """Lokacja przepięta A→B i z powrotem B→A bez gestu nazw (dwa zdarzenia tej pary bez wiersza stagingu), potem
    zmiana nazw A→B rozdarta (plik pod nową nazwą, baza nie) i rozstrzygnięta rekoncyliacją: jej zdarzenie niesie
    wiersz stagingu - FAKT. „Cofnij” nazw tego przebiegu, choć wcześniejsze przepięcia tej samej pary zmyliłyby
    przypisanie po kolei. Falsyfikatory: zdarzenie z identyfikatorem wiersza liczone jak każde inne (pierwsze A→B
    wzięte za zapis, właściwe - konflikt); fakt sprawdzany oknem."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _karta(con, "K", 1, "2026-07-03T12:00:00")
    _zmiana_nazw_rozstrzygnieta_rekoncyliacja(con, monkeypatch)
    con.close()
    con, v = _restart(path)
    try:
        assert v._undo_mode == "rename" and v._undo_rename_run_id == "N"
    finally:
        _zamknij_widok(v)
        con.close()


def test_zapis_po_rekoncyliacji_z_faktem_jest_ostatni(qapp, tmp_path, monkeypatch):
    """Scena rekoncyliacji z faktem (A→B, przebieg `N`, po przepięciach A→B, B→A bez gestu), potem zmiana odwrotna B→A
    zwykłym zapisem (`powrot`, zdarzenie bez identyfikatora): zapis `powrot` przychodzi po zapisie `N`, także znanym
    z faktu, więc wcześniejsze przepięcie B→A go nie udaje - „Cofnij” nazw `powrot`. Falsyfikator: zdarzenie sprzed
    zapisu z faktu przypisane dalszemu wierszowi („Cofnij” starszego przebiegu `N`)."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _karta(con, "K", 1, "2026-07-03T12:00:00")
    _zmiana_nazw_rozstrzygnieta_rekoncyliacja(con, monkeypatch)
    _nazwy(con, "powrot", [0], "2026-07-03T14:00:00", wstecz=True)
    con.close()
    con, v = _restart(path)
    try:
        assert v._undo_mode == "rename" and v._undo_rename_run_id == "powrot"
    finally:
        _zamknij_widok(v)
        con.close()


def _zmiana_nazw_rozstrzygnieta_rekoncyliacja(con, monkeypatch):
    """Lokacja pliku nr 0 przepięta A→B i z powrotem B→A bez gestu nazw, potem zmiana nazw A→B (`N`) rozdarta (plik pod
    nową nazwą, baza nie) i rozstrzygnięta rekoncyliacją - jej zdarzenie niesie wiersz stagingu (FAKT)."""
    import sqlite3
    from test_rename import _bez_kompensacji, _pad_raz
    lid, p, mt = con.execute("SELECT id, path, mtime FROM location ORDER BY id LIMIT 1").fetchone()
    assert repo.relocate_location(con, location_id=lid, new_path=p + ".x", now="2026-07-03T12:10:00")
    assert repo.relocate_location(con, location_id=lid, new_path=p, now="2026-07-03T12:20:00")
    rid = repo.stage_rename(con, run_id="N", location_id=lid, old_path=p, new_path=p + ".x", expected_mtime=mt)
    with monkeypatch.context() as m:
        _pad_raz(m, repo, "_apply_relocation", sqlite3.OperationalError("disk I/O error"))
        _bez_kompensacji(m)
        writeback.commit_renames(con, "N", now="2026-07-03T13:00:00")
    assert os.path.exists(p + ".x") and not os.path.exists(p)
    assert [f.status for f in writeback.reconcile_renames(con, now="2026-07-03T13:30:00")] == ["reconciled"]
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'location.renamed' "
                       "AND json_extract(payload, '$.pending_rename') = ?", (rid,)).fetchone()[0] == 1


def test_kopia_zniknela_przy_zapisie_a_odwrotna_zmiana_cofnieta(qapp, tmp_path):
    """Zmiana nazw A→B (`tam`) zapisana; zmiana odwrotna B→A (`znikla`) pominięta przy zapisie - kopia zniknęła, wiersz
    'skipped' bez zdarzenia; zapis kart K na innym pliku; cofnięcie `tam` (zdarzenie B→A). Wiersz bez zapisu nie wnosi
    pary do historii: zapis kart jest najnowszy - „Cofnij” kart. Falsyfikator: wiersz 'skipped' bez zdarzenia liczony
    jako zapis albo konflikt (odmowa wyboru)."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    (wiersz,) = _nazwy(con, "tam", [0], "2026-07-03T13:00:00")
    lid, p, mt = con.execute("SELECT id, path, mtime FROM location WHERE id = ?", (wiersz["location_id"],)).fetchone()
    repo.stage_rename(con, run_id="znikla", location_id=lid, old_path=p, new_path=p[:-2], expected_mtime=mt)
    with con:
        con.execute("UPDATE location SET present = 0 WHERE id = ?", (lid,))
    assert [f.status for f in writeback.commit_renames(con, "znikla", now="2026-07-03T13:30:00").skipped] == \
        ["skipped"]
    with con:
        con.execute("UPDATE location SET present = 1 WHERE id = ?", (lid,))
    k = _karta(con, "K", 1, "2026-07-03T14:00:00")
    writeback.undo_renames(con, "tam", now="2026-07-03T15:00:00")
    con.close()
    con, v = _restart(path)
    try:
        assert v._undo_mode == "macro" and v._undo_commity == (k,)
    finally:
        _zamknij_widok(v)
        con.close()


def test_kopia_zniknela_a_pozniejsze_przepiecia_nie_udaja_zapisu(qapp, tmp_path):
    """Przebieg nazw `R` na dwóch plikach: kopia pierwszego zniknęła przed zapisem (wiersz 'skipped' z powodem kopii,
    nie cofnięcia), drugi zapisany; potem zapis kart K na trzecim pliku, a lokację pierwszego przepięto A→B i z
    powrotem bez gestu nazw. Para wiersza bez zapisu w późniejszych zdarzeniach nie udaje zapisu i cofnięcia - ostatnim
    zapisem są karty: „Cofnij” kart. Falsyfikator: przypisanie najtańsze wbrew faktowi wiersza („Cofnij” nazw `R`
    ponad nowszym zapisem kart)."""
    path, con, _p = _baza_szuflady(tmp_path, 3)
    lok = [tuple(r) for r in con.execute("SELECT id, path, mtime FROM location ORDER BY id LIMIT 2")]
    for lid, p, mt in lok:
        repo.stage_rename(con, run_id="R", location_id=lid, old_path=p, new_path=p + ".x", expected_mtime=mt)
    with con:
        con.execute("UPDATE location SET present = 0 WHERE id = ?", (lok[0][0],))
    wynik = writeback.commit_renames(con, "R", now="2026-07-03T13:00:00")
    assert len(wynik.applied) == 1 and len(wynik.skipped) == 1
    with con:
        con.execute("UPDATE location SET present = 1 WHERE id = ?", (lok[0][0],))
    k = _karta(con, "K", 2, "2026-07-03T14:00:00")
    lid, p, _mt = lok[0]
    assert repo.relocate_location(con, location_id=lid, new_path=p + ".x", now="2026-07-03T15:00:00")
    assert repo.relocate_location(con, location_id=lid, new_path=p, now="2026-07-03T15:10:00")
    con.close()
    con, v = _restart(path)
    try:
        assert v._undo_mode == "macro" and v._undo_commity == (k,)
    finally:
        _zamknij_widok(v)
        con.close()


def test_cofniecie_pozniejszej_zmiany_nazw_przed_wczesniejsza(qapp, tmp_path):
    """Zmiana nazw A→B (`tam`, 13:00), zapis kart K (13:30), zmiana B→C tej samej lokacji (`dalej`, 14:00), potem
    cofnięcie `dalej` i dopiero `tam` (CLI - późniejszy przebieg cofnięty pierwszy). Ostatnim zapisem szuflady jest
    `dalej`, cofnięty w całości: bez „Cofnij”, także bez „Cofnij” starszych kart. Falsyfikator: wiersz czekający na
    cofnięcie wstrzymuje zapis następnego (`dalej` bez zapisu, „Cofnij” kart)."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    (wiersz,) = _nazwy(con, "tam", [0], "2026-07-03T13:00:00")
    _karta(con, "K", 1, "2026-07-03T13:30:00")
    lid, p, mt = con.execute("SELECT id, path, mtime FROM location WHERE id = ?", (wiersz["location_id"],)).fetchone()
    repo.stage_rename(con, run_id="dalej", location_id=lid, old_path=p, new_path=p + ".y", expected_mtime=mt)
    assert len(writeback.commit_renames(con, "dalej", now="2026-07-03T14:00:00").applied) == 1
    writeback.undo_renames(con, "dalej", now="2026-07-03T15:00:00")
    writeback.undo_renames(con, "tam", now="2026-07-03T16:00:00")
    assert [r["status"] for r in con.execute("SELECT status FROM pending_renames ORDER BY id")] == ["skipped"] * 2
    con.close()
    con, v = _restart(path)
    try:
        assert _bez_cofnij(v) and v._undo_mode is None
        assert queries.ostatni_zapis_szuflady(con) is None
    finally:
        _zamknij_widok(v)
        con.close()


def test_zapis_nazw_po_cofnieciach_pary_odwrotnej_odmawia_wyboru(qapp, tmp_path):
    """A→B (`tam`), B→A (`powrot`), cofnięcie `powrot`, cofnięcie `tam`, zapis kart K na innym pliku, znów A→B
    (`ponowna`): A→B po zapisie `powrot` bywa jego cofnięciem albo zapisem `ponowna` - historia nie mówi, czy ostatni
    zapis nazw był przed kartami, czy po nich. JAWNA odmowa wyboru: bez „Cofnij”, także bez „Cofnij” kart.
    Falsyfikator: przypisanie zachłanne (zapis `ponowna` przed kartami - „Cofnij” kart, choć ostatnim zapisem mogą
    być nazwy)."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _nazwy(con, "tam", [0], "2026-07-03T13:00:00")
    _nazwy(con, "powrot", [0], "2026-07-03T14:00:00", wstecz=True)
    writeback.undo_renames(con, "powrot", now="2026-07-03T15:00:00")
    writeback.undo_renames(con, "tam", now="2026-07-03T16:00:00")
    _karta(con, "K", 1, "2026-07-03T16:30:00")
    _nazwy(con, "ponowna", [0], "2026-07-03T17:00:00")
    con.close()
    con, v = _restart(path)
    try:
        assert _bez_cofnij(v) and v._undo_mode is None
        assert queries.ostatni_zapis_szuflady(con) is None
    finally:
        _zamknij_widok(v)
        con.close()


def test_cudze_przepiecie_w_oknie_zapisu_odmawia_wyboru(qapp, tmp_path):
    """Zapis kart, potem zmiana nazw A→B, a po niej przepięcia lokacji B→A i A→B bez gestu nazw (zdarzenia bez wiersza
    stagingu) w oknie tego wiersza: którym zdarzeniem był zapis, historia nie mówi - JAWNA odmowa wyboru, bez „Cofnij”
    nazw i bez spadania do starszych kart. Falsyfikator: cudze zdarzenie z parą wiersza pominięte w oknie."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _karta(con, "K", 1, "2026-07-03T12:00:00")
    (wiersz,) = _nazwy(con, "N", [0], "2026-07-03T13:00:00")
    lid, stara, nowa = wiersz["location_id"], wiersz["old_path"], wiersz["new_path"]
    assert repo.relocate_location(con, location_id=lid, new_path=stara, now="2026-07-03T14:00:00")
    assert repo.relocate_location(con, location_id=lid, new_path=nowa, now="2026-07-03T15:00:00")
    con.close()
    con, v = _restart(path)
    try:
        assert _bez_cofnij(v) and v._undo_mode is None
        assert queries.ostatni_zapis_szuflady(con) is None
    finally:
        _zamknij_widok(v)
        con.close()


# Przypisanie zdarzeń lokacji do jej wierszy zmian nazw - czysta reguła (`queries._zapisy_lokacji`) na wierszach
# i zdarzeniach syntetycznych: identyfikatory rosną z czasem, `wiersz` = `$.pending_rename` zdarzenia.


def _wiersz(id_, stara, nowa, status="applied"):
    """`status` 'applied', 'cofniety' ('skipped' z powodem cofnięcia - zapis był) albo 'skipped' (kopia zniknęła przed
    zapisem - zapisu nie było); pole `cofniety` jak w odczycie `queries._ostatni_zapis_nazw`."""
    return {"id": id_, "run_id": f"p{id_}", "location_id": 1, "old_path": stara, "new_path": nowa,
            "status": "skipped" if status == "cofniety" else status, "cofniety": status == "cofniety"}


def _zdarzenie(id_, przed, po, wiersz=None):
    return {"id": id_, "przed": przed, "po": po, "wiersz": wiersz}


def _granice(wiersze, zdarzenia):
    return [(w["id"], granica, jednoznaczny) for w, granica, jednoznaczny in queries._zapisy_lokacji(wiersze, zdarzenia)]


def test_przypisanie_para_odwrotna_i_cofniecie_po_kolei():
    """A→B, potem B→A - zapisy dwóch wierszy; cofnięcie drugiego (A→B) należy do niego, nie do pierwszego.
    Falsyfikatory: para odwrotna jako konflikt; zdarzenie przypisane pierwszemu pasującemu wierszowi bez kolejności."""
    tam, powrot = _wiersz(1, "A", "B"), _wiersz(2, "B", "A")
    zd = [_zdarzenie(10, "A", "B"), _zdarzenie(11, "B", "A")]
    assert _granice([tam, powrot], zd) == [(1, 10, True), (2, 11, True)]
    powrot.update(status="skipped", cofniety=True)
    assert _granice([tam, powrot], zd + [_zdarzenie(12, "A", "B")]) == [(1, 10, True), (2, 11, True)]
    # Cofnięty bez zdarzenia cofnięcia - historia sprzeczna z faktem wiersza: odmowa wyboru.
    assert _granice([tam, powrot], zd) == [(1, 10, False), (2, 11, False)]
    # Kopia zniknęła przed zapisem (bez cofnięcia) - zapisu nie było, a zdarzenie z jego parą jest cudze w oknie
    # pierwszego wiersza.
    powrot["cofniety"] = False
    assert _granice([tam, powrot], zd) == [(1, 10, False), (2, None, True)]


def test_przypisanie_wiersz_zapisany_czeka_na_swoj_zapis():
    """Zdarzenie, które nie pasuje do bieżącego wiersza 'applied', jest cudze - nie przeskakuje do dalszego wiersza.
    Falsyfikator: przeskok przez wiersz zapisany (zdarzenie dalszego wiersza przed zapisem bieżącego)."""
    assert _granice([_wiersz(1, "A", "B"), _wiersz(2, "X", "Y")],
                    [_zdarzenie(10, "X", "Y"), _zdarzenie(11, "A", "B")]) == [(1, 11, True), (2, None, True)]


def test_przypisanie_fakt_na_wierszu_wygrywa():
    """Zdarzenie z identyfikatorem wiersza (rekoncyliacja) jest jego zapisem albo cofnięciem bez heurystyki - także
    gdy wcześniejsze zdarzenia tej pary bez identyfikatora stoją w oknie. Identyfikator spoza zbioru - zdarzenie
    cudze. Falsyfikatory: fakt jako zwykłe zdarzenie ciągu; fakt sprawdzany oknem; cudzy identyfikator pominięty."""
    w = _wiersz(1, "A", "B")
    przed = [_zdarzenie(10, "A", "B"), _zdarzenie(11, "B", "A")]
    assert _granice([w], przed + [_zdarzenie(12, "A", "B", wiersz=1)]) == [(1, 12, True)]
    w.update(status="skipped", cofniety=True)
    assert _granice([w], [_zdarzenie(10, "A", "B"), _zdarzenie(11, "B", "A", wiersz=1)]) == [(1, 10, True)]
    assert _granice([w], [_zdarzenie(10, "A", "B", wiersz=1)]) == [(1, 10, False)]   # bez cofnięcia
    assert _granice([_wiersz(1, "A", "B")], [_zdarzenie(10, "A", "B"), _zdarzenie(11, "B", "A", wiersz=9)]) == \
        [(1, 10, False)]
    assert _granice([_wiersz(1, "A", "B")], [_zdarzenie(10, "A", "B", wiersz=9)]) == [(1, None, True)]
    # Wiersz z zapisem z faktu nie zatrzymuje ciągu - zapis następnego wiersza idzie dalej; cofnięcie przed zapisem
    # z faktu nie jest jego cofnięciem.
    assert _granice([_wiersz(1, "A", "B"), _wiersz(2, "B", "C")],
                    [_zdarzenie(11, "A", "B", wiersz=1), _zdarzenie(12, "B", "C")]) == [(1, 11, True), (2, 12, True)]
    assert _granice([_wiersz(1, "A", "B", "cofniety")], [_zdarzenie(10, "B", "A"), _zdarzenie(11, "A", "B", wiersz=1)]) \
        == [(1, 11, False)]


def test_przypisanie_skipped_bez_sladu_cofniecia_nie_jest_zapisem():
    """Wiersz 'skipped' tej samej pary przed wierszem zapisanym: kopia zniknęła przed zapisem - zdarzenie należy do
    następnego wiersza; cofnięty - zapis i cofnięcie są jego. Falsyfikator: wiersz bez zapisu bierze pierwsze
    pasujące zdarzenie."""
    pominiety, zapisany = _wiersz(1, "A", "B", "skipped"), _wiersz(2, "A", "B")
    assert _granice([pominiety, zapisany], [_zdarzenie(10, "A", "B")]) == [(1, None, True), (2, 10, True)]
    assert _granice([_wiersz(1, "A", "B", "cofniety"), zapisany],
                    [_zdarzenie(10, "A", "B"), _zdarzenie(11, "B", "A"), _zdarzenie(12, "A", "B")]) == \
        [(1, 10, True), (2, 12, True)]
    # Kopia zniknęła przed zapisem, a lokacja potem przepięta A→B i z powrotem bez gestu nazw: para wiersza w
    # zdarzeniach nie udaje zapisu i cofnięcia - zapisu nie było. Falsyfikator: przypisanie najtańsze (zapis 20,
    # cofnięcie 21) wbrew faktowi wiersza - granica późniejsza niż prawdziwy ostatni zapis.
    assert _granice([pominiety], [_zdarzenie(20, "A", "B"), _zdarzenie(21, "B", "A")]) == [(1, None, True)]
    assert _granice([_wiersz(1, "C", "D", "skipped"), zapisany], [_zdarzenie(10, "A", "B")]) == \
        [(1, None, True), (2, 10, True)]                 # inna para - przeskok przez pominięty


def test_przypisanie_cofniecia_jak_stos():
    """Zapis A→B, zapis B→C, cofnięcie C→B, cofnięcie B→A (późniejszy przebieg cofnięty pierwszy): zapis drugiego
    wiersza przychodzi, zanim pierwszy dostanie cofnięcie, a cofnięcie należy do najpóźniej zapisanego wiersza, który
    na nie czeka. Falsyfikatory: wiersz czekający na cofnięcie wstrzymuje zapis następnego; cofnięcie do najwcześniej
    zapisanego."""
    pierwszy, drugi = _wiersz(1, "A", "B", "cofniety"), _wiersz(2, "B", "C", "cofniety")
    assert _granice([pierwszy, drugi], [_zdarzenie(10, "A", "B"), _zdarzenie(11, "B", "C"), _zdarzenie(12, "C", "B"),
                                        _zdarzenie(13, "B", "A")]) == [(1, 10, True), (2, 11, True)]
    # A→B i B→A, oba cofnięte: B→A jest najpierw zapisem drugiego wiersza, nie cofnięciem pierwszego (to przychodzi
    # na końcu); zdarzenie jest jednym albo drugim, nigdy oboma.
    tam, powrot = _wiersz(1, "A", "B", "cofniety"), _wiersz(2, "B", "A", "cofniety")
    assert _granice([tam, powrot], [_zdarzenie(10, "A", "B"), _zdarzenie(11, "B", "A"), _zdarzenie(12, "A", "B"),
                                    _zdarzenie(13, "B", "A")]) == [(1, 10, True), (2, 11, True)]
    # Dwa wiersze tej samej pary, oba cofnięte, a lokacja wróciła na A przepięciem bez gestu: jedno cofnięcie na dwa
    # wiersze cofnięte - historia sprzeczna z faktami wierszy, oba niejednoznaczne, granica najnowsza możliwa.
    a, b = _wiersz(1, "A", "B", "cofniety"), _wiersz(2, "A", "B", "cofniety")
    assert _granice([a, b], [_zdarzenie(10, "A", "B"), _zdarzenie(11, "B", "A", wiersz=9), _zdarzenie(12, "A", "B"),
                             _zdarzenie(13, "B", "A")]) == [(1, 12, False), (2, 12, False)]


def test_przypisanie_zapis_albo_cofniecie_to_niejednoznacznosc():
    """Wiersze A→B i B→A (oba cofnięte) oraz trzeci A→B zapisany, zdarzenia A→B, B→A, A→B, B→A, A→B: A→B po zapisie
    B→A jest zapisem trzeciego wiersza ALBO cofnięciem drugiego - oba przypisania spójne i bez zdarzeń cudzych.
    Trzeci wiersz niejednoznaczny z granicą najnowszą (14), nie pierwszą znalezioną (12). Falsyfikator: zachłanne
    przypisanie zdarzenia zapisowi (granica 12, jednoznaczna) - zapis kart między 13 a 14 wygrałby z ostatnim zapisem
    nazw."""
    wiersze = [_wiersz(1, "A", "B", "cofniety"), _wiersz(2, "B", "A", "cofniety"), _wiersz(3, "A", "B")]
    zd = [_zdarzenie(10, "A", "B"), _zdarzenie(11, "B", "A"), _zdarzenie(12, "A", "B"), _zdarzenie(13, "B", "A"),
          _zdarzenie(14, "A", "B")]
    assert _granice(wiersze, zd) == [(1, 10, True), (2, 11, True), (3, 14, False)]


def test_przypisanie_zapis_z_faktu_to_granica_kolejnosci():
    """Przepięcia A→B, B→A bez gestu, zapis A→B z faktem (20), potem B→A bez identyfikatora (30): zapis drugiego wiersza
    przychodzi po zapisie pierwszego, także znanym z faktu - B→A z 10 jest cudze. Falsyfikator: zdarzenie sprzed
    zapisu z faktu przypisane dalszemu wierszowi (granica 10 - „Cofnij” starszego przebiegu)."""
    wiersze = [_wiersz(1, "A", "B"), _wiersz(2, "B", "A")]
    zd = [_zdarzenie(5, "A", "B"), _zdarzenie(10, "B", "A"), _zdarzenie(20, "A", "B", wiersz=1),
          _zdarzenie(30, "B", "A")]
    assert _granice(wiersze, zd) == [(1, 20, True), (2, 30, True)]
    # Fakty sprzeczne z kolejnością stagingu (zapis drugiego wiersza przed pierwszym) - bez przypisania spójnego:
    # wszystko niejednoznaczne, granica najnowsza z parą zapisu.
    assert _granice(wiersze, [_zdarzenie(10, "B", "A", wiersz=2), _zdarzenie(20, "A", "B", wiersz=1)]) == \
        [(1, 20, False), (2, 10, False)]
    # To samo, gdy pierwszy wiersz jest cofnięty (zapis i cofnięcie z faktu): nie jest wierszem bez zapisu, więc zapis
    # drugiego go nie przeskakuje. Falsyfikator: zapis z faktu wiersza już przeskoczonego.
    assert _granice([_wiersz(1, "A", "B", "cofniety"), _wiersz(2, "B", "C")],
                    [_zdarzenie(10, "B", "C", wiersz=2), _zdarzenie(20, "A", "B", wiersz=1),
                     _zdarzenie(25, "B", "A", wiersz=1)]) == [(1, 20, False), (2, 10, False)]


def test_przypisanie_zapis_z_faktu_wiersza_bez_zapisu_to_sprzecznosc():
    """Zdarzenie z identyfikatorem wiersza, którego kopia zniknęła przed zapisem (zapisu nie było): fakt zdarzenia
    przeczy faktowi wiersza - historia lokacji sprzeczna w całości, odmowa wyboru także dla dalszego wiersza.
    Falsyfikator: sprzeczność przyjęta dla jednego wiersza (dalszy wiersz jednoznaczny)."""
    assert _granice([_wiersz(1, "A", "B", "skipped"), _wiersz(2, "B", "C")],
                    [_zdarzenie(10, "A", "B", wiersz=1), _zdarzenie(11, "B", "C")]) == [(1, 10, False), (2, 11, False)]


def test_przypisanie_zapis_nie_po_cofnieciu_z_faktu():
    """Wiersz cofnięty z cofnięciem z faktu (10), a zdarzenie z jego parą zapisu przychodzi PÓŹNIEJ (20): zapis nie
    przychodzi po własnym cofnięciu - przypisania spójnego nie ma, odmowa wyboru. Falsyfikator: zapis po cofnięciu
    (granica 20 jednoznaczna)."""
    assert _granice([_wiersz(1, "A", "B", "cofniety")],
                    [_zdarzenie(10, "B", "A", wiersz=1), _zdarzenie(20, "A", "B")]) == [(1, 20, False)]


def test_przypisanie_ponad_limit_to_niejednoznacznosc(monkeypatch):
    """Przeszukiwanie ponad limit węzłów albo kroków - odmowa wyboru (wszystko niejednoznaczne), nie wynik częściowy.
    Bez limitu ta sama historia jest jednoznaczna (zdarzenia innej pary - cudze, poza parą wiersza). Falsyfikatory:
    przerwane przeszukiwanie oddaje przypisania znalezione do chwili przerwania; limit kroków bez skutku."""
    wiersze, zd = [_wiersz(1, "A", "B")], [_zdarzenie(10, "A", "B"), _zdarzenie(11, "X", "Y"), _zdarzenie(12, "X", "Y")]
    assert _granice(wiersze, zd) == [(1, 10, True)]
    monkeypatch.setattr(queries, "_LIMIT_PRZYPISAN", 4)       # pierwsze przypisanie pełne, przerwanie przy drugim
    assert _granice(wiersze, zd) == [(1, 10, False)]
    monkeypatch.setattr(queries, "_LIMIT_PRZYPISAN", 20000)
    monkeypatch.setattr(queries, "_LIMIT_KROKOW", 2)
    assert _granice(wiersze, zd) == [(1, 10, False)]


def test_przypisanie_zapis_po_kolei_stagingu():
    """Wiersz 'skipped' bez zapisu przeskoczony raz (zdarzenie innej pary trafiło do dalszego wiersza) nie wraca:
    późniejszy zapis z jego parą należy do następnego wiersza w kolejności stagingu. Falsyfikator: zapis szukany od
    pierwszego wiersza lokacji."""
    assert _granice([_wiersz(1, "A", "B", "skipped"), _wiersz(2, "A", "C", "cofniety"), _wiersz(3, "A", "B", "cofniety")],
                    [_zdarzenie(10, "A", "C"), _zdarzenie(11, "C", "A"), _zdarzenie(12, "A", "B"),
                     _zdarzenie(13, "B", "A")]) == [(1, None, True), (2, 10, True), (3, 12, True)]


def test_przypisanie_konflikt_w_oknie_wiersza():
    """Cudze zdarzenia pary wiersza po jego zapisie: konflikt, granica = najnowsze zdarzenie w kierunku zapisu. Okno
    kończy się na pierwszym zdarzeniu następnego wiersza i zaczyna po ostatnim poprzedniego, a powrót na starą
    ścieżkę PRZED zapisem wiersza nie jest konfliktem. Falsyfikatory: konflikt pominięty; granica bez cudzych
    zapisów; okno bez końca; okno bez początku; przyjazd przed zapisem jako konflikt."""
    assert _granice([_wiersz(1, "A", "B")], [_zdarzenie(10, "A", "B"), _zdarzenie(11, "B", "A"),
                                             _zdarzenie(12, "A", "B")]) == [(1, 12, False)]
    assert _granice([_wiersz(1, "A", "B"), _wiersz(2, "B", "C")],
                    [_zdarzenie(10, "A", "B"), _zdarzenie(11, "B", "C"), _zdarzenie(12, "B", "A", wiersz=9)]) == \
        [(1, 10, True), (2, 11, True)]
    assert _granice([_wiersz(1, "A", "B"), _wiersz(2, "B", "A")],
                    [_zdarzenie(9, "B", "A", wiersz=9), _zdarzenie(10, "A", "B"), _zdarzenie(11, "B", "A")]) == \
        [(1, 10, True), (2, 11, True)]
    assert _granice([_wiersz(1, "B", "A")], [_zdarzenie(10, "A", "B"), _zdarzenie(11, "B", "A")]) == [(1, 11, True)]


def test_ostatni_zapis_nazw_z_jednej_migawki(qapp, tmp_path, monkeypatch):
    """Odczyt ostatniego zapisu pod blokadą w JEDNEJ migawce: drugie połączenie cofa zmianę nazw między odczytem
    przebiegów czekających a odczytem zapisu nazw (bariera w `queries._ostatni_zapis_nazw` przy drugim odczycie -
    pierwszy idzie przed blokadą). „Cofnij” nazw stoi ze stanem sprzed bariery. Falsyfikator: odczyt bez transakcji
    odczytu (zapis nazw cofnięty - brak „Cofnij”)."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _nazwy(con, "N", [0, 1], "2026-07-03T15:00:00")
    con.close()
    prawdziwy, wolania = queries._ostatni_zapis_nazw, []

    def _z_bariera(c):
        wolania.append(1)
        if len(wolania) == 2:
            con2 = db.connect(path)
            try:
                writeback.undo_renames(con2, "N", now="2026-07-03T16:00:00")
            finally:
                con2.close()
        return prawdziwy(c)
    monkeypatch.setattr(queries, "_ostatni_zapis_nazw", _z_bariera)
    con, v = _restart(path)
    try:
        assert len(wolania) == 2, "bariera nie zadziałała - test nic by nie mierzył"
        assert v._undo_mode == "rename" and v._undo_rename_run_id == "N"
        assert v.drawer.label.text() == i18n.t("grid.rename.renamed_label", n=2)
    finally:
        monkeypatch.undo()
        _zamknij_widok(v)
        con.close()


def test_odmiana_zdania_ostatniej_zmiany_nazw():
    """Wpis mnogi `grid.drawer.last_rename`: PL 1/2/5/12/22, EN 1/2 bez polskich znaków."""
    try:
        assert [i18n.t_plural("grid.drawer.last_rename", n, day="D", undo="U").split(": ")[1].split(" - ")[0]
                for n in (1, 2, 5, 12, 22)] == ["1 plik", "2 pliki", "5 plików", "12 plików", "22 pliki"]
        i18n.set_lang("en")
        tekst = [i18n.t_plural("grid.drawer.last_rename", n, day="D", undo="U") for n in (1, 2)]
        assert [t.split(": ")[1].split(" - ")[0] for t in tekst] == ["1 file", "2 files"]
        assert not set("".join(tekst)) & _POLSKIE
    finally:
        i18n.set_lang("pl")


# ============================================================ AR-387 - krótka forma powodu (bez okna)


def _powod(kod, **params):
    from horreum.item_reasons import PowodPozycji
    return PowodPozycji(f"proza {kod}", kod, **params)


def _zdanie_krotkie(powod, *, obok=()):
    """Powód z nazwami plików tak, jak mówi go szuflada: `tekst_powodu(sciezki_skrocone(...))`."""
    from horreum.gui.wb_worker import sciezki_skrocone, tekst_powodu
    return tekst_powodu(sciezki_skrocone(powod, obok=obok))


def test_krotka_forma_mowi_nazwy_plikow(qapp):
    """`intent_both_names` z dwiema ścieżkami: krótka forma mówi same nazwy, zdanie i kod jak w pełnej formie.
    Falsyfikator: parametry ścieżek bez skrótu."""
    from horreum.gui.wb_worker import tekst_powodu
    p = _powod("intent_both_names", src=r"X:\L\noc\a.fits", dst=r"X:\L\noc\b.fits")
    assert _zdanie_krotkie(p) == tekst_powodu(_powod("intent_both_names", src="a.fits", dst="b.fits"))
    assert r"X:\L" not in _zdanie_krotkie(p) and r"X:\L\noc\a.fits" in tekst_powodu(p)


def test_krotka_forma_rowne_nazwy_zostaja_pelnymi_sciezkami(qapp):
    """Ta sama nazwa pliku w dwóch katalogach (w tym samym powodzie albo w innym członie zdania - `obok`, nazwy bez
    wielkości liter): pełne ścieżki, bo nazwy nie mówią, który plik gdzie stoi. Dwie ścieżki różne choćby wielkością
    liter katalogu - też pełne (dwa pliki dla zdania); ta sama ścieżka znak w znak w dwóch członach - jedna, skrót.
    Falsyfikatory: kolizja nazw pominięta; ścieżki nosicieli porównane bez wielkości liter."""
    from horreum.gui.wb_worker import tekst_powodu
    p = _powod("intent_both_names", src=r"X:\A\f.fits", dst=r"X:\B\f.fits")
    assert _zdanie_krotkie(p) == tekst_powodu(p)
    q = _powod("intent_sha1_differs", path=r"X:\A\g.fits")
    inny = _powod("intent_no_name", src=r"X:\B\G.FITS", dst=r"X:\B\h.fits")
    assert r"X:\A\g.fits" in _zdanie_krotkie(q, obok=[q, inny])
    krotki = tekst_powodu(_powod("intent_sha1_differs", path="g.fits"))
    assert _zdanie_krotkie(q) == krotki == _zdanie_krotkie(q, obok=[_powod("intent_no_name", src=r"X:\A\g.fits",
                                                                              dst=r"X:\A\h.fits")])
    wielkie = _powod("intent_both_names", src=r"X:\A\g.fits", dst=r"x:\a\g.fits")
    assert _zdanie_krotkie(wielkie) == tekst_powodu(wielkie)
    assert r"X:\A\g.fits" in _zdanie_krotkie(q, obok=[_powod("intent_sha1_differs", path=r"x:\a\G.fits")])


def test_krotka_forma_bez_zmiany_to_ten_sam_powod(qapp):
    """Powód bez ścieżki do skrócenia (nazwa bez katalogu, kolizja nazw, proza, parametry bez ścieżek, powód
    zagnieżdżony bez zmian) wraca TYM SAMYM obiektem - po tożsamości szuflada poznaje, że szczegół z pełnym powodem
    niczego nie dodaje; zmieniony - nowym, z tym samym zdaniem PL i kodem. Falsyfikatory: kopia przy braku zmiany
    (szczegół powtarza zdanie); zmiana powodu zagnieżdżonego niewidoczna dla zewnętrznego."""
    from horreum.gui.wb_worker import sciezki_skrocone
    bez_katalogu = _powod("intent_both_names", src="a.fits", dst="b.fits")
    kolizja = _powod("intent_both_names", src=r"X:\A\f.fits", dst=r"X:\B\f.fits")
    wewn = _powod("target_taken_db", location=7, volume="V", path="nowa.fits")
    zagniezdzony = _powod("intent_target_taken", inner=wewn, location=3, path="stara.fits")
    for p in (bez_katalogu, kolizja, zagniezdzony, _powod("disk_silent", detail="cisza"), "proza X:\\L\\a.fits"):
        assert sciezki_skrocone(p) is p, p
    zmieniony = _powod("intent_target_taken", inner=_powod("target_taken_db", location=7, volume="V",
                                                           path=r"X:\L\nowa.fits"), location=3, path="stara.fits")
    skrot = sciezki_skrocone(zmieniony)
    assert skrot is not zmieniony and str(skrot) == str(zmieniony) and skrot.code == zmieniony.code
    assert dict(dict(skrot.params)["inner"].params)["path"] == "nowa.fits"


def test_krotka_forma_powod_zagniezdzony_i_lista(qapp):
    """Ścieżka w powodzie zagnieżdżonym (`intent_target_taken` → `target_taken_db`) i w liście `paths` - nazwy.
    Falsyfikator: skrót tylko na najwyższym poziomie albo bez listy."""
    wewn = _powod("target_taken_db", location=7, volume="V", path=r"X:\L\noc\nowa.fits")
    tekst = _zdanie_krotkie(_powod("intent_target_taken", inner=wewn, location=3, path=r"X:\L\noc\stara.fits"))
    assert "nowa.fits" in tekst and "stara.fits" in tekst and r"X:\L" not in tekst, tekst
    lista = _zdanie_krotkie(_powod("undo_files_kept", paths=(r"X:\L\a.fits", r"X:\L\b.fits")))
    assert "a.fits, b.fits" in lista and r"X:\L" not in lista, lista


def test_krotka_forma_proze_mowi_przez_czytelny_powod(qapp):
    """Szew z `czytelny_powod`: parametr prozą (tekst systemu ze ścieżką w zapisie `repr`) idzie tą samą drogą co w
    pełnej formie - oczekiwanie liczone funkcją w biegu testu, więc test mówi to samo przed i po zmianie
    `czytelny_powod`. Falsyfikator: krótka forma z surową prozą powodu."""
    from horreum.gui.wb_worker import czytelny_powod
    detail = "OSError: [WinError 87] Parametr jest niepoprawny: 'X:\\\\L\\\\b.fits'"
    tekst = _zdanie_krotkie(_powod("torn_other", dst=r"X:\L\noc\b.fits", detail=detail,
                                       db_path=r"X:\L\noc\a.fits", in_flight="commit"))
    assert czytelny_powod(detail) in tekst and "\\\\" not in tekst, tekst
    assert "b.fits" in tekst and r"X:\L\noc" not in tekst, tekst


def test_krotka_forma_bez_kodu_i_bez_wpisu_jak_pelna(qapp):
    """Proza bez kodu i powód z kodem bez kompletnych parametrów wpisu: krótka forma = pełna (TOTALNE)."""
    from horreum.gui.wb_worker import tekst_powodu
    assert _zdanie_krotkie(r"plik X:\L\a.fits zajęty") == tekst_powodu(r"plik X:\L\a.fits zajęty")
    niepelny = _powod("intent_both_names", src=r"X:\L\a.fits")
    assert _zdanie_krotkie(niepelny) == tekst_powodu(niepelny)


def test_ta_sama_nazwa_w_dwoch_odmowach_zdania_mowi_pelne_sciezki(qapp, tmp_path, monkeypatch):
    """Dwa przebiegi nazw rozdarte (prawdziwy pisarz, atrapy wyłącznie porażki przepięcia i kompensacji - wzór
    `test_gui_grid_szuflada`), a plik każdego pod nową nazwą ma inny `mtime`: rekoncyliacja odmawia obu
    (`intent_mtime_differs`). Oba pliki noszą tę samą nazwę w dwóch katalogach - zdanie szuflady mówi o nich PEŁNYMI
    ścieżkami (sama nazwa dwa razy nie mówi, który plik gdzie stoi). Falsyfikator: kolizje nazw liczone osobno dla
    każdej odmowy zdania."""
    import sqlite3
    from test_gui_grid_szuflada import NOW
    from test_rename import _bez_kompensacji, _pad_raz
    path, con, _p = _baza_szuflady(tmp_path, 4)
    lok = con.execute("SELECT id, path, mtime FROM location ORDER BY id").fetchall()
    rozdarte = []
    for run, wiersze in (("A", lok[:2]), ("B", lok[2:])):
        for i, (lid, p, mt) in enumerate(wiersze):
            katalog = os.path.join(os.path.dirname(p), f"noc_{run}{i}")
            os.makedirs(katalog)
            nowa = os.path.join(katalog, "klatka.fits")
            repo.stage_rename(con, run_id=run, location_id=lid, old_path=p, new_path=nowa, expected_mtime=mt)
            if i == 0:
                rozdarte.append(nowa)
        pytania = []
        with monkeypatch.context() as m:
            _pad_raz(m, repo, "_apply_relocation", sqlite3.OperationalError("disk I/O error"))
            _bez_kompensacji(m)
            writeback.commit_renames(con, run, now=NOW, should_cancel=lambda p=pytania: p.append(1) or len(p) > 1)
        # `mtime` pod nową nazwą zmieniony zaraz po rozdarciu - rekoncyliacja na wejściu następnego zapisu odmawia.
        st = os.stat(rozdarte[-1])
        os.utime(rozdarte[-1], (st.st_atime, st.st_mtime + 3600))
    assert [f.reason.code for f in writeback.reconcile_renames(con, now=NOW)] == ["intent_mtime_differs"] * 2
    con.close()
    con, v = _restart(path)
    try:
        tekst = v.drawer.result.text()
        assert all(nowa in tekst for nowa in rozdarte), tekst
        assert v.drawer.result.szczegol() == "", v.drawer.result.szczegol()   # nic nie skrócone - bez szczegółu
    finally:
        _zamknij_widok(v)
        con.close()


def test_parametry_sciezek_w_kontrakcie_powodu():
    """Parametry, które krótka forma skraca, są parametrami tekstowymi kontraktu powodu, a `paths` - listą: zmiana
    nazwy parametru ścieżki w rdzeniu (`item_reasons.PARAM_KINDS`) czerwieni ten test, zamiast wyłączyć skrót po
    cichu."""
    from horreum.gui.wb_worker import _PARAMY_SCIEZEK
    from horreum.item_reasons import PARAM_KINDS
    assert _PARAMY_SCIEZEK and all(PARAM_KINDS.get(n) == "text" for n in _PARAMY_SCIEZEK), _PARAMY_SCIEZEK
    assert PARAM_KINDS.get("paths") == "list"
    assert json.dumps(sorted(_PARAMY_SCIEZEK)) == json.dumps(["copy", "db_path", "dst", "path", "src", "tmp"])
