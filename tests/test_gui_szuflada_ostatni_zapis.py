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
    ścieżkami (sama nazwa dwa razy nie mówi, który plik gdzie stoi), zwięźle (bez przedrostka formy pełnej), a oba
    pełne powody (czas UTC) stoją w szczególe, choć ścieżek nie skróciło (AR-387) - w kolejności członów zdania, każdy
    raz. Falsyfikatory: kolizje nazw liczone osobno dla każdej odmowy zdania; szczegół tylko przy skróconej ścieżce;
    szczegół w innej kolejności niż człony albo z powtórzeniem."""
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
        os.utime(rozdarte[-1], (st.st_atime, st.st_mtime + 5000))
    assert [f.reason.code for f in writeback.reconcile_renames(con, now=NOW)] == ["intent_mtime_differs"] * 2
    con.close()
    con, v = _restart(path)
    try:
        from horreum.gui.wb_worker import tekst_powodu
        from horreum.item_reasons import z_bazy
        tekst = v.drawer.result.text()
        assert all(nowa in tekst for nowa in rozdarte), tekst
        assert i18n.t("grid.drawer.names_held_refused", reason="")[:20] not in tekst, tekst
        odmowy, _czekajace = queries.powody_zamiarow_nazw(con, {"A", "B"})
        pelne = [z_bazy(w["reason"], w["reason_code"], w["reason_args"]) for w in odmowy]
        pelne.sort(key=lambda p: tekst.index(dict(p.params)["path"]))      # kolejność członów w zdaniu
        linie = v.drawer.result.szczegol().split("\n")
        assert linie == [tekst_powodu(p) for p in pelne] and len(set(linie)) == len(linie) == 2, linie
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


# ============================================================ AR-387 - zwięzłe zdania odmowy rekoncyliacji (wariant B)


def _lokalne(*isos, wzor="%Y-%m-%d %H:%M:%S"):
    """Wyrocznia czasów zdania: znaczniki ISO w czasie lokalnym maszyny testu (liczona w biegu, nie literałem); para
    po dwóch stronach przestawienia zegara maszyny - z przesunięciem strefy (scena w noc przestawienia zostaje
    prawdziwa). Regułę przesunięcia pinuje literałami `test_czasy_lokalne_do_sekundy_remis_i_przestawienie_zegara`."""
    from datetime import datetime
    chwile = [datetime.fromisoformat(i).astimezone() for i in isos]
    strefy = len({c.utcoffset() for c in chwile}) > 1
    return [c.strftime(wzor) + (c.isoformat()[-6:] if strefy else "") for c in chwile]   # `±HH:MM` z ISO


def _warszawa(c):
    """Strefa z przestawieniem zegara bez bazy stref (`tzdata` spoza zależności): czas środkowoeuropejski 2026 -
    letni (+02:00) od 2026-03-29 01:00 UTC do 2026-10-25 01:00 UTC, poza nim zimowy (+01:00)."""
    from datetime import datetime, timedelta, timezone
    lato = datetime(2026, 3, 29, 1, tzinfo=timezone.utc) <= c < datetime(2026, 10, 25, 1, tzinfo=timezone.utc)
    return c.astimezone(timezone(timedelta(hours=2 if lato else 1)))


def test_czasy_lokalne_do_sekundy_remis_i_przestawienie_zegara():
    """`wb_worker.czasy_lokalne` ze strefą podaną konwerterem (wynik nie zależy od strefy maszyny testu): znaczniki ISO
    UTC (`scan._mtime_iso`) w czasie lokalnym do sekundy; różne znaczniki równe do sekundy - pełna precyzja
    (mikrosekundy); para po dwóch stronach przestawienia zegara (godzina podwójna, przeskok) - z przesunięciem strefy;
    ta sama chwila inaczej zapisana (rdzeń porównuje napisy) i znacznik bez strefy obok znacznika ze strefą - napisy
    znak w znak; znaczniki bez strefy - jakie są; ten sam znacznik dwa razy - jeden czas; nieczytelny albo poza
    zakresem konwertera (`OSError`, `OverflowError`) - None. Domyślny konwerter - strefa systemu. Falsyfikatory: czas
    UTC zamiast lokalnego; para z godziny podwójnej jednym czasem ściennym, „pół sekundy” przy godzinie różnicy albo
    z odwróconym porządkiem; remis do sekundy albo ta sama chwila dwoma identycznymi czasami; para bez wspólnej skali
    przeliczona; błąd konwertera poza gałęzią None."""
    from horreum.gui.wb_worker import czasy_lokalne

    def _cl(znaczniki):
        return czasy_lokalne(znaczniki, lokalny=_warszawa)
    a, b = "2026-10-04T17:54:43.120000+00:00", "2026-10-04T17:54:40.990000+00:00"
    assert _cl([a, b]) == ["2026-10-04 19:54:43", "2026-10-04 19:54:40"]
    assert _cl([a, "2026-10-04T17:54:43.870000+00:00"]) == ["2026-10-04 19:54:43.120000",
                                                            "2026-10-04 19:54:43.870000"]
    # Godzina podwójna 2026-10-25 (02:00-03:00 dwa razy): ten sam czas ścienny przy godzinie i pół sekundy różnicy,
    # a para 00:50 / 01:10 UTC odwraca porządek czasu ściennego.
    assert _cl(["2026-10-25T00:30:00+00:00", "2026-10-25T01:30:00.500000+00:00"]) == [
        "2026-10-25 02:30:00+02:00", "2026-10-25 02:30:00+01:00"]
    assert _cl(["2026-10-25T01:10:00+00:00", "2026-10-25T00:50:00+00:00"]) == [
        "2026-10-25 02:10:00+01:00", "2026-10-25 02:50:00+02:00"]
    # Przeskok 2026-03-29 (02:00-03:00 nie istnieje): sekunda różnicy, godzina czasu ściennego.
    assert _cl(["2026-03-29T00:59:59+00:00", "2026-03-29T01:00:00+00:00"]) == [
        "2026-03-29 01:59:59+01:00", "2026-03-29 03:00:00+02:00"]
    # Przesunięcie ujemne i z minutami (strefa -02:30 / -03:30): znak, godziny i minuty przesunięcia.
    def _minus(c):
        from datetime import datetime, timedelta, timezone
        letni = c < datetime(2026, 11, 1, 4, 30, tzinfo=timezone.utc)
        return c.astimezone(timezone(timedelta(hours=-2, minutes=-30) if letni else timedelta(hours=-3, minutes=-30)))
    assert czasy_lokalne(["2026-11-01T04:00:00+00:00", "2026-11-01T05:00:00+00:00"], lokalny=_minus) == [
        "2026-11-01 01:30:00-02:30", "2026-11-01 01:30:00-03:30"]
    ta_sama = ["2026-10-04T17:54:43.120000+00:00", "2026-10-04T19:54:43.120000+02:00"]
    assert _cl(ta_sama) == ta_sama
    mieszane = ["2026-10-04T17:54:43.120000", "2026-10-04T17:54:43.120000+00:00"]
    assert _cl(mieszane) == mieszane
    assert _cl(["2026-10-04T17:54:43.120000", "2026-10-04T17:54:40.990000"]) == ["2026-10-04 17:54:43",
                                                                                "2026-10-04 17:54:40"]
    assert _cl([a, a]) == ["2026-10-04 19:54:43"] * 2
    for zly in ([a, None], [a, "wczoraj"], [a, 5]):
        assert _cl(zly) is None, zly
    for blad in (OSError(22, "Invalid argument"), OverflowError("date value out of range")):
        def _rzuca(_c, blad=blad):
            raise blad
        assert czasy_lokalne([a, b], lokalny=_rzuca) is None, blad
    assert czasy_lokalne([a, b]) == _lokalne(a, b)


def test_zdanie_zwiezle_totalne(monkeypatch):
    """`wb_worker.zdanie_zwiezle` - TOTALNE jak `_zdanie_z_kodu`: wpis wypełniony parametrami powodu (tekst przez
    `tekst_powodu`, liczba bez zmian, czasy lokalne) i polami wołającego (pierwszeństwo przed parametrem powodu o tej
    samej nazwie); czas powodu bez wartości - wariant `<klucz>.no_<pole>` bez tego pola; każdy brak - None, nigdy
    wyjątek: brak klucza albo wariantu, wpis mnogi, proza bez kodu, uwagi, pole bez parametru, None, lista, liczba
    tekstem, czas nieczytelny, wariant z polem czasu bez wartości. Falsyfikatory: zdanie bez sprawdzenia pól; None,
    lista albo uwagi przepuszczone; parametr powodu przed polem wołającego; czas nieczytelny bez odmowy; czas bez
    wartości bez wariantu albo podany do przeliczenia."""
    from horreum.gui.i18n_catalog import CATALOG
    from horreum.gui.wb_worker import tekst_powodu, zdanie_zwiezle
    szablon = "{way} {path} {location} {mtime}|{db_mtime}"
    monkeypatch.setitem(CATALOG, "_test.zwiezle", {"pl": szablon, "en": szablon})
    monkeypatch.setitem(CATALOG, "_test.wewn", {"pl": "{inner}", "en": "{inner}"})
    monkeypatch.setitem(CATALOG, "_test.lista", {"pl": "{paths}", "en": "{paths}"})
    monkeypatch.setitem(CATALOG, "_test.mnogi", {"pl": {"one": "{n}", "few": "{n}", "many": "{n}"},
                                                  "en": {"one": "{n}", "other": "{n}"}})
    monkeypatch.setitem(CATALOG, "_test.zly.no_db_mtime", {"pl": "{way} {db_mtime}", "en": "{way} {db_mtime}"})
    mt, db_mt = "2026-10-04T17:54:43.120000+00:00", "2026-10-04T17:54:40.990000+00:00"

    def _mtime(**zmiany):
        return _powod("intent_mtime_differs", **{"path": "a.fits", "mtime": mt, "db_mtime": db_mt, "location": 3,
                                                 **zmiany})
    lok, lok_db = _lokalne(mt, db_mt)
    assert zdanie_zwiezle("_test.zwiezle", _mtime(), way="D") == f"D a.fits 3 {lok}|{lok_db}"
    assert zdanie_zwiezle("_test.zwiezle", _mtime(way="z powodu"), way="D").startswith("D a.fits ")
    wewn = _powod("target_taken_db", location=7, volume="V", path="nowa.fits")
    assert zdanie_zwiezle("_test.wewn", _powod("intent_target_taken", inner=wewn, location=3, path="s.fits")) \
        == tekst_powodu(wewn)
    bez_db = _powod("intent_mtime_differs", path="a.fits", mtime=mt, location=3)
    niepelne = [bez_db, _mtime(path=None), _mtime(location="3"), _mtime(db_mtime="wczoraj"), _mtime(db_mtime=None),
                _mtime(notes=(_powod("disk_silent", detail="cisza"),)), "proza a.fits"]
    for p in niepelne:
        assert zdanie_zwiezle("_test.zwiezle", p, way="D") is None, p
    assert zdanie_zwiezle("_test.zwiezle", _mtime()) is None                     # pole wołającego nie podane
    assert zdanie_zwiezle("_test.lista", _powod("undo_files_kept", paths=("a.fits", "b.fits"))) is None
    assert zdanie_zwiezle("_test.mnogi", _powod("undo_files_kept", n=2)) is None
    assert zdanie_zwiezle("_test.brak", _mtime(), way="D") is None
    assert zdanie_zwiezle("_test.zly", _mtime(db_mtime=None), way="D") is None
    wariant = "{way} {path} {mtime}"
    monkeypatch.setitem(CATALOG, "_test.zwiezle.no_db_mtime", {"pl": wariant, "en": wariant})
    assert zdanie_zwiezle("_test.zwiezle", _mtime(db_mtime=None), way="D") == f"D a.fits {_lokalne(mt)[0]}"


def test_zwiezle_klucze_odmow_czlowieka_w_parytecie():
    """Zwięzłe zdania szuflady - klucz składany w locie `grid.drawer.refused.<kod>` (kolektor literałów `test_i18n` go
    nie widzi): klucz na KAŻDY kod drogi człowieka (`FramesView._DROGI_ODMOWY_NAZW`) i żaden poza nimi (kod bez zdania
    mówiłby formą pełną po cichu, zdanie bez kodu jest martwe), PL i EN napisem, EN bez polskich znaków; pole `way`
    (droga w zdaniu), pozostałe pola - parametry pełnego wpisu kodu `objchg.item.<kod>` (literówka pola = forma pełna
    na zawsze), szablon kończy się nazwą pliku. Wariant `<kod>.no_<pole>` (czas powodu bez wartości) - tylko dla kodu
    drogi i pola czasu, bez tego pola. Falsyfikatory: kod drogi bez klucza; pole spoza parametrów powodu; nazwa przed
    drogą; wariant z polem, którego powód nie ma."""
    import string
    from horreum.gui import grid as grid_mod
    from horreum.gui.i18n_catalog import CATALOG
    from horreum.gui.wb_worker import _PARAMY_CZASU

    def _pola(s):
        return {f for _, f, _, _ in string.Formatter().parse(s) if f}
    drogi = grid_mod.FramesView._DROGI_ODMOWY_NAZW
    klucze = {k.removeprefix("grid.drawer.refused.") for k in CATALOG if k.startswith("grid.drawer.refused.")}
    assert set(drogi) <= klucze and {k.partition(".")[0] for k in klucze} == set(drogi), klucze
    for klucz in klucze:
        kod, _, wariant = klucz.partition(".")
        bez = wariant.removeprefix("no_")
        assert not wariant or (wariant.startswith("no_") and bez in _PARAMY_CZASU), klucz
        for lang in ("pl", "en"):
            szablon = CATALOG[f"grid.drawer.refused.{klucz}"][lang]
            assert isinstance(szablon, str) and "way" in _pola(szablon), (klucz, lang)
            assert _pola(szablon) - {"way"} <= _pola(CATALOG[f"objchg.item.{kod}"][lang]) - {bez}, (klucz, lang)
            assert szablon.endswith(("{path}", "{dst}")), (klucz, lang)
        assert not set(CATALOG[f"grid.drawer.refused.{klucz}"]["en"]) & _POLSKIE, klucz


def _odmowa_mtime(tmp_path, monkeypatch, przesun=None):
    """Zapis nazw rozdarty (`test_gui_grid_szuflada._nazwy_rozdarte` - prawdziwy pisarz, atrapy wyłącznie porażki
    przepięcia i kompensacji), potem plik pod nową nazwą z `mtime` przestawionym `przesun(ns) → ns` albo - `przesun`
    None - kopia w bazie bez `mtime` (znacznik „przeczytaj od nowa” drogą rdzenia `repo.mark_location_rescan`):
    rekoncyliacja drugim połączeniem odmawia `intent_mtime_differs`. Restart programu. Zwraca (połączenie, widok,
    pełny powód odmowy z bazy)."""
    from horreum.item_reasons import z_bazy
    from test_gui_grid_szuflada import NOW, _nazwy_rozdarte, _rekoncyliacja_obok
    path, _pliki, run = _nazwy_rozdarte(tmp_path, monkeypatch)
    con = db.connect(path)
    nowa, lid = con.execute("SELECT new_path, location_id FROM pending_renames WHERE in_flight IS NOT NULL").fetchone()
    if przesun is None:
        repo.mark_location_rescan(con, location_id=lid, now=NOW, reason="przeczytaj od nowa")
    con.close()
    if przesun is not None:
        st = os.stat(nowa)
        os.utime(nowa, ns=(st.st_atime_ns, przesun(st.st_mtime_ns)))
    assert [f.reason.code for f in _rekoncyliacja_obok(path)] == ["intent_mtime_differs"]
    con, v = _restart(path)
    (w,), _czekajace = queries.powody_zamiarow_nazw(con, {run})
    return con, v, z_bazy(w["reason"], w["reason_code"], w["reason_args"])


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_odmowa_mtime_mowi_czasy_lokalne_i_nazwe_na_koncu(qapp, tmp_path, monkeypatch, lang):
    """Odmowa rekoncyliacji „inny mtime” (prawdziwy rdzeń): zwięzłe zdanie szuflady - bez przedrostka formy pełnej, oba
    czasy w czasie lokalnym do sekundy, droga człowieka, NAZWA pliku na końcu; surowego czasu UTC i pełnej ścieżki
    w zdaniu nie ma - stoją w szczególe zdania z pełnym powodem. EN tak samo, bez polskich znaków. Falsyfikatory: człon
    formą pełną; `db_mtime` poza czasami lokalnymi."""
    from horreum.gui.wb_worker import tekst_powodu
    i18n.set_lang(lang)
    con, v, odmowa = _odmowa_mtime(tmp_path, monkeypatch, lambda ns: ns + 5000 * 10**9)
    try:
        p = dict(odmowa.params)
        nazwa, tekst = os.path.basename(p["path"]), v.drawer.result.text()
        mt, db_mt = _lokalne(p["mtime"], p["db_mtime"])
        assert tekst == i18n.t("grid.drawer.refused.intent_mtime_differs", path=nazwa, mtime=mt, db_mtime=db_mt,
                               way=i18n.t("grid.drawer.names_way_check")), tekst
        assert tekst.endswith(": " + nazwa), tekst
        assert p["mtime"] not in tekst and p["db_mtime"] not in tekst and p["path"] not in tekst, tekst
        assert i18n.t("grid.drawer.names_held_refused", reason="")[:20] not in tekst, tekst
        assert v.drawer.result.szczegol() == tekst_powodu(odmowa) and p["mtime"] in v.drawer.result.szczegol()
        if lang == "en":
            assert not set(tekst) & _POLSKIE, tekst
    finally:
        i18n.set_lang("pl")
        _zamknij_widok(v)
        con.close()


def test_odmowa_mtime_rowny_do_sekundy_mowi_pelna_precyzje(qapp, tmp_path, monkeypatch):
    """`mtime` pliku w TEJ SAMEJ sekundzie co kopia w bazie, inna część ułamkowa (rdzeń porównuje napisy - odmawia):
    zwięzłe zdanie mówi oba czasy z mikrosekundami - „inny mtime” z dwoma identycznymi czasami do sekundy kłamałby.
    Falsyfikator: czasy wyłącznie do sekundy."""
    def _ta_sama_sekunda(ns):
        sekunda, ulamek = divmod(ns, 10**9)
        return sekunda * 10**9 + (250_000_000 if ulamek >= 500_000_000 else 750_000_000)
    con, v, odmowa = _odmowa_mtime(tmp_path, monkeypatch, _ta_sama_sekunda)
    try:
        p = dict(odmowa.params)
        assert len(set(_lokalne(p["mtime"], p["db_mtime"]))) == 1, p   # remis do sekundy - scena jest prawdziwa
        pelne = _lokalne(p["mtime"], p["db_mtime"], wzor="%Y-%m-%d %H:%M:%S.%f")
        assert pelne[0] != pelne[1] and all(c in v.drawer.result.text() for c in pelne), v.drawer.result.text()
    finally:
        _zamknij_widok(v)
        con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_odmowa_obu_nazw_mowi_zwiezle_z_nazwami_na_koncu(qapp, tmp_path, monkeypatch, lang):
    """Odmowa „plik pod obiema nazwami” (prawdziwy rdzeń): zwięzłe zdanie - krótki powód, droga człowieka („usuń jedną
    kopię, potem „Przyjmij nowe” (Dostawa)”), obie NAZWY plików na końcu; pełny powód w szczególe. EN bez polskich
    znaków. Falsyfikator: człon formą pełną (przedrostek, nazwy w środku zdania)."""
    from horreum.gui.wb_worker import tekst_powodu
    from horreum.item_reasons import z_bazy
    from test_gui_szuflada_przebieg import _odmowa_obu_nazw
    i18n.set_lang(lang)
    _path, con, v, stara = _odmowa_obu_nazw(tmp_path, monkeypatch)
    try:
        v.set_writeback_busy(True)
        v.set_writeback_busy(False)
        run, nowa = con.execute("SELECT run_id, new_path FROM pending_renames WHERE in_flight IS NOT NULL").fetchone()
        droga = i18n.t("grid.drawer.names_way_both", receive=i18n.t("pipeline.receive"), nav=i18n.t("nav.dostawa"))
        tekst = v.drawer.result.text()
        assert tekst == i18n.t("grid.drawer.refused.intent_both_names", src=os.path.basename(stara),
                               dst=os.path.basename(nowa), way=droga), tekst
        assert tekst.endswith(os.path.basename(stara) + " / " + os.path.basename(nowa)), tekst
        (w,), _czekajace = queries.powody_zamiarow_nazw(con, {run})
        assert v.drawer.result.szczegol() == tekst_powodu(z_bazy(w["reason"], w["reason_code"], w["reason_args"]))
        if lang == "en":
            assert not set(tekst) & _POLSKIE, tekst
    finally:
        i18n.set_lang("pl")
        _zamknij_widok(v)
        con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_odmowa_mtime_bez_czasu_w_bazie_mowi_brak_w_bazie(qapp, tmp_path, monkeypatch, lang):
    """Kopia w bazie bez `mtime` (znacznik „przeczytaj od nowa” `repo.mark_location_rescan` - prawdziwy rdzeń):
    rekoncyliacja odmawia „inny mtime” z `db_mtime` None. Zwięzłe zdanie mówi czas pliku i „brak w bazie” (nie
    „None”), drogę człowieka i nazwę na końcu; pełny powód w szczególe. Bez wariantu zdania w katalogu człon mówi
    formą pełną (przedrostek, krótka forma powodu, droga człowieka), nigdy wyjątkiem w oknie. Wyrocznie z
    `os.path.basename` i literału. Falsyfikatory: wariant pominięty (forma pełna z „None”); czas bez wartości podany do
    przeliczenia; forma pełna bez drogi."""
    from horreum.gui.i18n_catalog import CATALOG
    from horreum.gui.wb_worker import tekst_powodu
    from horreum.item_reasons import PowodPozycji
    i18n.set_lang(lang)
    con, v, odmowa = _odmowa_mtime(tmp_path, monkeypatch)
    try:
        p = dict(odmowa.params)
        assert p["db_mtime"] is None, odmowa.params
        nazwa, tekst, droga = os.path.basename(p["path"]), v.drawer.result.text(), i18n.t("grid.drawer.names_way_check")
        assert tekst == i18n.t("grid.drawer.refused.intent_mtime_differs.no_db_mtime", path=nazwa,
                               mtime=_lokalne(p["mtime"])[0], way=droga), tekst
        assert {"pl": " / brak w bazie)", "en": " / none in the database)"}[lang] in tekst, tekst
        assert "None" not in tekst and tekst.endswith(": " + nazwa), tekst
        assert v.drawer.result.szczegol() == tekst_powodu(odmowa)
        monkeypatch.delitem(CATALOG, "grid.drawer.refused.intent_mtime_differs.no_db_mtime")
        krotki = PowodPozycji(str(odmowa), odmowa.code,
                              **{n: os.path.basename(x) if n == "path" else x for n, x in odmowa.params})
        assert v._zdanie_wylaczonych()[1:] == (
            i18n.t("grid.drawer.names_held_refused", reason=tekst_powodu(krotki)) + droga, tekst_powodu(odmowa))
    finally:
        i18n.set_lang("pl")
        _zamknij_widok(v)
        con.close()


# Droga człowieka per kod odmowy - wyrocznia LITERAŁEM, niezależna od mapy produktu (`FramesView._DROGI_ODMOWY_NAZW`).
_DROGA_KODU = {
    "intent_both_names": "grid.drawer.names_way_both",
    "intent_no_name": "grid.drawer.names_way_none",
    "intent_mtime_differs": "grid.drawer.names_way_check",
    "intent_sha1_differs": "grid.drawer.names_way_check",
    "intent_target_taken": "grid.drawer.names_way_taken",
}
_NA_KONCU_CELU = {"pl": ": historię renamu niesie lokacja 3 pod stara.fits",
                  "en": ": the move history is carried by location 3 at stara.fits"}


@pytest.mark.parametrize("lang", ["pl", "en"])
@pytest.mark.parametrize("kod, parametry, krotkie, koniec", [
    ("intent_both_names", {"src": r"X:\L\noc\a.fits", "dst": r"X:\L\noc\b.fits"}, {"src": "a.fits", "dst": "b.fits"},
     {"pl": ": a.fits / b.fits", "en": ": a.fits / b.fits"}),
    ("intent_no_name", {"src": r"X:\L\noc\a.fits", "dst": r"X:\L\noc\b.fits"}, {"src": "a.fits", "dst": "b.fits"},
     {"pl": ": a.fits / b.fits", "en": ": a.fits / b.fits"}),
    ("intent_mtime_differs", {"path": r"X:\L\noc\a.fits", "mtime": "2026-07-15T10:00:05.250000+00:00",
                              "db_mtime": "2026-07-15T10:00:00.750000+00:00"}, {"path": "a.fits"},
     {"pl": ": a.fits", "en": ": a.fits"}),
    ("intent_sha1_differs", {"path": r"X:\L\noc\a.fits"}, {"path": "a.fits"}, {"pl": ": a.fits", "en": ": a.fits"}),
    ("intent_target_taken", {"inner": _powod("target_taken_db", location=7, volume="V", path=r"X:\L\noc\nowa.fits"),
                             "location": 3, "path": r"X:\L\noc\stara.fits"},
     {"inner": _powod("target_taken_db", location=7, volume="V", path="nowa.fits"), "location": 3,
      "path": "stara.fits"}, _NA_KONCU_CELU),
    ("intent_target_taken", {"inner": "location:3 nie istnieje", "location": 3, "path": r"X:\L\noc\stara.fits"},
     {"inner": "location:3 nie istnieje", "location": 3, "path": "stara.fits"}, _NA_KONCU_CELU),
])
def test_czlon_odmowy_kazdego_kodu_drogi_czlowieka(qapp, kod, parametry, krotkie, koniec, lang):
    """`FramesView._czlon_odmowy` bez okna, KAŻDY kod drogi człowieka, PL i EN: całe zwięzłe zdanie - krótki powód
    z nazwami plików, droga człowieka WŁAŚCIWA kodowi (wyrocznia literałem), nazwa na końcu (literał; cel zajęty: nazwa
    lokacji z historią renamu w relacji „pod”), czasy lokalne do sekundy, powód zagnieżdżony (`target_taken_db` albo
    proza rdzenia) w języku UI przez `tekst_powodu`; pełny powód do szczegółu. EN bez polskich znaków. Falsyfikatory:
    zła droga kodu w mapie; nazwa w środku zdania; powód zagnieżdżony surowo (polskie zdanie w EN)."""
    from horreum.gui import grid as grid_mod
    from horreum.gui.wb_worker import sciezki_skrocone, tekst_powodu
    i18n.set_lang(lang)
    try:
        receive, nav = i18n.t("pipeline.receive"), i18n.t("nav.dostawa")
        powod = _powod(kod, **parametry)
        tekst, pelny = grid_mod.FramesView._czlon_odmowy(kod, powod, sciezki_skrocone(powod), receive, nav)
        oczek = {n: tekst_powodu(x) if n == "inner" else x for n, x in krotkie.items()}
        if "mtime" in parametry:
            oczek["mtime"], oczek["db_mtime"] = _lokalne(parametry["mtime"], parametry["db_mtime"])
        assert tekst == i18n.t(f"grid.drawer.refused.{kod}", **oczek,
                               way=i18n.t(_DROGA_KODU[kod], receive=receive, nav=nav)), tekst
        assert tekst.endswith(koniec[lang]) and pelny is True, tekst
        if lang == "en":
            assert not set(tekst) & _POLSKIE, tekst
    finally:
        i18n.set_lang("pl")


def test_czlon_odmowy_kod_bez_klucza_i_przejsciowy(qapp, monkeypatch):
    """`FramesView._czlon_odmowy` bez okna: kod drogi człowieka bez zwięzłego klucza - forma pełna z drogą i pełnym
    powodem w szczególe (ścieżka skrócona); kod przejściowy - forma pełna bez drogi i bez szczegółu, gdy nic nie
    skrócono. Falsyfikatory: kod przejściowy przez mapę dróg; forma pełna bez drogi."""
    from horreum.gui import grid as grid_mod
    from horreum.gui.i18n_catalog import CATALOG
    from horreum.gui.wb_worker import sciezki_skrocone, tekst_powodu
    czlon = grid_mod.FramesView._czlon_odmowy
    receive, nav = i18n.t("pipeline.receive"), i18n.t("nav.dostawa")
    monkeypatch.delitem(CATALOG, "grid.drawer.refused.intent_sha1_differs")
    sha = _powod("intent_sha1_differs", path=r"X:\L\a.fits")
    assert czlon("intent_sha1_differs", sha, sciezki_skrocone(sha), receive, nav) == (
        i18n.t("grid.drawer.names_held_refused", reason=tekst_powodu(_powod("intent_sha1_differs", path="a.fits")))
        + i18n.t("grid.drawer.names_way_check"), True)
    cisza = _powod("disk_silent", detail="cisza")
    assert czlon("disk_silent", cisza, sciezki_skrocone(cisza), receive, nav) == (
        i18n.t("grid.drawer.names_held_refused", reason=tekst_powodu(cisza)), False)
