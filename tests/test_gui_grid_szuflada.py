"""Szuflada Zbiorów: poczekalnia z poprzedniej sesji (AR-280), przyczyny pominięć stagingu (AR-274),
identyfikator commitu i przebiegu przy żywym „Cofnij” (AR-276), belki grup po przewinięciu w poziomie
(AR-275), numer operacji w szczególe gestów izolacji (szew AR-281). Kliki prawdziwe (`QTest.mouseClick`
na widżecie), wątek zapisu prawdziwy tam, gdzie gest go ma, czekanie pętlą zdarzeń."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from horreum import db, repo, writeback
from horreum.gui import grid as grid_mod, i18n, queries

NOW = "2026-07-03T14:00:00"
_POL = {"source": "date_obs", "offset_hours": 0, "fallback": True}


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _baza_szuflady(tmp_path, n, nazwa="sz"):
    """Baza w pliku nad `n` prawdziwymi FITS (różne dane i czasy - różne klatki i nazwy z `DATE-OBS`)."""
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    path = tmp_path / f"{nazwa}.db"
    con = db.open_db(str(path))
    pliki = []
    for i in range(n):
        p = tmp_path / f"{nazwa}{i}.fits"
        hdu = fits.PrimaryHDU(data=np.full((4, 4), i + 1, dtype=np.int16))
        for k, v in (("IMAGETYP", "Light"), ("OBJECT", "NGC7000"), ("TELESCOP", "RC8"), ("FILTER", "Ha"),
                     ("DATE-OBS", f"2024-03-{15 + i:02d}T21:30:45"), ("EXPTIME", 300.0)):
            hdu.header[k] = v
        hdu.writeto(str(p), overwrite=True)
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary(),
                           pochodzenie=repo.ZEWNETRZNE)
        pliki.append(p)
    return str(path), con, pliki


def _widok_szuflady(con, *, inline=False):
    v = grid_mod.FramesView(con, now_fn=lambda: NOW)
    if inline:
        v._writeback_async = False
    v.resize(1400, 800)
    v.show()
    QApplication.processEvents()
    return v


def _klik_w(przycisk):
    from PySide6.QtTest import QTest
    QTest.mouseClick(przycisk, Qt.LeftButton)
    QApplication.processEvents()


def _makro_przyciskiem(v, kw, wartosc, *, przycisk="stage", comp=None):
    """Panel makra i „Do stagingu” (albo „Podgląd”) prawdziwym klikiem."""
    if not v.macro_bar.isVisible():
        _klik_w(v.sel_bar.btn_macro)
    b = v.macro_bar
    b.asg_kw.setCurrentText(kw)
    b.asg_op.setCurrentIndex(0)
    b.asg_expr.setText(wartosc)
    b.comp_name.setText("a" if comp else "")
    b.comp_expr.setText(comp or "")
    _klik_w(b.btn_stage if przycisk == "stage" else b.btn_prev)


def _zamknij_widok(v):
    from test_gui_pasek_szczegol import _czekaj
    _czekaj(lambda: not v._wb.is_busy, "wątek zapisu przed zamknięciem")
    v.zatrzymaj_pola()
    v.close()


def _przerwany_zapis(v, monkeypatch):
    """„Zatwierdź” klikiem i „Anuluj” po pierwszym pliku (prawdziwy wątek zapisu, brama testu AR-220). Brama
    zostaje podpięta do końca testu - zwolniona, więc kolejne zapisy przechodzą przez nią bez czekania."""
    from test_gui_pasek_szczegol import _anuluj_w_biegu, _brama_po_pierwszym_pliku
    stary = v.model._preview
    brama, doszlo = _brama_po_pierwszym_pliku(monkeypatch)
    _klik_w(v.drawer.btn_commit)
    _anuluj_w_biegu(v, brama, doszlo, stary)


def _wpis_drogi_atomowej(con, run_id):
    """Wpis `applied` przerwanego zapisu jako wpis drogi atomowej (spadek z zapisu w miejscu) - bez wiązania
    z operacją (`inplace_op_id`), czyli taki, który `clear_pending_for_run` kasował."""
    with con:
        con.execute("UPDATE pending_changes SET inplace_op_id = NULL WHERE run_id = ? AND status = 'applied'",
                    (run_id,))


def _restart(path):
    """Program otwarty na nowo na tej samej bazie: nowe połączenie, nowy widok."""
    from test_gui_pasek_szczegol import _czekaj
    con = db.connect(path)
    v = _widok_szuflady(con)
    _czekaj(lambda: not v._zbior_w_drodze(), "pierwszy zbiór")
    return con, v


def _obcy():
    """Zdanie cudzej blokady szuflady: w teście drugie okno żyje w TYM procesie, więc plik blokady niesie
    PID testu."""
    return i18n.t("grid.drawer.foreign_owner", pid=os.getpid())


# ============================================================ AR-280 - poczekalnia z poprzedniej sesji


def test_szuflada_podejmuje_przerwany_zapis_po_restarcie(qapp, tmp_path, monkeypatch):
    """Staging trzech kart, „Zatwierdź”, „Anuluj” po pierwszym pliku, zamknięcie widoku i nowy widok na tej
    samej bazie (nowe połączenie). Szuflada mówi „Z poprzedniej sesji czekają 2 zmiany” i że zapis przerwano,
    kolumna podglądu pokazuje dwa czekające wpisy, a „Zatwierdź” kończy zapis. Falsyfikator: widok bez
    `_podejmij_przebieg_poprzedni` (szuflada „pusta”, `run_id` None - jak przed zmianą)."""
    from astropy.io import fits
    from test_gui_pasek_szczegol import _czekaj
    path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    _makro_przyciskiem(v, "TELESCOP", "EQ6")
    _przerwany_zapis(v, monkeypatch)
    run_id = v._run_id
    assert v._pending_count() == 2
    _zamknij_widok(v)
    con.close()
    con, v = _restart(path)
    try:
        assert v._run_id == run_id and v._pending_count() == 2
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", 2)
        assert v.drawer.result.text() == i18n.t("grid.drawer.prev_interrupted",
                                                commit=i18n.t("grid.action.commit"))
        czekajace = {w["frame_id"] for w in queries.pending_cards_for_run(con, run_id)}
        assert len(czekajace) == 2 and set(v.model._preview) == czekajace
        assert not v.table.isColumnHidden(v.model._preview_col())
        assert v.drawer.btn_commit.isVisible() and v.drawer.btn_commit.isEnabled()
        _klik_w(v.drawer.btn_commit)
        _czekaj(lambda: not v._wb.is_busy and not v._zbior_w_drodze(), "dokończenie zapisu")
        assert [fits.getheader(str(p))["TELESCOP"] for p in pliki] == ["EQ6"] * 3
        # „Cofnij” cofa CAŁY przebieg, także commit sprzed restartu (AR-345) - etykieta liczy jego pliki.
        assert v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=3)
    finally:
        _zamknij_widok(v)
        con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_szuflada_podejmuje_staging_porzucony_bez_zapisu(qapp, tmp_path, lang):
    """Staging bez „Zatwierdź” i zamknięcie - po ponownym otwarciu szuflada mówi „Z poprzedniej sesji czekają
    3 zmiany” bez zdania o przerwanym zapisie (zapis nie ruszył). Falsyfikator: zdanie przerwania przy każdym
    przebiegu podjętym (predykat `przerwany` zawsze prawdziwy)."""
    i18n.set_lang(lang)
    path, con, _p = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    _makro_przyciskiem(v, "TELESCOP", "EQ6")
    assert v._pending_count() == 3
    _zamknij_widok(v)
    con.close()
    con, v = _restart(path)
    try:
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", 3)
        assert v.drawer.result.text() == ""
    finally:
        _zamknij_widok(v)
        con.close()


def test_podjecie_pomija_przebiegi_cudze_i_w_biegu(qapp, tmp_path):
    """Szuflada podejmuje wyłącznie przebieg bez właściciela - nie przebieg zmiany obiektu (`object_change_run`),
    nie wpis związany z operacją zapisu w miejscu (`inplace_op_id`) i nie przebieg nazw z wierszem w locie
    (`in_flight` - inny proces właśnie go pisze). Wszystkie trzy są NOWSZE niż zwykły przebieg `R`, więc
    podjęty musi być `R`; zdanie nie liczy ich jako starszych przebiegów, ale mówi o dwóch zmianach nazw
    zatrzymanych zapisem nazw (AR-316). Falsyfikatory: predykat bez któregokolwiek z trzech wykluczeń;
    zdanie przebiegu bez członu nazw w locie."""
    from horreum import repo
    path, con, pliki = _baza_szuflady(tmp_path, 3)
    lok = [(r["id"], r["header_hash"], r["path"])
           for r in con.execute("SELECT id, header_hash, path FROM location ORDER BY id")]

    def _karta(run_id, lid, hh):
        repo.stage_pending(con, run_id=run_id, location_id=lid, keyword="TELESCOP", idx=0, op="set",
                           old_value="RC8", new_value="EQ6", new_type="str", new_comment=None,
                           expected_header_hash=hh)
    _karta("R", lok[0][0], lok[0][1])
    with con:
        con.execute("INSERT INTO object_change_run (run_id, mode, created_at) VALUES ('OC', 'align', ?)", (NOW,))
    _karta("OC", lok[1][0], lok[1][1])
    _karta("IP", lok[2][0], lok[2][1])
    con.execute("PRAGMA foreign_keys = OFF")     # atrapa operacji: liczy się tylko wiązanie wpisu
    with con:
        con.execute("UPDATE pending_changes SET inplace_op_id = 999 WHERE run_id = 'IP'")
    con.execute("PRAGMA foreign_keys = ON")
    for lid, _hh, p in lok[:2]:
        repo.stage_rename(con, run_id="NF", location_id=lid, old_path=p, new_path=p + ".x",
                          expected_mtime=None)
    with con:
        con.execute("UPDATE pending_renames SET in_flight = 'commit' "
                    "WHERE id = (SELECT min(id) FROM pending_renames WHERE run_id = 'NF')")
    assert [p["run_id"] for p in queries.oczekujace_przebiegi_szuflady(con)] == ["R"]
    v = _widok_szuflady(con, inline=True)
    try:
        assert v._run_id == "R" and v._rename_run_id is None
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", 1)
        assert v.drawer.result.text() == i18n.t_plural("grid.drawer.names_held_more", 2)
    finally:
        _zamknij_widok(v)
        con.close()


def test_szuflada_podejmuje_przerwana_zmiane_nazw(qapp, tmp_path, monkeypatch):
    """Klinga nazw: zmiana trzech nazw przerwana po pierwszym pliku, restart - „Z poprzedniej sesji czekają
    2 zmiany nazw”, podgląd „nazwa →” dwóch nazw, „Zatwierdź” kończy, a „Cofnij” przywraca WSZYSTKIE trzy nazwy
    (wpis `applied` przerwanego zapisu przeżył). Falsyfikator: podjęcie samych kart."""
    from test_gui_pasek_szczegol import _anuluj_w_biegu, _brama_po_pierwszym_pliku, _czekaj
    path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    v._on_rename_stage(_POL)
    stary = v.model._preview
    brama, doszlo = _brama_po_pierwszym_pliku(monkeypatch)
    _klik_w(v.drawer.btn_commit)
    _anuluj_w_biegu(v, brama, doszlo, stary)
    assert v._rename_pending_count() == 2
    _zamknij_widok(v)
    con.close()
    con, v = _restart(path)
    try:
        assert v._rename_pending_count() == 2 and v._run_id is None
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_rename_prev", 2)
        assert len(v.model._preview) == 2 and v.model._preview_label == i18n.t("grid.preview.name")
        _klik_w(v.drawer.btn_commit)
        _czekaj(lambda: not v._wb.is_busy and not v._zbior_w_drodze(), "dokończenie nazw")
        assert not any(p.exists() for p in pliki)
        _klik_w(v._undo_btn)
        _czekaj(lambda: not v._wb.is_busy and not v._zbior_w_drodze(), "cofnięcie nazw")
        assert all(p.exists() for p in pliki), "nazwa z przerwanego zapisu nie wróciła"
    finally:
        _zamknij_widok(v)
        con.close()


def test_odrzuc_przebieg_z_poprzedniej_sesji_zostawia_rozstrzygniete_i_wpis_w_dzienniku(qapp, tmp_path,
                                                                                      monkeypatch):
    """„Odrzuć” klikiem na przebiegu podjętym po restarcie zdejmuje dwa czekające wpisy, a wpis zapisu
    przerwanego (`applied`, droga atomowa) zostaje; dziennik dostaje JEDNO `staging.discarded` z liczbą.
    Szuflada: pusta, „Odrzucono 2 zmiany”. Falsyfikatory: czyszczenie wszystkich wpisów przebiegu (wpis
    `applied` znika), odrzucenie bez zdarzenia."""
    path, con, _p = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    _makro_przyciskiem(v, "TELESCOP", "EQ6")
    _przerwany_zapis(v, monkeypatch)
    run_id = v._run_id
    _wpis_drogi_atomowej(con, run_id)
    _zamknij_widok(v)
    con.close()
    con, v = _restart(path)
    try:
        _klik_w(v.drawer.btn_reject)
        statusy = [r["status"] for r in con.execute(
            "SELECT status FROM pending_changes WHERE run_id = ? ORDER BY id", (run_id,))]
        assert statusy == ["applied"], statusy
        zdarzenia = [(r["verb"], r["target"], json.loads(r["payload"])) for r in con.execute(
            "SELECT verb, target, payload FROM event WHERE verb = 'staging.discarded'")]
        assert zdarzenia == [("staging.discarded", f"run:{run_id}", {"n": 2, "klinga": "karty"})]
        # Plik zapisany przed restartem dostaje „Cofnij” przebiegu (AR-345) - dawniej pustostan i droga przez CLI.
        [cid] = [r[0] for r in con.execute("SELECT id FROM commits WHERE run_id = ?", (run_id,))]
        assert v._run_id is None and v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=1)
        assert v.drawer.result.text() == (i18n.t_plural("grid.wb.rejected", 2)
                                          + i18n.t_plural("grid.wb.written_before", 1)
                                          + i18n.t("grid.wb.commit_id", id=cid))
        assert v._undo_btn.isVisible() and v._undo_commity == (cid,)
    finally:
        _zamknij_widok(v)
        con.close()


def test_odrzuc_w_tej_samej_sesji_po_przerwaniu_zostawia_rozstrzygniete_bez_zdarzenia(qapp, tmp_path,
                                                                                   monkeypatch):
    """Wpisy rozstrzygnięte, klinga kart: „Odrzuć” po zapisie przerwanym w TEJ sesji zdejmuje czekające, wpis
    `applied` drogi atomowej zostaje (na wpisach `failed` tej drogi stoi potwierdzenie skanem), a staging tej
    sesji schodzi bez zdarzenia (transient). Falsyfikator: czyszczenie wszystkich wpisów przebiegu."""
    path, con, _p = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _przerwany_zapis(v, monkeypatch)
        run_id = v._run_id
        _wpis_drogi_atomowej(con, run_id)
        _klik_w(v.drawer.btn_reject)
        assert [r["status"] for r in con.execute(
            "SELECT status FROM pending_changes WHERE run_id = ?", (run_id,))] == ["applied"]
        assert con.execute("SELECT count(*) FROM event WHERE verb = 'staging.discarded'").fetchone()[0] == 0
    finally:
        _zamknij_widok(v)
        con.close()


def test_ponowny_staging_nazw_po_przerwaniu_zostawia_wpis_cofniecia(qapp, tmp_path, monkeypatch):
    """Wpisy rozstrzygnięte, klinga nazw: zmiana nazw przerwana po pierwszym pliku, ponowny staging nazw w tej
    samej sesji, „Zatwierdź”, „Cofnij” - wracają WSZYSTKIE trzy nazwy. Ponowny staging kasował wiersz `applied`
    przerwanego zapisu (`clear_renames_for_run`), a cofnięcie przebiegu czyta właśnie `applied` - pierwszy plik
    zostawał pod nową nazwą. Falsyfikator: `clear_renames_for_run` w stagingu."""
    from test_gui_pasek_szczegol import _anuluj_w_biegu, _brama_po_pierwszym_pliku, _czekaj
    path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    try:
        v._on_rename_stage(_POL)
        stary = v.model._preview
        brama, doszlo = _brama_po_pierwszym_pliku(monkeypatch)
        _klik_w(v.drawer.btn_commit)
        _anuluj_w_biegu(v, brama, doszlo, stary)
        v._on_rename_stage(_POL)
        assert v._rename_pending_count() == 2
        _klik_w(v.drawer.btn_commit)
        _czekaj(lambda: not v._wb.is_busy and not v._zbior_w_drodze(), "zapis nazw")
        assert not any(p.exists() for p in pliki)
        _klik_w(v._undo_btn)
        _czekaj(lambda: not v._wb.is_busy and not v._zbior_w_drodze(), "cofnięcie nazw")
        assert all(p.exists() for p in pliki), "plik z przerwanego zapisu nie wrócił do nazwy"
    finally:
        _zamknij_widok(v)
        con.close()


def test_makro_nie_zastepuje_po_cichu_zmian_z_poprzedniej_sesji(qapp, tmp_path):
    """Na przebiegu podjętym „Do stagingu” makra odmawia zdaniem „z poprzedniej sesji” - wpisy czekające
    nietknięte. Falsyfikator: podjęcie bez `_komorki` (ponowny staging zastępuje je po cichu)."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con)
    _makro_przyciskiem(v, "TELESCOP", "EQ6")
    _zamknij_widok(v)
    con.close()
    con, v = _restart(path)
    try:
        zdania = []
        v.status_message.connect(zdania.append)
        przed = [tuple(r) for r in con.execute("SELECT id, new_value FROM pending_changes ORDER BY id")]
        _makro_przyciskiem(v, "TELESCOP", "AZ-GTI")
        assert zdania[-1] == i18n.t_plural("grid.drawer.prev_macro_blocked", 2)
        assert [tuple(r) for r in con.execute("SELECT id, new_value FROM pending_changes ORDER BY id")] == przed
    finally:
        _zamknij_widok(v)
        con.close()


def test_klucze_szuflady_z_poprzedniej_sesji_odmieniaja_liczbe():
    """Wpisy mnogie AR-280 w PL dla 1, 2, 5, 12, 22 i w EN dla 1 i 2."""
    pl = {n: i18n.t_plural("grid.drawer.pending_prev", n) for n in (1, 2, 5, 12, 22)}
    assert pl == {1: "Z poprzedniej sesji czeka 1 zmiana", 2: "Z poprzedniej sesji czekają 2 zmiany",
                  5: "Z poprzedniej sesji czeka 5 zmian", 12: "Z poprzedniej sesji czeka 12 zmian",
                  22: "Z poprzedniej sesji czekają 22 zmiany"}
    assert i18n.t_plural("grid.drawer.prev_older", 22).startswith("Czekają jeszcze 22 starsze przebiegi")
    assert i18n.t_plural("grid.drawer.prev_macro_blocked", 12).startswith("Makro: w szufladzie czeka 12 zmian")
    i18n.set_lang("en")
    assert i18n.t_plural("grid.drawer.pending_rename_prev", 1) == "1 name change waiting from the previous session"
    assert i18n.t_plural("grid.drawer.pending_rename_prev", 2) == "2 name changes waiting from the previous session"


def test_zamkniecie_okna_w_biegu_zapisu_szuflady_odmawia_i_anuluje(qapp, tmp_path, monkeypatch):
    """Zamknięcie okna gospodarza W BIEGU zapisu szuflady - okno zostaje, połączenie żyje, bieg dostaje
    anulowanie po bieżącym pliku, a drugie zamknięcie po biegu zamyka. Zmierzone przed zmianą: okno znikało,
    połączenie zamykało się pod wątkiem, a ogon zapisu padał na zamkniętej bazie. Falsyfikator: `closeEvent`
    bez straży `refuse_close`."""
    import threading
    from horreum.gui.app import MainWindow
    from horreum.gui.wb_worker import WritebackWorker
    from test_gui_pasek_szczegol import _czekaj
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    path, con, _p = _baza_szuflady(tmp_path, 3)
    con.close()
    win = MainWindow(path)
    win.show()
    g = win.grid_view
    brama, doszlo = threading.Event(), threading.Event()
    try:
        _czekaj(lambda: not g._zbior_w_drodze(), "pierwszy zbiór")
        g.macro_bar.asg_kw.setCurrentText("TELESCOP")
        g.macro_bar.asg_op.setCurrentIndex(0)
        g.macro_bar.asg_expr.setText("EQ6")
        g.macro_bar._emit_stage()
        prawdziwy = WritebackWorker._emit_progress

        def _postep(self, done, total, p, status):
            prawdziwy(self, done, total, p, status)
            if done == 1:
                doszlo.set()
                brama.wait(30)
        monkeypatch.setattr(WritebackWorker, "_emit_progress", _postep)
        _klik_w(g.drawer.btn_commit)
        _czekaj(lambda: doszlo.is_set(), "pierwszy plik")
        assert win.close() is False
        assert win.isVisible() and win.con is not None
        brama.set()
        _czekaj(lambda: not g._wb.is_busy, "koniec biegu")
        assert g._pending_count() == 2, "anulowanie po bieżącym pliku"
    finally:
        brama.set()
        assert win.close() is True
        assert win.con is None


def test_zamkniecie_okna_bez_bazy_bez_wyjatku(qapp):
    """Straż zamknięcia (AR-280) nie zakłada widoku Zbiorów: okno bez bazy zamyka się bez wyjątku."""
    from horreum.gui.app import MainWindow
    win = MainWindow(None)
    win.show()
    assert win.close() is True


# ============================================================ AR-274 - przyczyny pominięć stagingu


def _cztery_pliki_z_kopia(tmp_path):
    """Cztery FITS; pierwsza klatka dostaje drugą obecną kopię (syntetyczna lokacja) - makro ją pominie innym
    powodem niż typ."""
    path, con, pliki = _baza_szuflady(tmp_path, 4, nazwa="p")
    with con:
        con.execute("INSERT INTO location (frame_id, volume, path, present) "
                    "SELECT min(frame_id), 'V', 'X:/L/kopia.fits', 1 FROM location")
    return path, con, pliki


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_staging_samych_pominiec_mowi_przyczyny_i_zdejmuje_stary_wynik(qapp, tmp_path, lang):
    """Zapis i „Cofnij” klikiem (w szufladzie zostaje wynik cofnięcia), potem `EXPTIME = abc` „Do stagingu”:
    pasek i szuflada mówią „0 zmian, 4 pominięto - 3: <typ>; 1: <kopie>”, wynik cofnięcia znika, Zatwierdź/Odrzuć
    widoczne (wygaszone). Falsyfikatory: rozbicie pominięć puste (przyczyna tylko w podpowiedziach komórek),
    wynik stagingu niewpisany do szuflady (stary wynik zostaje)."""
    from horreum.gui.grid_model import zdanie_pominiec_makra
    i18n.set_lang(lang)
    _path, con, _p = _cztery_pliki_z_kopia(tmp_path)
    v = _widok_szuflady(con, inline=True)
    try:
        zdania = []
        v.status_message.connect(zdania.append)
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _klik_w(v.drawer.btn_commit)
        _klik_w(v._undo_btn)
        po_cofnieciu = v.drawer.result.text()
        assert po_cofnieciu
        _makro_przyciskiem(v, "EXPTIME", "abc")
        pominiete = [p["skipped"] for p in v.model._preview.values()]
        assert len(pominiete) == 4
        oczek = i18n.t_plural("grid.macro.staged", 0, s=4) + zdanie_pominiec_makra(
            [type("S", (), {"reason": p})() for p in pominiete])
        assert zdania[-1] == oczek and v.drawer.result.text() == oczek
        assert oczek.count(" · ") == 1 and oczek.index(" 3: ") < oczek.index(" · 1: ")
        assert po_cofnieciu not in v.drawer.result.text()
        assert v.drawer.label.text() == i18n.t("grid.drawer.empty")
        assert v.drawer.btn_commit.isVisible() and not v.drawer.btn_commit.isEnabled()
    finally:
        _zamknij_widok(v)
        con.close()


def test_staging_samych_pominiec_przy_zywym_cofnij_zostawia_cofnij(qapp, tmp_path):
    """Zapis (żywe „Cofnij”), potem staging samych pominięć - „Cofnij” i etykieta „Zatwierdzono” zostają
    (reguła „Popraw f/”: „Cofnij” znika, gdy do szuflady COŚ wchodzi), a przyczyny stoją w wierszu szuflady
    obok niego z numerem commitu raz - jak bez „Cofnij” (AR-309). Falsyfikatory: `_dismiss_undo` przed
    makrem (szuflada bez akcji i bez numeru commitu); wynik szuflady bez zdania stagingu (przyczyny tylko na
    pasku, stary wynik w szufladzie)."""
    _path, con, _p = _cztery_pliki_z_kopia(tmp_path)
    v = _widok_szuflady(con, inline=True)
    try:
        zdania = []
        v.status_message.connect(zdania.append)
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _klik_w(v.drawer.btn_commit)
        [cid] = v._undo_commity
        etykieta = v.drawer.label.text()
        _makro_przyciskiem(v, "EXPTIME", "abc")
        assert v._undo_mode == "macro" and v._undo_btn.isVisible()
        assert v.drawer.label.text() == etykieta
        assert v.drawer.result.text() == zdania[-1] + i18n.t("grid.wb.commit_id", id=cid)
        assert (etykieta + " " + v.drawer.result.text()).count(f"commit {cid})") == 1
        assert " 3: " in zdania[-1] and " · 1: " in zdania[-1]
        assert v.drawer.btn_commit.isHidden() and v.drawer.btn_reject.isHidden()
    finally:
        _zamknij_widok(v)
        con.close()


def test_zdanie_pominiec_makra_malejaco_i_puste_bez_pominiec():
    """Czysta funkcja: przyczyny malejąco po liczbie, remis alfabetycznie, pusty łańcuch bez pominięć; powód
    z kodem w języku UI (EN)."""
    from horreum.gui.grid_model import zdanie_pominiec_makra
    from horreum.item_reasons import PowodPozycji

    class S:
        def __init__(self, reason):
            self.reason = reason
    raw = PowodPozycji("plik RAW (DSLR) -- Horreum go NIE zapisuje (read-only)", "macro_raw")
    assert zdanie_pominiec_makra([]) == ""
    zd = zdanie_pominiec_makra([S("b"), S(raw), S("a"), S(raw)])
    assert zd.startswith(" - 2: ") and zd.endswith(" · 1: a · 1: b"), zd
    i18n.set_lang("en")
    assert i18n.t("objchg.item.macro_raw") in zdanie_pominiec_makra([S(raw)])


def test_zdanie_pominiec_makra_trzy_przyczyny_i_reszta_jednym_czlonem():
    """Powód z parametrem per klatka (tu 50 różnych przyczyn, jedna z nich na 3 klatkach) - zdanie niesie trzy
    najliczniejsze przyczyny i człon „i jeszcze 47 przyczyn (47 klatek)”, nie listę pięćdziesięciu; przyczyna
    z uwagą po średniku zostaje JEDNYM członem (separator „ · ”). Falsyfikatory: zdanie bez sufitu (50 członów),
    separator „; ” (człon z uwagą liczy się jak dwa)."""
    from horreum.gui.grid_model import zdanie_pominiec_makra

    class S:
        def __init__(self, reason):
            self.reason = reason
    przyczyny = [S("p00; uwaga")] * 3 + [S(f"p{i:02d}") for i in range(1, 50)]
    zd = zdanie_pominiec_makra(przyczyny)
    assert zd == (" - 3: p00; uwaga · 1: p01 · 1: p02 · "
                  + i18n.t_plural("grid.drawer.skipped_more", 47,
                                  frames=i18n.t_plural("grid.drawer.skipped_frames", 47))), zd
    assert zd.count(" · ") == 3 and len(zd) < 120
    assert i18n.t_plural("grid.drawer.skipped_more", 22, frames=i18n.t_plural("grid.drawer.skipped_frames", 5)) == (
        "i jeszcze 22 przyczyny (5 klatek)")
    i18n.set_lang("en")
    assert i18n.t_plural("grid.drawer.skipped_more", 1, frames=i18n.t_plural("grid.drawer.skipped_frames", 1)) == (
        "and 1 more cause (1 frame)")


# ============================================================ AR-276 - identyfikator przy żywym „Cofnij”


def _wiersz_szuflady(v):
    return v.drawer.label.text() + " | " + v.drawer.result.text()


@pytest.mark.parametrize("galaz", ["podglad_blad", "przywroc_naglowek", "blad_nazw", "cofniecie_nazw_niedomkniete"])
def test_wiersz_szuflady_przy_zywym_cofnij_niesie_identyfikator_raz(qapp, tmp_path, monkeypatch, galaz):
    """Zdanie, które przy żywym „Cofnij” zastępuje wynik zapisu - błąd definicji makra w „Podglądzie”, ogon
    gestu izolacji („Przywróć nagłówek sprzed zapisu”), błąd operacji nazw, cofnięcie nazw niedomknięte - niesie
    identyfikator commitu albo przebiegu nazw dokładnie raz, a etykieta „Zatwierdzono/Przemianowano” zostaje.
    Falsyfikatory: `_zdanie_przy_cofnij` bez ogona (zero), ogon zostawiony w `_after_commit` albo
    `_after_commit_rename` (dwa)."""
    from horreum.gui.wb_worker import WritebackWorker
    if galaz == "przywroc_naglowek":
        from horreum import repo
        from test_gui_izolacja_zapisu import _baza, _fazy, _widok, _zaznacz
        con, [(_p, fid)] = _baza(tmp_path)
        v = _widok(con)
        try:
            v.refresh()
            v._on_commit()
            ident = f"commit {v._undo_commity[0]})"
            assert _wiersz_szuflady(v).count(ident) == 1
            loc = con.execute("SELECT id, header_hash FROM location WHERE frame_id = ?", (fid,)).fetchone()
            repo.stage_pending(con, run_id="R2", location_id=loc["id"], keyword="OBJECT", idx=0, op="set",
                               old_value="NGC 6992", new_value="NGC 6995", new_type="str", new_comment=None,
                               expected_header_hash=loc["header_hash"])
            prawdziwy = os.fsync

            def _fsync(fd):
                prawdziwy(fd)
                raise OSError(64, "The specified network name is no longer available")
            with monkeypatch.context() as m:
                m.setattr(writeback.os, "fsync", _fsync)
                writeback.commit(con, "R2", now=NOW, inplace=True)
            assert _fazy(con) == ["synced", "unverified"]
            v.apply_perspective(grid_mod.PRESET_TORN_WRITE)
            _zaznacz(v, [fid])
            v._on_restore_header()
            assert v._undo_mode == "macro" and _wiersz_szuflady(v).count(ident) == 1, _wiersz_szuflady(v)
            assert v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=1)
        finally:
            v.close()
            con.close()
        return
    _path, con, _pl = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con, inline=True)
    try:
        if galaz == "podglad_blad":
            _makro_przyciskiem(v, "TELESCOP", "EQ6")
            _klik_w(v.drawer.btn_commit)
            ident, etykieta = f"commit {v._undo_commity[0]})", i18n.t("grid.wb.committed_label", n=2)
            _makro_przyciskiem(v, "TELESCOP", "EQ6", przycisk="prev", comp="1 +")
        else:
            v._on_rename_stage(_POL)
            _klik_w(v.drawer.btn_commit)
            ident = f"run {v._undo_rename_run_id})"
            etykieta = i18n.t("grid.rename.renamed_label", n=2)
            assert _wiersz_szuflady(v).count(ident) == 1
            if galaz == "blad_nazw":
                def _pada(*_a):
                    raise ValueError("złamany inwariant cofnięcia nazw")
                monkeypatch.setitem(WritebackWorker._OPS, "undo_rename", _pada)
            else:
                monkeypatch.setitem(WritebackWorker._OPS, "undo_rename", lambda c, t, now, pr, sc: (
                    writeback.undo_renames(c, t, now=now, progress=pr, should_cancel=lambda: True)))
            _klik_w(v._undo_btn)
        assert v._undo_mode is not None and v._undo_btn.isVisible()
        assert v.drawer.label.text() == etykieta
        assert _wiersz_szuflady(v).count(ident) == 1, _wiersz_szuflady(v)
    finally:
        _zamknij_widok(v)
        con.close()


def test_szczegol_gestow_izolacji_i_kopii_wiodacej_niesie_numer_operacji():
    """Szew AR-281: zdanie gestu izolacji („Przywróć nagłówek…”, „Dokończ zapis”, „Zwolnij…”) i gestu „Ta kopia
    prowadzi” mówi gest z menu, a numer operacji zapisu w miejscu z wywołaniem rdzenia stoi w szczególe pod
    kursorem (`wb_worker.wiersz_operacji`) - obok szczegółu systemu, nie zamiast. Falsyfikator: szczegół
    z samego `wiersz_systemu` (numer operacji znika z widoku)."""
    from horreum.gui.grid_model import _podpowiedz_gestu_zapisu, _zdanie_kopii_wiodacej
    from horreum.gui.wb_worker import InplaceGestureResult
    from horreum.lead_copy import LeadCopyResult
    izolowana = writeback._powod_izolacji({"id": 7, "kind": "commit", "phase": "writing"})
    res = InplaceGestureResult([writeback.FileResult(1, r"X:\L\a.fits", "blocked", izolowana)])
    assert _podpowiedz_gestu_zapisu("finish_inplace", res) == (
        "Operacja zapisu w miejscu 7: writeback.recover_torn(7)")
    _zdanie, szczegol = _zdanie_kopii_wiodacej(LeadCopyResult("isolated", 1, r"X:\L\a.fits", izolowana))
    assert szczegol == "Operacja zapisu w miejscu 7: writeback.recover_torn(7)"
    assert _zdanie_kopii_wiodacej(LeadCopyResult("adopted", 1, r"X:\L\a.fits"))[1] == ""


# ============================================================ AR-275 - belki grup po przewinięciu w poziomie


def _widok_z_belkami(tmp_path):
    from test_gui_pasek_szczegol import _czekaj
    _path, con, _p = _baza_szuflady(tmp_path, 3, nazwa="b")
    v = _widok_szuflady(con, inline=True)
    v.combo_group.setCurrentIndex(v.combo_group.findData("kind"))
    # Kolumna 0 szersza niż kadr (minimum okna Zbiorów nie da go zwęzić) - jest co przewinąć.
    v.table.setColumnWidth(0, 2 * v.table.viewport().width())
    _czekaj(lambda: v.table.horizontalScrollBar().maximum() > 0, "tabela szersza niż kadr")
    return con, v


def test_delegat_belki_tylko_na_wierszach_belek(qapp, tmp_path):
    """Wiersz belki maluje `_DelegatBelki` (delegat wiersza), wiersz klatki - nie; po zdjęciu grupowania żaden
    wiersz nie ma delegata belki, a po ponownym grupowaniu wyłącznie wiersze belek. Falsyfikator:
    `_uloz_belki_i_wersje` bez zdjęcia delegatów poprzedniego układu."""
    from horreum.gui.grid_model import _DelegatBelki
    con, v = _widok_z_belkami(tmp_path)
    try:
        t, m = v.table, v.model

        def _wiersze_z_belka():
            return [i for i in range(m.rowCount())
                    if isinstance(t.itemDelegateForIndex(m.index(i, 0)), _DelegatBelki)]
        belki = [i for i, r in enumerate(m._rows) if "_group" in r]
        assert belki and _wiersze_z_belka() == belki
        v.combo_group.setCurrentIndex(0)
        QApplication.processEvents()
        assert _wiersze_z_belka() == []
        v.combo_group.setCurrentIndex(v.combo_group.findData("kind"))
        QApplication.processEvents()
        assert _wiersze_z_belka() == [i for i, r in enumerate(m._rows) if "_group" in r]
    finally:
        _zamknij_widok(v)
        con.close()


def test_belka_po_przewinieciu_w_poziomie_maluje_podpis_od_krawedzi_kadru(qapp, tmp_path, monkeypatch):
    """Tabela przewinięta w poziomie do końca - Qt podaje delegatowi belki prostokąt spanu z ujemną lewą
    krawędzią (kolumna 0 poza kadrem), a styl rysuje belkę od krawędzi kadru (podpis widoczny). Twierdzenie
    o pikselach - zrzut natywny w raporcie. Falsyfikator: delegat bez `max(left, 0)`."""
    from PySide6.QtWidgets import QAbstractSlider, QStyledItemDelegate
    con, v = _widok_z_belkami(tmp_path)
    try:
        lewe = []
        prawdziwy = QStyledItemDelegate.paint

        def _paint(self, painter, option, index):
            if "_group" in v.model._rows[index.row()]:
                lewe.append(option.rect.left())
            return prawdziwy(self, painter, option, index)
        monkeypatch.setattr(QStyledItemDelegate, "paint", _paint)
        hb = v.table.horizontalScrollBar()
        hb.triggerAction(QAbstractSlider.SliderToMaximum)
        QApplication.processEvents()
        assert v.table.columnViewportPosition(0) < 0, "kolumna 0 w kadrze - test nic by nie mierzył"
        lewe.clear()
        v.table.viewport().repaint()
        assert lewe and min(lewe) >= 0, lewe
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ wpisy rozstrzygnięte w oknach kart, numery po cofnięciu


def _okno_kart(rodzaj, con):
    from horreum.gui.app import ConfirmPathObjectsDialog, RepairHeaderDialog
    if rodzaj == "naprawa":
        dlg = RepairHeaderDialog(con, rows=queries.nameless_frames(con), db_path=queries.db_path_of(con),
                                 now_fn=lambda: NOW)
    else:
        dlg = ConfirmPathObjectsDialog(con, proposals=[], now_fn=lambda: NOW, db_path=queries.db_path_of(con))
    dlg._runner.async_ok = False
    return dlg


@pytest.mark.parametrize("rodzaj", ["naprawa", "sciezka"])
def test_okno_kart_porzuca_wylacznie_czekajace_wpisy(qapp, tmp_path, rodzaj):
    """Okno kart („Napraw nagłówek…”, „Zatwierdź ze ścieżki…”) porzuca staging przebiegu po awarii operacji
    (`_on_failed` → `_porzuc_staging`): na prawdziwym rdzeniu zapis drogą atomową przerwany po pierwszym pliku
    (`applied`) z wpisem odbitym kotwicą (`blocked`) - znikają wyłącznie czekające, rozstrzygnięte zostają
    (reguła szuflady, `repo.clear_waiting_staging`). Falsyfikator: `clear_pending_for_run` (kasował wpisy
    rozstrzygnięte drogi atomowej, a na `failed` tej drogi stoi potwierdzenie skanem)."""
    from horreum import repo
    _path, con, _p = _baza_szuflady(tmp_path, 4, nazwa="k")
    lok = [(r["id"], r["header_hash"]) for r in con.execute("SELECT id, header_hash FROM location ORDER BY id")]
    for i, (lid, hh) in enumerate(lok):
        repo.stage_pending(con, run_id="K", location_id=lid, keyword="TELESCOP", idx=0, op="set",
                           old_value="RC8", new_value="EQ6", new_type="str", new_comment=None,
                           expected_header_hash="inny" if i == 0 else hh)
    pliki = []

    def _po_drugim():
        pliki.append(1)
        return len(pliki) > 2
    writeback.commit(con, "K", now=NOW, should_cancel=_po_drugim)
    przed = sorted(r["status"] for r in con.execute("SELECT status FROM pending_changes WHERE run_id = 'K'"))
    assert przed == ["applied", "blocked", "pending", "pending"], przed
    dlg = _okno_kart(rodzaj, con)
    try:
        dlg._run_id = "K"
        dlg._on_failed("commit", "awaria", "")
        po = sorted(r["status"] for r in con.execute("SELECT status FROM pending_changes WHERE run_id = 'K'"))
        assert po == ["applied", "blocked"], po
    finally:
        dlg.reject()
        con.close()


@pytest.mark.parametrize("klinga", ["karty", "nazwy"])
def test_szuflada_po_cofnieciu_niesie_numery_operacji_wszystkich_plikow(qapp, tmp_path, monkeypatch, klinga):
    """Cofnięcie z szuflady (karty i Nazwy), które zostawiło dwa pliki izolowane: szczegół zdania pod kursorem
    niesie numer operacji i wywołanie rdzenia KAŻDEGO pliku z nazwą pliku - zdanie mówi gest, numerów nie mówi
    (AR-281). Atrapa wyłącznie wyniku operacji cofnięcia (`_OPS`). Falsyfikator: ogon cofnięcia z samym
    `podpowiedz_systemu` (szczegół bez numerów)."""
    from horreum.gui.wb_worker import WritebackWorker
    from test_powody_pisarza import _izolowane_dwa_pliki
    _path, con, _p = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con, inline=True)
    try:
        if klinga == "karty":
            _makro_przyciskiem(v, "TELESCOP", "EQ6")
        else:
            v._on_rename_stage(_POL)
        _klik_w(v.drawer.btn_commit)
        assert v._undo_btn.isVisible()
        wynik = writeback.UndoResult(1, [], [], _izolowane_dwa_pliki())
        op = "undo_run" if klinga == "karty" else "undo_rename"       # „Cofnij” kart = przebieg (AR-345)
        monkeypatch.setitem(WritebackWorker._OPS, op, lambda *_a: wynik)
        _klik_w(v._undo_btn)
        szczegol = v.drawer.result.szczegol()
        assert "a.fits: Operacja zapisu w miejscu 11: writeback.finish_inplace(11)" in szczegol, szczegol
        assert "b.fits: Operacja zapisu w miejscu 12: writeback.recover_torn(12)" in szczegol, szczegol
        assert "recover_torn" not in v.drawer.result.text()
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ wyłączność szuflady na bazę, przebiegi cudze


def test_szuflade_bazy_prowadzi_jedno_okno(qapp, tmp_path):
    """Dwa okna na jednej bazie (osobne połączenia): A zakłada przebieg - B go NIE podejmuje, mówi, że szufladę
    prowadzi inne okno, i nie przyjmuje własnego stagingu (przebieg drugiego właściciela rozjechałby się
    z pierwszym). Po zamknięciu A nowe okno podejmuje przebieg A w całości. Falsyfikatory: podjęcie bez
    blokady szuflady (B podejmuje żywy przebieg A), staging bez blokady (B zakłada drugi przebieg)."""
    path, con, _p = _baza_szuflady(tmp_path, 3)
    a = _widok_szuflady(con)
    _makro_przyciskiem(a, "TELESCOP", "EQ6")
    run_a = a._run_id
    con_b = db.connect(path)
    b = _widok_szuflady(con_b)
    try:
        assert b._run_id is None, "B podjęło przebieg żywego okna A"
        assert b.drawer.result.text() == _obcy()
        zdania = []
        b.status_message.connect(zdania.append)
        _makro_przyciskiem(b, "TELESCOP", "AZ-GTI")
        assert zdania[-1] == _obcy() and b._run_id is None
        assert {r[0] for r in con_b.execute("SELECT DISTINCT run_id FROM pending_changes")} == {run_a}
    finally:
        _zamknij_widok(b)
        con_b.close()
        _zamknij_widok(a)
        con.close()
    con, c = _restart(path)
    try:
        assert c._run_id == run_a and c._pending_count() == 3
        assert c.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", 3)
    finally:
        _zamknij_widok(c)
        con.close()


def test_blokada_martwego_procesu_nie_blokuje_podjecia(qapp, tmp_path):
    """Program zginął z blokadą szuflady (proces bez `unlock`) - plik blokady zostaje, ale jego proces nie żyje,
    więc następne okno ją przejmuje i podejmuje przebieg. Wiek blokady jej nie unieważnia
    (`setStaleLockTime(0)`), wyłącznie martwy proces. Falsyfikator: blokada bez wykrywania martwego procesu."""
    import subprocess
    import sys
    path, con, _p = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con)
    _makro_przyciskiem(v, "TELESCOP", "EQ6")
    _zamknij_widok(v)
    con.close()
    kod = ("import os, sys\nfrom PySide6.QtCore import QLockFile\n"
           "l = QLockFile(sys.argv[1]); l.setStaleLockTime(0)\nassert l.tryLock(0)\nos._exit(0)\n")
    subprocess.run([sys.executable, "-c", kod, path + ".szuflada.lock"], check=True, timeout=60)
    assert os.path.exists(path + ".szuflada.lock"), "proces nie zostawił blokady - test nic by nie mierzył"
    con, v = _restart(path)
    try:
        assert v._pending_count() == 2
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", 2)
    finally:
        _zamknij_widok(v)
        con.close()


def test_przebieg_z_zapisem_w_miejscu_nie_jest_podejmowany(qapp, tmp_path, monkeypatch):
    """Przebieg mieszany: zapis w miejscu przerwany po fazie `written` pierwszego pliku (re-sync pada), dalsze
    wpisy tego samego przebiegu czekają. Taki przebieg należy do dokończenia zapisu w miejscu (izolacja,
    Porządki) - szuflada go nie podejmuje wcale, a wpisy zostają nietknięte. Falsyfikator: predykat
    podjęcia odsiewający tylko pojedyncze wpisy z operacją."""
    from test_gui_izolacja_zapisu import _baza, _fazy
    con, _pliki = _baza(tmp_path, n=2)
    licz = []

    def _po_pierwszym():
        licz.append(1)
        return len(licz) > 1
    with monkeypatch.context() as m:
        m.setattr(writeback.scan, "scan_file",
                  lambda path, **kw: (_ for _ in ()).throw(OSError(64, "zerwany udział")))
        writeback.commit(con, "R", now=NOW, inplace=True, should_cancel=_po_pierwszym)
    assert _fazy(con) == ["written"]
    przed = [tuple(r) for r in con.execute(
        "SELECT id, status, inplace_op_id IS NOT NULL FROM pending_changes ORDER BY id")]
    assert [s for _i, s, _w in przed].count("pending") == 1 and any(w for *_r, w in przed), przed
    assert queries.oczekujace_przebiegi_szuflady(con) == []
    v = _widok_szuflady(con, inline=True)
    try:
        # Nie podjęty, ale nie „pusta” - szuflada mówi, ile zmian czeka na zapis w miejscu (AR-308).
        assert v._run_id is None and v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_isolated", 1)
        assert [tuple(r) for r in con.execute(
            "SELECT id, status, inplace_op_id IS NOT NULL FROM pending_changes ORDER BY id")] == przed
    finally:
        _zamknij_widok(v)
        con.close()


@pytest.mark.parametrize("gest", ["odrzuc", "ponowny_staging"])
def test_wpis_failed_po_odrzuceniu_potwierdza_skan(qapp, tmp_path, monkeypatch, gest):
    """Wpis `failed` drogi atomowej (re-sync padł po podmianie pliku) przeżywa „Odrzuć” przebiegu podjętego
    po restarcie (prawdziwy klik) i ponowny staging (czyszczenie czekających rdzenia), a skan dokańcza commit:
    wpis `applied` z potwierdzeniem, nagrobek ręki zgaszony. Falsyfikator: czyszczenie zdejmujące także
    `failed` (skan nie ma czego potwierdzić - klatka zostaje `user_cleared` przy karcie w pliku)."""
    from horreum import repo, scan
    from test_undo_nagrobek import _baza_z_nagrobkiem, _commit_failed, _stan, _wpisy
    con, p, lid, fid, _cos = _baza_z_nagrobkiem(tmp_path)
    res, hh = _commit_failed(con, lid, "R", monkeypatch, awaria="odczyt")
    repo.stage_pending(con, run_id="R", location_id=lid, keyword="TELESCOP", idx=0, op="set",
                       old_value=None, new_value="EQ6", new_type="str", new_comment=None,
                       expected_header_hash=hh)
    if gest == "odrzuc":
        v = _widok_szuflady(con, inline=True)
        try:
            assert v._run_id == "R" and v._pending_count() == 1
            _klik_w(v.drawer.btn_reject)
        finally:
            _zamknij_widok(v)
    else:
        repo.clear_waiting_staging(con, run_id="R", klinga="karty")
    assert [s for s, _r in _wpisy(con, "R")] == ["failed"]
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary(),
                       pochodzenie=repo.ZEWNETRZNE)
    (status, powod), = _wpisy(con, "R")
    assert status == "applied" and f"commicie {res.commit_id}" in powod
    assert _stan(con, fid) == (None, None, None)
    con.close()


def test_makro_po_dokonczeniu_podjetego_przebiegu_mowi_zdaniem_neutralnym(qapp, tmp_path, monkeypatch):
    """Przebieg podjęty po restarcie, „Zatwierdź”, „Anuluj” po pierwszym pliku, „Do stagingu” makra: odmowa mówi
    „w szufladzie czekają 2 zmiany” - ani „z poprzedniej sesji” (przebieg prowadzi już ta sesja), ani „edycje
    komórek” (nikt nie edytował). Falsyfikator: klucz odmowy z porównania `run_id`, nie z predykatu etykiety."""
    path, con, _p = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    _makro_przyciskiem(v, "TELESCOP", "EQ6")
    _zamknij_widok(v)
    con.close()
    con, v = _restart(path)
    try:
        _przerwany_zapis(v, monkeypatch)
        assert v._pending_count() == 2
        zdania = []
        v.status_message.connect(zdania.append)
        _makro_przyciskiem(v, "TELESCOP", "AZ-GTI")
        assert zdania[-1] == i18n.t_plural("grid.drawer.macro_blocked", 2), zdania[-1]
    finally:
        _zamknij_widok(v)
        con.close()


def _cztery_pliki_dwie_kopie(tmp_path):
    """Cztery FITS, dwie pierwsze klatki z drugą obecną kopią - makro zmieni dwie, a dwie pominie."""
    path, con, pliki = _baza_szuflady(tmp_path, 4, nazwa="q")
    with con:
        for i, fid in enumerate(r[0] for r in con.execute("SELECT frame_id FROM location ORDER BY frame_id "
                                                          "LIMIT 2").fetchall()):
            con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                        (fid, f"X:/L/kopia{i}.fits"))
    return con


@pytest.mark.parametrize("przycisk", ["stage", "prev"])
def test_zmiany_i_pominiecia_razem_mowia_przyczyny(qapp, tmp_path, przycisk):
    """Staging (i „Podgląd”) prawdziwym klikiem: dwie zmiany i dwa pominięcia - zdanie niesie liczby i przyczynę
    pominięć; przy stagingu szuflada „2 zmiany oczekują” z tym zdaniem w wyniku. Falsyfikatory: wynik szuflady
    tylko przy zerze zmian, „Podgląd” bez rozbicia."""
    from horreum.gui.grid_model import zdanie_pominiec_makra
    con = _cztery_pliki_dwie_kopie(tmp_path)
    v = _widok_szuflady(con, inline=True)
    try:
        zdania = []
        v.status_message.connect(zdania.append)
        _makro_przyciskiem(v, "TELESCOP", "EQ6", przycisk=przycisk)
        pominiete = [p["skipped"] for p in v.model._preview.values() if "skipped" in p]
        assert len(pominiete) == 2
        rozbicie = zdanie_pominiec_makra([type("S", (), {"reason": p})() for p in pominiete])
        assert rozbicie.startswith(" - 2: ")
        if przycisk == "prev":
            assert zdania[-1] == i18n.t("grid.macro.preview_result", t=2, s=2) + rozbicie
        else:
            oczek = i18n.t_plural("grid.macro.staged", 2, s=2) + rozbicie
            assert zdania[-1] == oczek
            assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending", 2)
            assert v.drawer.result.text() == oczek
    finally:
        _zamknij_widok(v)
        con.close()


def test_ta_kopia_prowadzi_przy_zywym_cofnij_niesie_identyfikator_raz(qapp, tmp_path):
    """AR-276, gałąź „Ta kopia prowadzi”: zapis szuflady (żywe „Cofnij”), potem gest kopii wiodącej prawdziwym
    menu i wątkiem tła - wiersz szuflady mówi wynik gestu z identyfikatorem commitu dokładnie raz, etykieta
    „Zatwierdzono” zostaje. Falsyfikator: ogon gestu bez `_zdanie_przy_cofnij` (zero)."""
    from test_gui_lead_copy import _lpro, _cls, _po_gescie, _pozycje_kopii, _prawy_klik, _wiersz
    from horreum import scan
    from test_copy_facts import NOW as TERAZ
    root = tmp_path / "ARCH"
    a = _lpro(root)
    _cls(root)
    _cls(root, payload=b"\x09" * 32, sub="SOLO")
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=TERAZ)
    fid = con.execute("SELECT frame_id FROM location WHERE path = ?", (str(a),)).fetchone()[0]
    v = _widok_szuflady(con)
    try:
        _makro_przyciskiem(v, "EXPTIME", "0.3")
        assert v._pending_count() >= 1
        _klik_w(v.drawer.btn_commit)
        assert _po_gescie(v)
        ident = f"commit {v._undo_commity[0]})"
        assert v._undo_mode == "macro" and _wiersz_szuflady(v).count(ident) == 1
        v.apply_perspective(grid_mod.PRESET_COPY_CONFLICT)
        _prawy_klik(v, _wiersz(v, fid))
        _pozycje_kopii(v)[1].trigger()
        v._menu_tabeli.hide()
        assert _po_gescie(v)
        assert v._undo_mode == "macro" and _wiersz_szuflady(v).count(ident) == 1, _wiersz_szuflady(v)
        assert v.drawer.label.text().startswith(i18n.t("grid.wb.committed_label", n=1)[:12])
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ AR-308 - przebieg zatrzymany izolacją zapisu w miejscu


def _zatrzymany_izolacja(tmp_path, monkeypatch, n=3, faza="written"):
    """Przebieg `R` (karta OBJECT na `n` plikach) zatrzymany izolacją tak, jak zostawia go program zabity
    w biegu zapisu w miejscu: pierwszy plik zapisany i związany z operacją w fazie `faza` (`written` - re-sync
    padł; `unverified` - `fsync` padł po zapisie), reszta czeka. Prawdziwy pisarz; atrapą jest wyłącznie
    status wpisu związanego - proces zginął przed jego zapisem, więc wpis zostaje `pending`. Zwraca
    (ścieżka bazy, [(plik, frame_id)]) - połączenie zamknięte (restart)."""
    from test_gui_izolacja_zapisu import _baza, _fazy
    con, pliki = _baza(tmp_path, n=n)
    licz = []

    def _po_pierwszym():
        licz.append(1)
        return len(licz) > 1
    with monkeypatch.context() as m:
        if faza == "written":
            m.setattr(writeback.scan, "scan_file",
                      lambda path, **kw: (_ for _ in ()).throw(OSError(64, "zerwany udział")))
        else:
            prawdziwy = os.fsync

            def _fsync(fd):
                prawdziwy(fd)
                raise OSError(64, "The specified network name is no longer available")
            m.setattr(writeback.os, "fsync", _fsync)
        writeback.commit(con, "R", now=NOW, inplace=True, should_cancel=_po_pierwszym)
    assert _fazy(con) == [faza]
    with con:
        con.execute("UPDATE pending_changes SET status = 'pending' WHERE inplace_op_id IS NOT NULL")
    assert con.execute("SELECT count(*) FROM pending_changes WHERE status = 'pending'").fetchone()[0] == n
    con.close()
    return str(tmp_path / "h.db"), pliki


def _statusy(con):
    return [tuple(r) for r in con.execute(
        "SELECT run_id, status, inplace_op_id FROM pending_changes ORDER BY id")]


class _ZwolnijBezOkna:
    """Okno „Zwolnij plik do skanu…” zaakceptowane z powodem - bez modalu w teście."""

    def __init__(self, n, parent=None):
        self.n = n

    def exec(self):
        from PySide6.QtWidgets import QDialog
        return QDialog.Accepted

    def reason(self):
        return "plik przywrócony z pełnej kopii"


_GEST_IZOLACJI = {"dokoncz": "act_finish_write", "przywroc": "act_restore_header", "zwolnij": "act_release_file"}


def _makro_dodaj(v, kw, wartosc):
    """Panel makra, `add` karty i „Do stagingu” prawdziwym klikiem (pliki izolacji nie mają karty do `set`)."""
    if not v.macro_bar.isVisible():
        _klik_w(v.sel_bar.btn_macro)
    b = v.macro_bar
    b.asg_kw.setCurrentText(kw)
    b.asg_op.setCurrentIndex(1)
    b.asg_expr.setText(wartosc)
    b.comp_name.setText("")
    b.comp_expr.setText("")
    _klik_w(b.btn_stage)


def _gest_izolacji(v, gest, fid, monkeypatch, faza="written"):
    """Gest izolacji z menu Zbiorów nad klatką `fid`: perspektywa izolacji fazy `faza`, zaznaczenie, akcja
    pozycji menu (`QAction.trigger` - ten sam slot co klik w menu), czekanie pętlą na wątek zapisu
    i przyłożenie zbioru."""
    from test_gui_izolacja_zapisu import _zaznacz
    from test_gui_pasek_szczegol import _czekaj
    akcja = _GEST_IZOLACJI[gest]
    if gest == "zwolnij":
        monkeypatch.setattr(grid_mod, "ReleaseDialog", _ZwolnijBezOkna)
    v.apply_perspective(grid_mod.PRESET_PENDING_FINISH if faza == "written" else grid_mod.PRESET_TORN_WRITE)
    _czekaj(lambda: not v._zbior_w_drodze(), "perspektywa izolacji")
    _zaznacz(v, [fid])
    v._sync_menu_zapisu()
    assert getattr(v, akcja).isEnabled(), getattr(v, akcja).toolTip()
    getattr(v, akcja).trigger()
    _czekaj(lambda: not v._wb.is_busy and not v._zbior_w_drodze(), f"gest {gest}")


@pytest.mark.parametrize("faza", ["written", "unverified"])
@pytest.mark.parametrize("lang", ["pl", "en"])
def test_przebieg_zatrzymany_izolacja_mowi_ile_czeka_i_droge(qapp, tmp_path, monkeypatch, lang, faza):
    """Restart po zapisie w miejscu przerwanym śmiercią programu: szuflada przebiegu nie podejmuje (należy do
    dokończenia albo odzysku), ale nie mówi „pusta” - etykieta liczy czekające zmiany, wynik mówi gest i wiersz
    Porządków właściwy fazie operacji. Wpisy w bazie nietknięte. Falsyfikatory: pusta szuflada bez zdania
    izolacji („pusta”); droga dokończenia przy zapisie przerwanym (albo odwrotnie)."""
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch, faza=faza)
    i18n.set_lang(lang)
    con, v = _restart(path)
    try:
        przed = _statusy(con)
        assert v._run_id is None
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_isolated", 3)
        nav = i18n.t("nav.porzadki")
        if faza == "written":
            droga = i18n.t("grid.drawer.isolated_finish", finish=i18n.t("grid.inplace.finish"), nav=nav,
                           row=i18n.t("tasks.pending_finish_frames"))
        else:
            droga = i18n.t("grid.drawer.isolated_torn", restore=i18n.t("grid.inplace.restore"),
                           release=i18n.t("grid.inplace.release"), nav=nav, row=i18n.t("tasks.torn_write_frames"))
        assert v.drawer.result.text() == droga
        assert not v.drawer.btn_commit.isEnabled() and not v.drawer.btn_reject.isEnabled()
        assert _statusy(con) == przed
    finally:
        _zamknij_widok(v)
        con.close()


@pytest.mark.parametrize("gest,faza,n", [("dokoncz", "written", 3), ("przywroc", "unverified", 3),
                                         ("zwolnij", "written", 1)])
def test_gest_zamykajacy_izolacje_podejmuje_przebieg_w_tej_samej_sesji(qapp, tmp_path, monkeypatch, gest,
                                                                      faza, n):
    """„Dokończ zapis” / „Przywróć nagłówek…” / „Zwolnij…” zamyka ostatnią operację izolującą przebiegu - szuflada
    podejmuje go od razu, w tej samej sesji: „Z poprzedniej sesji czeka N” z czynnymi Zatwierdź/Odrzuć, wynik =
    zdanie gestu + zdanie przebiegu, a „Zatwierdź” rozstrzyga wszystkie czekające wpisy. Przebieg jednego pliku
    (jedyny wpis związany z operacją) też - po „Zwolnij” z N = 1 (operacja zamknięta ręką, wpis wiąże się na
    nowo). Falsyfikator: ogon gestu bez podjęcia (szuflada dalej bez przebiegu, zmiany wracają dopiero przy
    kolejnym otwarciu bazy)."""
    from test_gui_pasek_szczegol import _czekaj
    path, pliki = _zatrzymany_izolacja(tmp_path, monkeypatch, n=n, faza=faza)
    con, v = _restart(path)
    try:
        assert v._run_id is None and v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_isolated", n)
        _gest_izolacji(v, gest, pliki[0][1], monkeypatch, faza)
        czeka = v._pending_count()
        assert v._run_id == "R" and czeka >= 1, (gest, _statusy(con))
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", czeka)
        assert v.drawer.btn_commit.isVisible() and v.drawer.btn_commit.isEnabled()
        assert v.drawer.btn_reject.isEnabled()
        przebieg = v._zdanie_przebiegu_poprzedniego()
        assert przebieg and v.drawer.result.text().endswith(" · " + przebieg), v.drawer.result.text()
        _klik_w(v.drawer.btn_commit)
        _czekaj(lambda: not v._wb.is_busy, "Zatwierdź po podjęciu")
        assert not [s for r, s, _o in _statusy(con) if r == "R" and s == "pending"], _statusy(con)
    finally:
        _zamknij_widok(v)
        con.close()


def test_przywroc_odmawia_na_poprawnym_zapisie_szuflada_dalej_mowi_o_izolacji(qapp, tmp_path, monkeypatch):
    """„Przywróć nagłówek…” na zapisie zweryfikowanym (faza `written`, kontrola danych przechodzi) rdzeń odmawia
    - operacja dalej izoluje, więc szuflada niczego nie podejmuje i dalej mówi o izolacji. Falsyfikator:
    podjęcie po każdym geście izolacji bez względu na wynik (przebieg należący do dokończenia w szufladzie)."""
    path, pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        _gest_izolacji(v, "przywroc", pliki[0][1], monkeypatch)
        assert v._run_id is None
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_isolated", 3)
    finally:
        _zamknij_widok(v)
        con.close()


def test_zmiana_perspektywy_po_podjeciu_nie_wraca_do_zdania_izolacji(qapp, tmp_path, monkeypatch):
    """Po „Dokończ zapis” i podjęciu zmiana perspektywy oddaje szufladzie zdanie podjętego przebiegu - nie zdanie
    izolacji sprzed gestu, które już nie jest prawdą. Falsyfikator: pamięć wyniku gestu bez poprawki przy
    podjęciu (droga „najpierw Dokończ zapis” obok etykiety „Z poprzedniej sesji czeka”)."""
    from test_gui_pasek_szczegol import _czekaj
    path, pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        droga = v.drawer.result.text()
        _gest_izolacji(v, "dokoncz", pliki[0][1], monkeypatch)
        assert v._run_id == "R"
        v.apply_perspective(grid_mod.PRESET_TORN_WRITE)
        _czekaj(lambda: not v._zbior_w_drodze(), "inna perspektywa")
        assert v.drawer.result.text() == v._zdanie_przebiegu_poprzedniego() != droga
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", v._pending_count())
    finally:
        _zamknij_widok(v)
        con.close()


def test_podjecie_po_gescie_wymaga_blokady_szuflady(qapp, tmp_path, monkeypatch):
    """Dwa okna na jednej bazie: szufladę prowadzi okno A (własny staging), „Dokończ zapis” robi okno B - B nie
    podejmuje przebiegu, mówi, że szufladę prowadzi inne okno, a czekające wpisy zostają. Falsyfikator: podjęcie
    po geście bez blokady szuflady (B prowadzi przebieg obok żywego A)."""
    path, pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con_a, a = _restart(path)
    con_b = None
    try:
        _makro_dodaj(a, "OBSERVER", "obs")
        assert a._run_id not in (None, "R")
        con_b, b = _restart(path)
        try:
            _gest_izolacji(b, "dokoncz", pliki[0][1], monkeypatch)
            assert b._run_id is None
            assert _obcy() in b.drawer.result.text()
            assert len([s for r, s, _o in _statusy(con_b) if r == "R" and s == "pending"]) == 2
        finally:
            _zamknij_widok(b)
    finally:
        if con_b is not None:
            con_b.close()
        _zamknij_widok(a)
        con_a.close()


def test_podjecie_po_gescie_bierze_przebieg_z_izolacji_nie_starszy_zwykly(qapp, tmp_path, monkeypatch):
    """Szuflada wolna, czeka zwykły przebieg `Y` NOWSZY niż zatrzymany `R`: „Dokończ zapis” podejmuje `R`
    (ten, który gest zwolnił), a `Y` dalej wraca przy kolejnym otwarciu bazy (reguła starszych przebiegów).
    Falsyfikator: podjęcie najnowszego podejmowalnego bez pamięci przebiegów zatrzymanych (`Y`)."""
    from horreum import repo
    path, pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con = db.connect(path)
    lok = [(r["id"], r["header_hash"]) for r in con.execute(
        "SELECT id, header_hash FROM location ORDER BY id")]
    for run_id, (lid, hh) in (("Y", lok[1]), ("Z", lok[2])):
        repo.stage_pending(con, run_id=run_id, location_id=lid, keyword="TELESCOP", idx=0, op="set",
                           old_value=None, new_value="EQ6", new_type="str", new_comment=None,
                           expected_header_hash=hh)
    con.close()
    con, v = _restart(path)
    try:
        assert v._run_id == "Z"
        _klik_w(v.drawer.btn_reject)                     # szuflada wolna, Y czeka, R zatrzymany
        assert v._run_id is None
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_isolated", 3)
        _gest_izolacji(v, "dokoncz", pliki[0][1], monkeypatch)
        assert v._run_id == "R"
    finally:
        _zamknij_widok(v)
        con.close()


def test_szuflada_zajeta_przy_zamknieciu_izolacji_mowi_ze_wroci(qapp, tmp_path, monkeypatch):
    """Żywe „Cofnij” zapisu tej sesji w chwili, gdy „Dokończ zapis” zwalnia przebieg zatrzymany: szuflada go nie
    podejmuje (świeżego „Cofnij” nie zdejmujemy po cichu) i mówi, że zmiany wrócą przy kolejnym otwarciu bazy.
    Falsyfikator: podjęcie przy żywym „Cofnij” („Cofnij” znika albo stoi obok Zatwierdź/Odrzuć)."""
    from test_gui_pasek_szczegol import _czekaj
    path, pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        _makro_dodaj(v, "OBSERVER", "obs")
        assert v._run_id not in (None, "R") and v._pending_count() >= 1
        _klik_w(v.drawer.btn_commit)
        _czekaj(lambda: not v._wb.is_busy and not v._zbior_w_drodze(), "zapis tej sesji")
        assert v._undo_mode == "macro"
        _gest_izolacji(v, "dokoncz", pliki[0][1], monkeypatch)
        assert v._run_id is None and v._undo_mode == "macro" and v._undo_btn.isVisible()
        assert i18n.t_plural("grid.drawer.isolated_ready", 2) in v.drawer.result.text()
    finally:
        _zamknij_widok(v)
        con.close()


def test_awaria_gestu_po_zamknieciu_operacji_podejmuje_przebieg(qapp, tmp_path, monkeypatch):
    """Wyjątek całej operacji gestu PO tym, jak pętla zamknęła operację (prawdziwe dokończenie, potem wyjątek):
    ogon awarii też podejmuje przebieg, a szuflada mówi zdaniem operacji z nazwą gestu. Falsyfikator: ogon
    awarii bez podjęcia (pusta szuflada przy przebiegu podejmowalnym)."""
    from horreum.gui.wb_worker import WritebackWorker, po_operacjach

    def _dokoncz_i_pada(con, t, now, pr, sc):
        po_operacjach(con, t, now, pr, sc, writeback.finish_inplace)
        raise ValueError("złamany inwariant po dokończeniu")
    path, pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        monkeypatch.setitem(WritebackWorker._OPS, "finish_inplace", _dokoncz_i_pada)
        _gest_izolacji(v, "dokoncz", pliki[0][1], monkeypatch)
        assert v._run_id == "R"
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", v._pending_count())
        assert v.drawer.result.text().startswith(i18n.t("grid.wb.op.finish_inplace", msg=""))
    finally:
        _zamknij_widok(v)
        con.close()


def test_klucze_izolacji_odmieniaja_liczbe():
    """Odmiana kluczy zdania izolacji (1, 2, 5, 12, 22) w PL i EN; EN bez polskich znaków i bez „."""
    i18n.set_lang("pl")
    assert [i18n.t_plural("grid.drawer.pending_isolated", n).split(",")[0] for n in (1, 2, 5, 12, 22)] == [
        "1 zmiana czeka", "2 zmiany czekają", "5 zmian czeka", "12 zmian czeka", "22 zmiany czekają"]
    assert [i18n.t_plural("grid.drawer.isolated_ready", n).split(" - ")[0] for n in (1, 2, 5, 12, 22)] == [
        "1 zmiana zwolniona z zapisu w miejscu czeka", "2 zmiany zwolnione z zapisu w miejscu czekają",
        "5 zmian zwolnionych z zapisu w miejscu czeka", "12 zmian zwolnionych z zapisu w miejscu czeka",
        "22 zmiany zwolnione z zapisu w miejscu czekają"]
    assert i18n.t_plural("grid.drawer.isolated_more", 22) == "czekają też 22 zmiany zatrzymane zapisem w miejscu"
    assert i18n.t_plural("grid.drawer.isolated_more", 5) == "czeka też 5 zmian zatrzymanych zapisem w miejscu"
    i18n.set_lang("en")
    assert i18n.t_plural("grid.drawer.pending_isolated", 1) == "1 change waits for an in-place write to be settled"
    assert i18n.t_plural("grid.drawer.pending_isolated", 2) == "2 changes wait for an in-place write to be settled"
    for klucz in ("grid.drawer.pending_isolated", "grid.drawer.isolated_more", "grid.drawer.isolated_ready",
                  "grid.drawer.isolated_finish", "grid.drawer.isolated_torn"):
        for n in (1, 2):
            tekst = (i18n.t_plural(klucz, n) if klucz.endswith(("isolated", "more", "ready"))
                     else i18n.t(klucz, finish="F", restore="R", release="Z", nav="N", row="W"))
            assert not set(tekst) & set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ„"), tekst


# ============================================================ AR-309 - zdania szuflady


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_pole_zdania_kopiuje_samo_polecenie(qapp, tmp_path, lang):
    """Pole zdania (`EtykietaBledu` - wynik szuflady) z poleceniem podanym osobno: prawdziwy prawy klik daje
    „Kopiuj zdanie”, „Kopiuj szczegół”, „Kopiuj polecenie”, a ta ostatnia kopiuje SAMO polecenie (szczegół niesie
    prozę z poleceniem - wklejona do terminala proza pada pierwsza). Zdanie bez polecenia (`setText`) zdejmuje
    pozycję. Falsyfikatory: menu bez pozycji polecenia; `setText` zostawia polecenie poprzedniego zdania;
    pozycja kopiuje szczegół."""
    from PySide6.QtGui import QGuiApplication
    from prawy_klik import menu_pola_otwarte, prawy_klik
    i18n.set_lang(lang)
    _path, con, _p = _baza_szuflady(tmp_path, 1)
    v = _widok_szuflady(con, inline=True)
    pole = v.drawer.result
    polecenie = 'horreum header-fix "X:\\L\\h.db" --undo 7'
    szczegol = "Cofnięcie commitu 7 po zamknięciu okna (wiersz poleceń):\n" + polecenie
    try:
        pole.ustaw("4 zapisane", szczegol, polecenie=polecenie)
        assert pole.polecenie() == polecenie
        prawy_klik(pole)
        pozycje = menu_pola_otwarte(pole)
        assert list(pozycje) == [i18n.t("wb.copy_sentence"), i18n.t("wb.copy_detail"), i18n.t("wb.copy_command")]
        pozycje[i18n.t("wb.copy_command")].trigger()
        assert QGuiApplication.clipboard().text() == polecenie
        pole._menu.hide()
        pole.setText("inne zdanie")
        assert pole.polecenie() == ""
        prawy_klik(pole)
        assert i18n.t("wb.copy_command") not in menu_pola_otwarte(pole)
        pole._menu.hide()
    finally:
        _zamknij_widok(v)
        con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_awaria_operacji_w_szufladzie_mowi_nazwe_gestu(qapp, tmp_path, monkeypatch, lang):
    """Wyjątek całej operacji zapisu (błąd programu) po kliku „Zatwierdź”: szuflada mówi tym samym zdaniem
    operacji co pasek - z nazwą tego, co się nie udało, w PL i EN - a nie „BŁĄD: błąd programu…”.
    Falsyfikator: wynik szuflady z `grid.wb.error`."""
    from horreum.gui.wb_worker import WritebackWorker

    def _pada(*_a):
        raise ValueError("złamany inwariant zapisu")
    i18n.set_lang(lang)
    _path, con, _p = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con, inline=True)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        monkeypatch.setitem(WritebackWorker._OPS, "commit", _pada)
        _klik_w(v.drawer.btn_commit)
        assert v.drawer.result.text() == i18n.t("grid.wb.op.commit", msg=i18n.t("objchg.item.prog_error"))
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ AR-305 - Nazwy: „Cofnij” znika dopiero przy zmianie


def test_zly_wzor_nazw_przy_zywym_cofnij_zostawia_cofnij(qapp, tmp_path):
    """Zapis makra (żywe „Cofnij”), potem „Do stagingu” Nazw ze złym wzorem: zdanie błędu wzoru na pasku i w
    wierszu szuflady (z identyfikatorem commitu, jak błąd definicji makra), a „Cofnij”, jego tryb i etykieta
    „Zatwierdzono…” zostają - zły wzór niczego do szuflady nie wnosi. Falsyfikator: `_dismiss_undo` przed
    walidacją wzoru (szuflada bez żadnego przycisku)."""
    _path, con, _p = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con, inline=True)
    try:
        zdania = []
        v.status_message.connect(zdania.append)
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _klik_w(v.drawer.btn_commit)
        etykieta = v.drawer.label.text()
        v._on_rename_stage({**_POL, "template": ["datetime", {"t": "orig", "re": "("}]})
        assert zdania[-1].startswith(i18n.t("grid.rename.error", e="")), zdania[-1]
        assert v._undo_mode == "macro" and v._undo_btn.isVisible() and v.drawer.label.text() == etykieta
        assert v.drawer.result.text() == zdania[-1] + i18n.t("grid.wb.commit_id", id=v._undo_commity[0])
        assert v._rename_run_id is None
    finally:
        _zamknij_widok(v)
        con.close()


def test_staging_nazw_bez_zmian_przy_zywym_cofnij_mowi_w_szufladzie(qapp, tmp_path):
    """Zmiana nazw zapisana (żywe „Cofnij” przebiegu nazw), potem ten sam staging - nazwy już kanoniczne, zero
    zmian: „Cofnij” zostaje przy tym samym przebiegu, a zdanie stagingu staje w wierszu szuflady obok niego
    z identyfikatorem przebiegu raz (jak w makrze). Falsyfikatory: `_dismiss_undo` przy zerze zmian; mint nowego
    przebiegu przy zerze zmian; zdanie stagingu tylko na pasku."""
    _path, con, _p = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con, inline=True)
    try:
        zdania = []
        v.status_message.connect(zdania.append)
        v._on_rename_stage(_POL)
        _klik_w(v.drawer.btn_commit)
        run = v._undo_rename_run_id
        etykieta = v.drawer.label.text()
        v._on_rename_stage(_POL)
        assert v._undo_mode == "rename" and v._undo_btn.isVisible() and v._undo_rename_run_id == run
        assert v._rename_run_id == run and v.drawer.label.text() == etykieta
        assert zdania[-1].startswith(i18n.t_plural("grid.rename.staged", 0, s=2, target="")[:10]), zdania[-1]
        assert v.drawer.result.text() == zdania[-1] + i18n.t("grid.wb.run_id", id=run)
    finally:
        _zamknij_widok(v)
        con.close()


def test_staging_nazw_bez_zmian_nie_bierze_blokady_szuflady(qapp, tmp_path):
    """Staging Nazw bez żadnej zmiany nie zakłada przebiegu - nie trzyma więc blokady szuflady: drugie okno na tej
    bazie przyjmuje swój staging. Falsyfikator: mint przebiegu i blokada przy zerze zmian (drugie okno słyszy
    „szufladę prowadzi inne okno”, choć nic nie czeka)."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    a = _widok_szuflady(con, inline=True)
    con_b = db.connect(path)
    b = None
    try:
        a._on_rename_stage(_POL)
        _klik_w(a.drawer.btn_commit)                     # nazwy kanoniczne, przebieg zapisany - blokada oddana
        a._on_rename_stage(_POL)                         # zero zmian
        b = _widok_szuflady(con_b, inline=True)
        _makro_przyciskiem(b, "TELESCOP", "EQ6")
        assert b._run_id is not None and b._pending_count() == 2
    finally:
        if b is not None:
            _zamknij_widok(b)
        con_b.close()
        _zamknij_widok(a)
        con.close()


def test_odrzuc_po_zwolnij_zdejmuje_wpis_zwiazany_z_operacja_zamknieta(qapp, tmp_path, monkeypatch):
    """Przebieg jednego pliku zatrzymany izolacją, „Zwolnij…” - szuflada podejmuje go (jedyny wpis związany
    z operacją zamkniętą ręką), a „Odrzuć” zdejmuje także ten wpis: w bazie nie zostaje nic czekającego, czego
    szuflada już by nie pokazała; dziennik ma odrzucenie jednej zmiany. Falsyfikator: „Odrzuć” zdejmujące
    wyłącznie wpisy bez związku z operacją (wpis zostaje `pending` bez słowa)."""
    path, pliki = _zatrzymany_izolacja(tmp_path, monkeypatch, n=1)
    con, v = _restart(path)
    try:
        _gest_izolacji(v, "zwolnij", pliki[0][1], monkeypatch)
        assert v._run_id == "R" and v._pending_count() == 1
        _klik_w(v.drawer.btn_reject)
        assert v._run_id is None
        assert not [s for r, s, _o in _statusy(con) if r == "R" and s == "pending"], _statusy(con)
        # Zapis zwolniony ręką to commit przebiegu bez dowodu podmiany (AR-345): „Cofnij” go sprawdzi, etykieta
        # mówi „Do sprawdzenia: 1”, nie „Zatwierdzono” - dawniej pustostan.
        assert v.drawer.label.text() == i18n.t("grid.wb.to_check_label", n=1)
        assert v._undo_btn.isVisible()
        zdarzenie = con.execute("SELECT payload FROM event WHERE verb = 'staging.discarded'").fetchone()
        assert json.loads(zdarzenie["payload"]) == {"n": 1, "klinga": "karty"}
    finally:
        _zamknij_widok(v)
        con.close()


def test_izolacja_zamknieta_innym_polaczeniem_odswiezenie_podejmuje(qapp, tmp_path, monkeypatch):
    """Izolację przebiegu zamyka ktoś inny (drugie połączenie - jak CLI albo drugie okno - prawdziwe
    `writeback.finish_inplace`), a widok tylko odświeża szufladę (koniec cudzego zapisu, bez restartu): przebieg
    zapamiętany jako zatrzymany jest już podejmowalny, więc szuflada go podejmuje - nie mówi „pusta” przy
    czekających wpisach. Falsyfikator: odświeżenie pustej szuflady bez `_podejmij_zwolnione`."""
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_isolated", 3)
        con2 = db.connect(path)
        try:
            op_id = con2.execute("SELECT id FROM inplace_op").fetchone()[0]
            assert writeback.finish_inplace(con2, op_id, now=NOW).status == "applied"
        finally:
            con2.close()
        v.set_writeback_busy(True)                       # cudzy zapis plików (okno naprawy) i jego koniec -
        v.set_writeback_busy(False)                      # zwykłe odświeżenie szuflady
        assert v._run_id == "R" and v._pending_count() == 2
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", 2)
        assert v.drawer.btn_commit.isVisible() and v.drawer.btn_commit.isEnabled()
    finally:
        _zamknij_widok(v)
        con.close()


def _dokoncz_i_pada(monkeypatch):
    """Operacja „Dokończ zapis”, której pętla PRAWDZIWIE zamyka operację, a potem rzuca wyjątek."""
    from horreum.gui.wb_worker import WritebackWorker, po_operacjach

    def _op(con, t, now, pr, sc):
        po_operacjach(con, t, now, pr, sc, writeback.finish_inplace)
        raise ValueError("złamany inwariant po dokończeniu")
    monkeypatch.setitem(WritebackWorker._OPS, "finish_inplace", _op)


def test_awaria_gestu_przy_zywym_cofnij_mowi_ze_zmiany_czekaja(qapp, tmp_path, monkeypatch):
    """Częściowa awaria gestu izolacji (operacja zamknięta, potem wyjątek) przy żywym „Cofnij”: szuflada nie
    podejmuje przebiegu, a zdanie błędu mówi też, że zwolnione zmiany czekają; „Cofnij” i „Zatwierdzono” zostają.
    Falsyfikator: ogon awarii gubiący człon `_podejmij_po_izolacji` (samo zdanie błędu)."""
    from test_gui_pasek_szczegol import _czekaj
    path, pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        _makro_dodaj(v, "OBSERVER", "obs")
        _klik_w(v.drawer.btn_commit)
        _czekaj(lambda: not v._wb.is_busy and not v._zbior_w_drodze(), "zapis tej sesji")
        assert v._undo_mode == "macro"
        _dokoncz_i_pada(monkeypatch)
        _gest_izolacji(v, "dokoncz", pliki[0][1], monkeypatch)
        wynik = v.drawer.result.text()
        assert v._run_id is None and v._undo_mode == "macro" and v._undo_btn.isVisible()
        assert wynik.startswith(i18n.t("grid.wb.op.finish_inplace", msg="")[:20]), wynik
        assert i18n.t_plural("grid.drawer.isolated_ready", 2) in wynik, wynik
        assert v.drawer.label.text() != i18n.t("grid.drawer.empty")
    finally:
        _zamknij_widok(v)
        con.close()


def test_awaria_gestu_przy_cudzej_blokadzie_mowi_ze_zmiany_czekaja(qapp, tmp_path, monkeypatch):
    """Częściowa awaria gestu izolacji w oknie B, gdy szufladę prowadzi okno A: B nie podejmuje przebiegu, zdanie
    błędu mówi, kto prowadzi szufladę, a etykieta - że zmiany czekają na podjęcie, nie „pusta”. Falsyfikatory:
    ogon awarii bez członu; pusta szuflada z pustostanem przy zachowanych wpisach."""
    path, pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con_a, a = _restart(path)
    con_b = None
    try:
        _makro_dodaj(a, "OBSERVER", "obs")
        con_b, b = _restart(path)
        try:
            _dokoncz_i_pada(monkeypatch)
            _gest_izolacji(b, "dokoncz", pliki[0][1], monkeypatch)
            assert b._run_id is None
            assert _obcy() in b.drawer.result.text()
            # Zwolnione `R` (2) i staging okna A, który B zapamiętało przy otwarciu jako odmówiony cudzą
            # blokadą (AR-323) - oba czekają na podjęcie przez B.
            assert b.drawer.label.text() == i18n.t_plural("grid.drawer.pending_ready", 2 + a._pending_count())
        finally:
            _zamknij_widok(b)
    finally:
        if con_b is not None:
            con_b.close()
        _zamknij_widok(a)
        con_a.close()


def test_izolacja_zamknieta_przy_podjetym_innym_przebiegu_mowi_ze_czeka(qapp, tmp_path, monkeypatch):
    """Przy otwarciu szuflada podejmuje zwykły przebieg `Z` i mówi, że obok czeka zatrzymany `R`; „Dokończ zapis”
    dla `R` BEZ odrzucania `Z` - szuflada zajęta, więc zdanie mówi, że zwolnione zmiany czekają. Falsyfikator:
    `R` niezapamiętany przy członie `isolated_more` (gest nie wie o `R`, informacja znika)."""
    from horreum import repo
    path, pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con = db.connect(path)
    lid, hh = con.execute("SELECT id, header_hash FROM location ORDER BY id LIMIT 1 OFFSET 2").fetchone()
    repo.stage_pending(con, run_id="Z", location_id=lid, keyword="TELESCOP", idx=0, op="set",
                       old_value=None, new_value="EQ6", new_type="str", new_comment=None, expected_header_hash=hh)
    con.close()
    con, v = _restart(path)
    try:
        assert v._run_id == "Z"
        assert i18n.t_plural("grid.drawer.isolated_more", 3) in v.drawer.result.text()
        _gest_izolacji(v, "dokoncz", pliki[0][1], monkeypatch)
        assert v._run_id == "Z"
        assert i18n.t_plural("grid.drawer.isolated_ready", 2) in v.drawer.result.text(), v.drawer.result.text()
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ AR-316 - szuflada mówi o każdym przebiegu


def _trzyma_blokade(v):
    return v._blokada_szuflady is not None and v._blokada_szuflady.isLocked()


def _karta_martwego_procesu(path, run_id, wiersz=0):
    """Przebieg `run_id` z jednym wpisem czekającym, zostawiony przez proces, którego już nie ma (drugie
    połączenie, bez okna)."""
    from horreum import repo
    con = db.connect(path)
    try:
        lid, hh = con.execute("SELECT id, header_hash FROM location ORDER BY id LIMIT 1 OFFSET ?",
                              (wiersz,)).fetchone()
        repo.stage_pending(con, run_id=run_id, location_id=lid, keyword="FILTER", idx=0, op="set",
                           old_value="Ha", new_value="OIII", new_type="str", new_comment=None,
                           expected_header_hash=hh)
    finally:
        con.close()


def test_ponowne_makro_do_zera_oddaje_blokade_drugie_okno_podejmuje(qapp, tmp_path):
    """Makro (3 zmiany), potem makro bez żadnej zmiany (same pominięcia) - przebieg wyczyszczony do zera
    zamyka się jak odrzucony: okno A nie trzyma blokady szuflady, a drugie okno podejmuje przebieg zostawiony
    przez martwy proces („Z poprzedniej sesji czeka 1 zmiana”). Falsyfikator: ponowne makro bez zamknięcia
    pustego przebiegu (A trzyma blokadę, B słyszy „szufladę prowadzi inne okno”)."""
    path, con, _p = _baza_szuflady(tmp_path, 3)
    a = _widok_szuflady(con, inline=True)
    con_b = b = None
    try:
        _makro_przyciskiem(a, "TELESCOP", "EQ6")
        assert a._pending_count() == 3 and _trzyma_blokade(a)
        _makro_przyciskiem(a, "EXPTIME", "abc")          # 3 pominięte - zero zmian
        assert a._run_id is None and not _trzyma_blokade(a)
        _karta_martwego_procesu(path, "Y")
        con_b = db.connect(path)
        b = _widok_szuflady(con_b, inline=True)
        assert b._run_id == "Y", b.drawer.result.text()
        assert b.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", 1)
    finally:
        if b is not None:
            _zamknij_widok(b)
        if con_b is not None:
            con_b.close()
        _zamknij_widok(a)
        con.close()


def test_ponowny_staging_nazw_do_zera_oddaje_blokade(qapp, tmp_path):
    """Staging nazw (3), potem staging wzorem, który nazw nie zmienia (token `orig`) - przebieg nazw
    wyczyszczony do zera zamyka się, blokada schodzi, a drugie okno przyjmuje swój staging makra.
    Falsyfikator: ponowny staging nazw bez zamknięcia pustego przebiegu."""
    path, con, _p = _baza_szuflady(tmp_path, 3)
    a = _widok_szuflady(con, inline=True)
    con_b = db.connect(path)
    b = None
    try:
        a._on_rename_stage(_POL)
        assert a._rename_pending_count() == 3 and _trzyma_blokade(a)
        a._on_rename_stage({**_POL, "template": [{"t": "orig", "re": ".*"}]})
        assert a._rename_run_id is None and not _trzyma_blokade(a)
        b = _widok_szuflady(con_b, inline=True)
        _makro_przyciskiem(b, "TELESCOP", "AZ-GTI")
        assert b._run_id is not None and b._pending_count() == 3
    finally:
        if b is not None:
            _zamknij_widok(b)
        con_b.close()
        _zamknij_widok(a)
        con.close()


def test_awaria_zapisu_po_rozstrzygnieciu_wszystkich_wpisow_oddaje_blokade(qapp, tmp_path, monkeypatch):
    """„Zatwierdź”, którego operacja zapisuje wszystkie trzy pliki, a potem rzuca (prawdziwy zapis, atrapa
    wyłącznie wyjątku): przebieg bez czekających wpisów zamyka się w ogonie awarii, blokada schodzi, drugie
    okno przyjmuje staging. Falsyfikator: ogon awarii bez zamknięcia pustego przebiegu."""
    from horreum.gui.wb_worker import WritebackWorker, _zapis_kart

    def _zapisz_i_pada(c, t, now, pr, sc):
        _zapis_kart(c, t, now, pr, sc)
        raise ValueError("złamany inwariant po zapisie")
    path, con, _p = _baza_szuflady(tmp_path, 3)
    a = _widok_szuflady(con, inline=True)
    con_b = db.connect(path)
    b = None
    try:
        _makro_przyciskiem(a, "TELESCOP", "EQ6")
        monkeypatch.setitem(WritebackWorker._OPS, "commit", _zapisz_i_pada)
        _klik_w(a.drawer.btn_commit)
        # Wynik częściowy (AR-344): pliki zapisane, potem błąd - nie samo „nie powiódł się”.
        assert a.drawer.result.text().startswith(i18n.t_plural(
            "grid.wb.partial_commit", 3, m=3, msg=i18n.t("objchg.item.prog_error"))), a.drawer.result.text()
        assert a._run_id is None and not _trzyma_blokade(a)
        b = _widok_szuflady(con_b, inline=True)
        _makro_przyciskiem(b, "TELESCOP", "AZ-GTI")
        assert b._pending_count() == 3
    finally:
        if b is not None:
            _zamknij_widok(b)
        con_b.close()
        _zamknij_widok(a)
        con.close()


def test_przerwane_nazwy_wyczyszczone_do_zera_zamykaja_sie_jak_odrzucone(qapp, tmp_path, monkeypatch):
    """Zmiana trzech nazw przerwana po pierwszym pliku, potem staging nazw bez żadnej zmiany: przebieg nazw
    (niezapisany) przy zerze czekających zamyka się jak po „Odrzuć” - wiersz `applied` przerwanego zapisu
    zostaje w bazie, szuflada oddaje blokadę, a nazwa pierwszego pliku dostaje „Cofnij” nazw (AR-345 - dawniej
    droga wyłącznie przez CLI `rename --undo`); klik przywraca pierwszy plik. Falsyfikatory: zamknięcie także
    przebiegu ZAPISANEGO (bez warunku `_rename_run_committed`) - czerwone zastane testy żywego „Cofnij” nazw;
    zamknięcie bez „Cofnij” zapisanych nazw."""
    from test_gui_pasek_szczegol import _anuluj_w_biegu, _brama_po_pierwszym_pliku, _czekaj
    path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    try:
        v._on_rename_stage(_POL)
        run = v._rename_run_id
        stary = v.model._preview
        brama, doszlo = _brama_po_pierwszym_pliku(monkeypatch)
        _klik_w(v.drawer.btn_commit)
        _anuluj_w_biegu(v, brama, doszlo, stary)
        assert v._rename_pending_count() == 2 and not pliki[0].exists()
        v._on_rename_stage({**_POL, "template": [{"t": "orig", "re": ".*"}]})
        assert v._rename_run_committed and v._undo_mode == "rename" and not _trzyma_blokade(v)
        assert [r["status"] for r in writeback.renames_for_run(con, run)] == ["applied"]
        _klik_w(v._undo_btn)
        _czekaj(lambda: not v._wb.is_busy and not v._zbior_w_drodze(), "cofnięcie nazw")
        assert pliki[0].exists()
    finally:
        _zamknij_widok(v)
        con.close()


def _nazwy_przerwane_smiercia(tmp_path, monkeypatch, n=3):
    """Staging `n` nazw w oknie, zamknięcie okna i zapis nazw drugim połączeniem przerwany ŚMIERCIĄ procesu
    po `os.rename` pierwszego pliku (prawdziwy pisarz, atrapa wyłącznie śmierci - wzór `test_rename.py`):
    pierwszy plik pod nową nazwą, baza pod starą, `n` wierszy czekających, pierwszy z otwartym zamiarem.
    Zwraca (ścieżka bazy, pliki, run_id) - połączenie zamknięte."""
    from horreum import repo
    from test_rename import _pad_raz
    path, con, pliki = _baza_szuflady(tmp_path, n)
    v = _widok_szuflady(con, inline=True)
    v._on_rename_stage(_POL)
    run = v._rename_run_id
    _zamknij_widok(v)
    with monkeypatch.context() as m:
        _pad_raz(m, repo, "_apply_relocation", KeyboardInterrupt())
        with pytest.raises(KeyboardInterrupt):
            writeback.commit_renames(con, run, now=NOW)
    con.close()
    return path, pliki, run


def _rekoncyliacja_obok(path):
    """Rekoncyliacja zamiarów nazw drugim połączeniem (Dostawa, CLI, inne okno)."""
    con2 = db.connect(path)
    try:
        return writeback.reconcile_renames(con2, now=NOW)
    finally:
        con2.close()


def _droga_nazw():
    return i18n.t("grid.drawer.names_held_way", receive=i18n.t("pipeline.receive"), nav=i18n.t("nav.dostawa"))


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_nazwy_przerwane_smiercia_mowia_ile_czeka_i_co_zwolni(qapp, tmp_path, monkeypatch, lang):
    """Restart po zapisie nazw przerwanym śmiercią programu: przebiegu z otwartym zamiarem szuflada nie
    podejmuje (dwa zapisy jednego przebiegu to wyścig), ale nie mówi „pusta” - etykieta liczy czekające zmiany
    nazw, wynik mówi, co rozstrzygnie zamiar; Zatwierdź/Odrzuć wygaszone, wiersze nietknięte. Falsyfikatory:
    zdanie szuflady bez gałęzi nazw (pustostan); zdanie bez drogi nazw."""
    path, _pliki, _run = _nazwy_przerwane_smiercia(tmp_path, monkeypatch)
    i18n.set_lang(lang)
    con, v = _restart(path)
    try:
        przed = [tuple(r) for r in con.execute("SELECT status, in_flight FROM pending_renames ORDER BY id")]
        assert v._rename_run_id is None and v._run_id is None
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_names_held", 3)
        assert v.drawer.result.text() == _droga_nazw()
        assert not v.drawer.btn_commit.isEnabled() and not v.drawer.btn_reject.isEnabled()
        assert [tuple(r) for r in con.execute(
            "SELECT status, in_flight FROM pending_renames ORDER BY id")] == przed
    finally:
        _zamknij_widok(v)
        con.close()


def test_rekoncyliacja_nazw_innym_polaczeniem_odswiezenie_podejmuje_i_cofnij_obejmuje_wszystkie(
        qapp, tmp_path, monkeypatch):
    """Zamiar rozstrzyga ktoś inny (rekoncyliacja drugim połączeniem), widok tylko odświeża szufladę: przebieg
    nazw zapamiętany jako zatrzymany jest już podejmowalny - „Z poprzedniej sesji czekają 2 zmiany nazw”, zapis
    przerwano; „Zatwierdź” kończy, a „Cofnij” przywraca WSZYSTKIE trzy nazwy (wiersz z rekoncyliacji należy do
    przebiegu). Falsyfikatory: podjęcie zwolnionych wyłącznie dla kart; pamięć przebiegów bez nazw."""
    from test_gui_pasek_szczegol import _czekaj
    path, pliki, run = _nazwy_przerwane_smiercia(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_names_held", 3)
        assert [f.status for f in _rekoncyliacja_obok(path)] == ["reconciled"]
        v.set_writeback_busy(True)                       # koniec cudzego zapisu - zwykłe odświeżenie
        v.set_writeback_busy(False)
        assert v._rename_run_id == run and v._rename_pending_count() == 2
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_rename_prev", 2)
        assert i18n.t("grid.drawer.prev_interrupted", commit=i18n.t("grid.action.commit")) in v.drawer.result.text()
        assert v.drawer.btn_commit.isVisible() and v.drawer.btn_commit.isEnabled()
        _klik_w(v.drawer.btn_commit)
        _czekaj(lambda: not v._wb.is_busy and not v._zbior_w_drodze(), "dokończenie nazw")
        assert not any(p.exists() for p in pliki)
        _klik_w(v._undo_btn)
        _czekaj(lambda: not v._wb.is_busy and not v._zbior_w_drodze(), "cofnięcie nazw")
        assert all(p.exists() for p in pliki), "nazwa z zapisu przerwanego śmiercią nie wróciła"
    finally:
        _zamknij_widok(v)
        con.close()


def test_zwolnione_nazwy_przy_zajetej_szufladzie_mowia_ze_czekaja(qapp, tmp_path, monkeypatch):
    """Szuflada zajęta przebiegiem `Z` podjętym przy otwarciu; obok czekają karty zatrzymane izolacją (`R`) i nazwy
    z otwartym zamiarem - zdanie przebiegu mówi o obu. Zamiar rozstrzyga drugie połączenie, a „Dokończ zapis”
    zwalnia `R`: szuflada niczego nie podejmuje, a wynik mówi, że czekają zwolnione karty I zwolnione nazwy -
    każde swoją liczbą. Falsyfikatory: człon nazw w locie zdjęty ze zdania przebiegu; człon `names_held_ready`
    zdjęty."""
    from horreum import repo, scan
    from test_rename import _pad_raz
    from test_gui_izolacja_zapisu import _fits
    path, pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con = db.connect(path)
    nazwy = []
    for i in (3, 4, 5):
        p = _fits(tmp_path / "arch" / f"n{i}.fits", seed=i)
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary(),
                           pochodzenie=repo.ZEWNETRZNE)
        lid, mtime = con.execute("SELECT id, mtime FROM location WHERE path = ?", (str(p),)).fetchone()
        repo.stage_rename(con, run_id="NF", location_id=lid, old_path=str(p),
                          new_path=str(tmp_path / "arch" / f"m{i}.fits"), expected_mtime=mtime)
        nazwy.append(p)
    with monkeypatch.context() as m:
        _pad_raz(m, repo, "_apply_relocation", KeyboardInterrupt())
        with pytest.raises(KeyboardInterrupt):
            writeback.commit_renames(con, "NF", now=NOW)
    lid, hh = con.execute("SELECT id, header_hash FROM location ORDER BY id LIMIT 1 OFFSET 2").fetchone()
    repo.stage_pending(con, run_id="Z", location_id=lid, keyword="TELESCOP", idx=0, op="set",
                       old_value=None, new_value="EQ6", new_type="str", new_comment=None, expected_header_hash=hh)
    con.close()
    con, v = _restart(path)
    try:
        assert v._run_id == "Z"
        assert i18n.t_plural("grid.drawer.names_held_more", 3) in v.drawer.result.text(), v.drawer.result.text()
        assert [f.status for f in _rekoncyliacja_obok(path)] == ["reconciled"]
        _gest_izolacji(v, "dokoncz", pliki[0][1], monkeypatch)
        wynik = v.drawer.result.text()
        assert v._run_id == "Z" and v._rename_run_id is None
        assert i18n.t_plural("grid.drawer.isolated_ready", 2) in wynik, wynik
        assert i18n.t_plural("grid.drawer.names_held_ready", 2) in wynik, wynik
    finally:
        _zamknij_widok(v)
        con.close()


def test_odczyt_nazw_szuflady_jeden_predykat_dwie_polowy(tmp_path):
    """Odczyt przebiegów nazw szuflady: przebieg zwykły w połowie do podjęcia, przebieg z otwartym zamiarem
    w połowie „w locie” (z liczbą wszystkich czekających wierszy), przebieg zmiany obiektu i wiersz przeniesienia
    zmiany obiektu w żadnej - także gdy tabela pozycji zmiany obiektu ma wiersz bez przeniesienia
    (`rename_id IS NULL`). Falsyfikator: `NOT IN` bez `IS NOT NULL` (NULL na liście gasi obie połowy)."""
    from horreum import repo
    path, con, _p = _baza_szuflady(tmp_path, 3)
    lok = [(r["id"], r["frame_id"], r["path"]) for r in con.execute(
        "SELECT id, frame_id, path FROM location ORDER BY id")]

    def _nazwa(run_id, i):
        repo.stage_rename(con, run_id=run_id, location_id=lok[i][0], old_path=lok[i][2],
                          new_path=lok[i][2] + f".{run_id}", expected_mtime=None)
        return con.execute("SELECT max(id) FROM pending_renames").fetchone()[0]
    _nazwa("OK", 0)
    _nazwa("NF", 1)
    _nazwa("NF", 2)
    przeniesienie = _nazwa("X", 0)
    with con:
        con.execute("UPDATE pending_renames SET in_flight = 'commit' "
                    "WHERE id = (SELECT min(id) FROM pending_renames WHERE run_id = 'NF')")
        con.execute("INSERT INTO object_change_run (run_id, mode, created_at) VALUES ('OC', 'align', ?)", (NOW,))
        con.execute("INSERT INTO pending_object_change (run_id, frame_id, location_id, old_path, object_change, "
                    "rename_id) VALUES ('OC', ?, ?, ?, 1, NULL)", (lok[1][1], lok[1][0], lok[1][2]))
        con.execute("INSERT INTO pending_object_change (run_id, frame_id, location_id, old_path, object_change, "
                    "rename_id) VALUES ('OC', ?, ?, ?, 0, ?)", (lok[0][1], lok[0][0], lok[0][2], przeniesienie))
    _nazwa("OC", 2)
    try:
        assert [(p["run_id"], p["klinga"], p["n"]) for p in queries.oczekujace_przebiegi_szuflady(con)] == [
            ("OK", "nazwy", 1)]
        assert queries.przebiegi_nazw_w_locie(con) == [{"run_id": "NF", "n": 2}]
    finally:
        con.close()


def test_klucze_nazw_zatrzymanych_odmieniaja_liczbe():
    """Odmiana kluczy zdań nazw zatrzymanych (1, 2, 5, 12, 22) w PL i EN; EN bez polskich znaków i bez „."""
    i18n.set_lang("pl")
    assert [i18n.t_plural("grid.drawer.pending_names_held", n).split(",")[0] for n in (1, 2, 5, 12, 22)] == [
        "1 zmiana nazwy czeka", "2 zmiany nazw czekają", "5 zmian nazw czeka", "12 zmian nazw czeka",
        "22 zmiany nazw czekają"]
    assert [i18n.t_plural("grid.drawer.names_held_ready", n).split(" - ")[0] for n in (1, 2, 5, 12, 22)] == [
        "1 zmiana nazwy zwolniona z zapisu nazw czeka", "2 zmiany nazw zwolnione z zapisu nazw czekają",
        "5 zmian nazw zwolnionych z zapisu nazw czeka", "12 zmian nazw zwolnionych z zapisu nazw czeka",
        "22 zmiany nazw zwolnione z zapisu nazw czekają"]
    assert i18n.t_plural("grid.drawer.names_held_more", 22) == "czekają też 22 zmiany nazw zatrzymane zapisem nazw"
    assert i18n.t_plural("grid.drawer.names_held_more", 5) == "czeka też 5 zmian nazw zatrzymanych zapisem nazw"
    assert i18n.t_plural("grid.drawer.names_held_more", 1) == "czeka też 1 zmiana nazwy zatrzymana zapisem nazw"
    i18n.set_lang("en")
    assert i18n.t_plural("grid.drawer.pending_names_held", 1) == "1 name change waits for a name write to be settled"
    assert i18n.t_plural("grid.drawer.pending_names_held", 2) == "2 name changes wait for a name write to be settled"
    for klucz in ("grid.drawer.pending_names_held", "grid.drawer.names_held_more", "grid.drawer.names_held_ready",
                  "grid.drawer.names_held_way", "grid.drawer.dot_held_tip"):
        for n in (1, 2):
            tekst = (i18n.t_plural(klucz, n) if klucz.endswith(("held", "more", "ready"))
                     else i18n.t(klucz, receive="R", nav="N"))
            assert not set(tekst) & set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ„"), tekst


def _kropka(v):
    return v.drawer.dot.text(), v.drawer.dot.property("role"), v.drawer.dot.toolTip()


@pytest.mark.parametrize("stan", ["izolacja", "nazwy", "cudza"])
def test_kropka_mowi_o_zmianach_czekajacych_poza_szuflada(qapp, tmp_path, monkeypatch, stan):
    """Przy zerze w tej szufladzie, a zmianach czekających POZA nią - zatrzymanych izolacją, nazwach z otwartym
    zamiarem, zwolnionych przy szufladzie prowadzonej przez inne okno - kropka nie mówi „○” (pusto), tylko
    „◌” w roli `warn` z podpowiedzią. Po podjęciu „●” bez podpowiedzi, po „Odrzuć” „○” bez podpowiedzi.
    Falsyfikatory: `set_count` bez stanu „czeka poza szufladą”; podpowiedź kropki niezdejmowana w innych
    stanach; gałąź zwolnionych niepodjętych bez kropki."""
    tip = i18n.t("grid.drawer.dot_held_tip")
    if stan == "nazwy":
        path, _pliki, _run = _nazwy_przerwane_smiercia(tmp_path, monkeypatch)
    else:
        path, pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con, v = _restart(path)
    con_a = a = None
    try:
        if stan == "cudza":
            con_a, a = _restart(path)
            _makro_dodaj(a, "OBSERVER", "obs")           # szufladę prowadzi okno A
            assert _trzyma_blokade(a)
            con2 = db.connect(path)
            try:
                op_id = con2.execute("SELECT id FROM inplace_op").fetchone()[0]
                writeback.finish_inplace(con2, op_id, now=NOW)
            finally:
                con2.close()
            v.set_writeback_busy(True)
            v.set_writeback_busy(False)
            assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_ready", 2)
        assert _kropka(v) == ("◌", "warn", tip)
        if stan == "cudza":
            return
        if stan == "izolacja":
            _gest_izolacji(v, "dokoncz", pliki[0][1], monkeypatch)
        else:
            _rekoncyliacja_obok(path)
            v.set_writeback_busy(True)
            v.set_writeback_busy(False)
        assert _kropka(v) == ("●", "warn", ""), v.drawer.label.text()
        _klik_w(v.drawer.btn_reject)
        assert _kropka(v) == ("○", "secondary", "")
    finally:
        if a is not None:
            _zamknij_widok(a)
            con_a.close()
        _zamknij_widok(v)
        con.close()


def test_kropka_przy_zatwierdzono_zostaje_pusta(qapp, tmp_path):
    """Stan „Zatwierdzono: N” przy żywym „Cofnij” - poczekalnia pusta, „Cofnij” działa na zapisanym: kropka
    „○” w roli `secondary`, bez podpowiedzi. Falsyfikator: kropka „czeka poza szufladą” przy etykiecie zapisu."""
    _path, con, _p = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con, inline=True)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _klik_w(v.drawer.btn_commit)
        assert v._undo_mode == "macro"
        assert _kropka(v) == ("○", "secondary", "")
    finally:
        _zamknij_widok(v)
        con.close()


def _zamknij_izolacje_obok(path):
    """„Dokończ zapis” operacji izolującej drugim połączeniem (CLI, drugie okno) - prawdziwy rdzeń."""
    con2 = db.connect(path)
    try:
        op_id = con2.execute("SELECT id FROM inplace_op").fetchone()[0]
        assert writeback.finish_inplace(con2, op_id, now=NOW).status == "applied"
    finally:
        con2.close()


def _aktywuj(okno):
    """Aktywacja okna jak powrót człowieka z innej aplikacji: drugie okno aktywne, potem to (offscreen
    doręcza `WindowActivate` widocznym dzieciom)."""
    from PySide6.QtWidgets import QWidget
    from test_gui_pasek_szczegol import _czekaj
    inne = QWidget()
    inne.resize(200, 100)
    inne.show()
    inne.activateWindow()
    _czekaj(lambda: QApplication.activeWindow() is inne, "drugie okno aktywne")
    okno.activateWindow()
    _czekaj(lambda: QApplication.activeWindow() is okno, "okno aktywne")
    inne.close()


def _okno_glowne(path, monkeypatch):
    from horreum.gui.app import MainWindow
    from test_gui_pasek_szczegol import _czekaj
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    win = MainWindow(path)
    win.resize(1400, 900)
    win.show()
    _czekaj(lambda: not win.grid_view._zbior_w_drodze(), "pierwszy zbiór")
    return win


def _klik_nav(win, wiersz):
    from PySide6.QtTest import QTest
    rect = win.nav.visualItemRect(win.nav.item(wiersz))
    QTest.mouseClick(win.nav.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    QApplication.processEvents()


def test_wejscie_w_zbiory_odswieza_pusta_szuflade_po_izolacji_zamknietej_innym_polaczeniem(qapp, tmp_path,
                                                                                          monkeypatch):
    """Szuflada mówi „3 zmiany czekają, aż rozstrzygniesz zapis w miejscu”; człowiek wychodzi na Dom, izolację
    zamyka drugie połączenie, a wejście w Zbiory klikiem sidebara odświeża pustą szufladę - przebieg podjęty,
    „Z poprzedniej sesji czekają 2 zmiany” z czynnym „Zatwierdź”, zamiast nieaktualnego „najpierw Dokończ
    zapis”. Falsyfikator: widok bez odświeżenia przy pokazaniu."""
    from horreum.gui.app import NAV_DOM, NAV_ZBIORY
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    win = _okno_glowne(path, monkeypatch)
    g = win.grid_view
    try:
        _klik_nav(win, NAV_ZBIORY)
        assert g.isVisible() and g.drawer.label.text() == i18n.t_plural("grid.drawer.pending_isolated", 3)
        _klik_nav(win, NAV_DOM)
        _zamknij_izolacje_obok(path)
        _klik_nav(win, NAV_ZBIORY)
        assert g._run_id == "R" and g.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", 2)
        assert g.drawer.btn_commit.isVisible() and g.drawer.btn_commit.isEnabled()
    finally:
        win.close()


def test_aktywacja_okna_odswieza_pusta_szuflade(qapp, tmp_path, monkeypatch):
    """Zbiory na ekranie, izolację zamyka drugie połączenie, człowiek wraca do okna (aktywacja) - pusta szuflada
    odświeża się i podejmuje przebieg. Falsyfikator: widok bez odświeżenia przy `WindowActivate`."""
    from horreum.gui.app import NAV_ZBIORY
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    win = _okno_glowne(path, monkeypatch)
    g = win.grid_view
    try:
        _klik_nav(win, NAV_ZBIORY)
        assert g.drawer.label.text() == i18n.t_plural("grid.drawer.pending_isolated", 3)
        _zamknij_izolacje_obok(path)
        _aktywuj(win)
        assert g._run_id == "R" and g.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", 2)
    finally:
        win.close()


def test_odswiezenie_pustej_szuflady_czeka_na_koniec_etapu_dostawy(qapp, tmp_path, monkeypatch):
    """PRAWDZIWY etap „Rozwiąż” z bramą; izolację zamyka drugie połączenie, a aktywacja okna w biegu etapu
    niczego nie podejmuje (Zatwierdź/Odrzuć zostają wygaszone - etap pisze do bazy). Koniec przebiegu odświeża
    pustą szufladę sam - przebieg podjęty bez kolejnej aktywacji. Falsyfikatory: odświeżenie bez strażnika
    etapu; koniec etapu bez odświeżenia pustej szuflady."""
    import threading
    from horreum import derive
    from horreum.gui.app import NAV_ZBIORY
    from test_gui_pasek_szczegol import _czekaj
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    puszczona = threading.Event()
    prawdziwy = derive.DERIVED["resolve"]

    def _czeka(con, now, cancel):
        puszczona.wait(30)
        return prawdziwy(con, now, cancel)
    monkeypatch.setitem(derive.DERIVED, "resolve", _czeka)
    win = _okno_glowne(path, monkeypatch)
    g = win.grid_view
    try:
        _klik_nav(win, NAV_ZBIORY)
        assert win.pipeline_view.run_stage("resolve") is None
        _czekaj(lambda: g._etap_w_biegu, "etap w biegu")
        _zamknij_izolacje_obok(path)
        _aktywuj(win)
        assert g._run_id is None and not g.drawer.btn_commit.isEnabled() and not g.drawer.btn_reject.isEnabled()
        puszczona.set()
        _czekaj(lambda: not g._etap_w_biegu and win.pipeline_view._thread is None, "koniec przebiegu")
        assert g._run_id == "R" and g.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", 2)
        assert g.drawer.btn_commit.isEnabled()
    finally:
        puszczona.set()
        win.close()


def test_aktywacja_przy_zywym_cofnij_nie_podejmuje(qapp, tmp_path, monkeypatch):
    """Żywe „Cofnij” zapisu tej sesji, izolację zamyka drugie połączenie, aktywacja okna: świeżego „Cofnij”
    nie zdejmujemy po cichu - etykieta „Zatwierdzono…” i przycisk zostają, przebieg nie podjęty. Falsyfikator:
    odświeżenie bez strażnika żywego „Cofnij” (etykieta zastąpiona zdaniem o zmianach czekających)."""
    from test_gui_pasek_szczegol import _czekaj
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        _makro_dodaj(v, "OBSERVER", "obs")
        _klik_w(v.drawer.btn_commit)
        _czekaj(lambda: not v._wb.is_busy and not v._zbior_w_drodze(), "zapis tej sesji")
        assert v._undo_mode == "macro"
        etykieta = v.drawer.label.text()
        _zamknij_izolacje_obok(path)
        _aktywuj(v)
        assert v._run_id is None and v._undo_mode == "macro" and v._undo_btn.isVisible()
        assert v.drawer.label.text() == etykieta
    finally:
        _zamknij_widok(v)
        con.close()


def test_aktywacja_w_biegu_gestu_izolacji_nie_pokazuje_zatwierdz(qapp, tmp_path, monkeypatch):
    """„Dokończ zapis” w wątku zapisu stoi na bramie PO zamknięciu operacji (przebieg w bazie już podejmowalny),
    a człowiek aktywuje okno: szuflada nie podejmuje przebiegu w biegu własnego gestu - pasek postępu zostaje,
    Zatwierdź/Odrzuć schowane. Po końcu gestu podejmuje go ogon. Falsyfikator: odświeżenie bez strażnika
    własnego zapisu w biegu."""
    import threading
    from test_gui_izolacja_zapisu import _zaznacz
    from test_gui_pasek_szczegol import _czekaj
    path, pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con, v = _restart(path)
    brama, doszlo = threading.Event(), threading.Event()
    prawdziwy = writeback.finish_inplace

    def _dokoncz_i_czekaj(c, op_id, *, now):
        wynik = prawdziwy(c, op_id, now=now)
        doszlo.set()
        brama.wait(30)
        return wynik
    monkeypatch.setattr(writeback, "finish_inplace", _dokoncz_i_czekaj)
    try:
        v.apply_perspective(grid_mod.PRESET_PENDING_FINISH)
        _czekaj(lambda: not v._zbior_w_drodze(), "perspektywa izolacji")
        _zaznacz(v, [pliki[0][1]])
        v._sync_menu_zapisu()
        v.act_finish_write.trigger()
        _czekaj(lambda: doszlo.is_set(), "operacja zamknięta w wątku")
        _aktywuj(v)
        assert v._wb.is_busy and v._run_id is None
        assert v.drawer.bar.isVisible() and not v.drawer.btn_commit.isVisible()
        brama.set()
        _czekaj(lambda: not v._wb.is_busy and not v._zbior_w_drodze(), "koniec gestu")
        assert v._run_id == "R"
    finally:
        brama.set()
        _zamknij_widok(v)
        con.close()


def test_aktywacja_w_biegu_skladu_zbioru_czeka_na_przylozenie(qapp, tmp_path, monkeypatch):
    """Skład zbioru w wątku tła stoi na bramie, izolację zamyka drugie połączenie, człowiek aktywuje okno:
    szuflada nie podejmuje przebiegu nad zbiorem, który zaraz zniknie (Zatwierdź/Odrzuć niewidoczne i wygaszone).
    Przyłożenie zbioru podejmuje odświeżenie odłożone. Falsyfikatory: odświeżenie bez strażnika zbioru
    w drodze; przyłożenie bez podjęcia odłożonego odświeżenia."""
    from test_gui_pola_w_tle import _brama_na_pivot
    from test_gui_pasek_szczegol import _czekaj
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con = db.connect(path)
    v = grid_mod.FramesView(con, now_fn=lambda: NOW, pola_poza_watkiem=True)
    v.resize(1400, 800)
    v.show()
    brama = None
    try:
        _czekaj(lambda: not v._zbior_w_drodze() and v._zbior_worker is None, "pierwszy zbiór")
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_isolated", 3)
        brama, wszedl = _brama_na_pivot(monkeypatch)
        v.refresh(w_tle=True)
        _czekaj(lambda: wszedl.is_set(), "skład w drodze")
        _zamknij_izolacje_obok(path)
        _aktywuj(v)
        assert v._zbior_w_drodze() and v._run_id is None
        assert not (v.drawer.btn_commit.isVisible() and v.drawer.btn_commit.isEnabled())
        brama.set()
        _czekaj(lambda: not v._zbior_w_drodze() and v._zbior_worker is None, "przyłożenie zbioru")
        assert v._run_id == "R" and v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", 2)
        assert v.drawer.btn_commit.isVisible() and v.drawer.btn_commit.isEnabled()
    finally:
        if brama is not None:
            brama.set()
        _zamknij_widok(v)
        con.close()


def test_blad_bazy_przy_odswiezeniu_pustej_szuflady_mowi_zdaniem_okno_zyje(qapp, tmp_path, monkeypatch):
    """Odczyt pustej szuflady w haczyku aktywacji pada błędem bazy (prawdziwy błąd SQLite z kodem - plik, który
    nie jest bazą): zdarzenie Qt wraca bez wyjątku, szuflada mówi zdaniem z powodem klasy bazy, a szczegół
    systemu stoi pod kursorem. Błąd programu (inna klasa) leci dalej. Falsyfikatory: haczyk bez obsługi błędu
    bazy (wyjątek z `event()`, brak zdania); obsługa łapiąca każdy wyjątek."""
    import sqlite3
    from PySide6.QtCore import QEvent
    zly = tmp_path / "zly.db"
    zly.write_bytes(b"to nie jest baza" * 64)
    try:
        sqlite3.connect(str(zly)).execute("SELECT 1 FROM sqlite_master").fetchall()
    except sqlite3.DatabaseError as e:
        blad = e
    _path, con, _p = _baza_szuflady(tmp_path, 1)
    v = _widok_szuflady(con, inline=True)
    try:
        monkeypatch.setattr(queries, "przebiegi_szuflady_izolowane", lambda c: (_ for _ in ()).throw(blad))
        QApplication.sendEvent(v, QEvent(QEvent.WindowActivate))
        zdanie = i18n.t("grid.wb.error", msg=i18n.t("objchg.item.db_damaged", db_code="SQLITE_NOTADB"))
        assert v.drawer.result.text() == zdanie
        assert v.drawer.result.szczegol(), "szczegół systemu pod kursorem"
        monkeypatch.setattr(queries, "przebiegi_szuflady_izolowane",
                            lambda c: (_ for _ in ()).throw(sqlite3.ProgrammingError("zamknięte połączenie")))
        with pytest.raises(sqlite3.ProgrammingError):
            v._odswiez_pusta_szuflade()
    finally:
        _zamknij_widok(v)
        con.close()


def _blad_notadb(tmp_path):
    """Prawdziwy błąd SQLite z kodem (NOTADB): plik, który nie jest bazą."""
    import sqlite3
    zly = tmp_path / "zly.db"
    zly.write_bytes(b"to nie jest baza" * 64)
    try:
        sqlite3.connect(str(zly)).execute("SELECT 1 FROM sqlite_master").fetchall()
    except sqlite3.DatabaseError as e:
        return e
    raise AssertionError("plik śmieci otworzył się jako baza")


def test_aktywacja_przy_przebiegu_tej_szuflady_nie_rusza_go(qapp, tmp_path):
    """Szuflada niesie przebieg tej sesji (makro, 3 zmiany), człowiek aktywuje okno: etykieta i czynne
    „Zatwierdź” zostają - odświeżenie pustej szuflady nie dotyka szuflady, która nie jest pusta.
    Falsyfikator: odświeżenie bez strażnika przebiegu tej szuflady (etykieta pustostanu, Zatwierdź wygaszone)."""
    _path, con, _p = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con, inline=True)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _aktywuj(v)
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending", 3)
        assert v.drawer.btn_commit.isVisible() and v.drawer.btn_commit.isEnabled()
    finally:
        _zamknij_widok(v)
        con.close()


def test_aktywacja_przy_cudzym_zapisie_czeka_na_jego_koniec(qapp, tmp_path, monkeypatch):
    """Cudzy zapis plików w biegu (okno naprawy), izolację zamyka drugie połączenie, aktywacja okna: szuflada nie
    podejmuje przebiegu obok cudzego zapisu (Zatwierdź wygaszone); koniec cudzego zapisu podejmuje go sam.
    Falsyfikator: odświeżenie bez strażnika cudzego zapisu."""
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        v.set_writeback_busy(True)
        _zamknij_izolacje_obok(path)
        _aktywuj(v)
        assert v._run_id is None and not v.drawer.btn_commit.isEnabled()
        v.set_writeback_busy(False)
        assert v._run_id == "R" and v.drawer.btn_commit.isEnabled()
    finally:
        _zamknij_widok(v)
        con.close()


def test_widok_zatrzymany_nie_podejmuje_przy_zdarzeniu(qapp, tmp_path, monkeypatch):
    """Widok zatrzymany (zamykany - `zatrzymaj_pola`) dostaje jeszcze zdarzenie aktywacji: niczego nie podejmuje
    i nie bierze blokady szuflady, którą za chwilę ma oddać. Falsyfikator: odświeżenie bez strażnika widoku
    zatrzymanego."""
    from PySide6.QtCore import QEvent
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        _zamknij_izolacje_obok(path)
        v.zatrzymaj_pola()
        QApplication.sendEvent(v, QEvent(QEvent.WindowActivate))
        assert v._run_id is None and not _trzyma_blokade(v)
    finally:
        _zamknij_widok(v)
        con.close()


def test_okno_zmiany_obiektu_zwalnia_nazwy_zamkniecie_odswieza_szuflade(qapp, tmp_path, monkeypatch):
    """PRAWDZIWE okno zmiany obiektu (wejście z przerwanego przebiegu, „Dokończ” prawdziwym klikiem, zapis inline):
    zapis zmiany obiektu rekoncyliuje zamiary nazw, więc przebieg nazw przerwany śmiercią procesu staje się
    podejmowalny. Aktywacja okna Zbiorów przy otwartym oknie zmiany obiektu niczego nie podejmuje; zamknięcie okna
    odświeża pustą szufladę - przebieg nazw podjęty. Falsyfikatory: odświeżenie bez strażnika okna zmiany
    obiektu; zamknięcie okna bez odświeżenia."""
    from PySide6.QtCore import QEvent, QTimer
    from PySide6.QtTest import QTest
    from horreum import repo
    from test_object_change_write import _Scena, _fits as _fits_oc, _wczytaj
    from test_rename import _pad_raz
    s = _Scena(tmp_path)
    s.stage(s.plan("R1"))
    con = s.con
    for i in range(3):
        p = _fits_oc(tmp_path / "inne" / f"n{i}.fits", seed=20 + i)
        _wczytaj(con, p)
        lid, mtime = con.execute("SELECT id, mtime FROM location WHERE path = ?", (str(p),)).fetchone()
        repo.stage_rename(con, run_id="NF", location_id=lid, old_path=str(p),
                          new_path=str(tmp_path / "inne" / f"m{i}.fits"), expected_mtime=mtime)
    with monkeypatch.context() as m:
        _pad_raz(m, repo, "_apply_relocation", KeyboardInterrupt())
        with pytest.raises(KeyboardInterrupt):
            writeback.commit_renames(con, "NF", now=NOW)
    con.close()
    con = db.connect(str(tmp_path / "h.db"))
    v = _widok_szuflady(con, inline=True)
    w_oknie = []

    def _scenariusz():
        dlg = v._okno_zmiany_obiektu
        try:
            QTest.mouseClick(dlg.action_btn, Qt.LeftButton)
            QApplication.processEvents()
            w_oknie.append(con.execute("SELECT count(*) FROM pending_renames WHERE in_flight IS NOT NULL"
                                       ).fetchone()[0])
            QApplication.sendEvent(v, QEvent(QEvent.WindowActivate))
            w_oknie.append(v._rename_run_id)
        finally:
            dlg.reject()
    try:
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_names_held", 3)
        QTimer.singleShot(0, _scenariusz)
        v.otworz_przebieg_zmiany_obiektu("R1")
        assert w_oknie == [0, None], w_oknie
        assert v._rename_run_id == "NF" and v._rename_pending_count() == 2
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_rename_prev", 2)
    finally:
        _zamknij_widok(v)
        con.close()


def test_druga_porazka_skladu_podejmuje_odlozone_odswiezenie(qapp, tmp_path, monkeypatch):
    """Aktywacja okna w biegu składu w tle odkłada odświeżenie pustej szuflady; skład pada dwa razy (pierwsza
    porażka i ponowienie) - zbiór nie przykłada się, ale stan „w drodze” schodzi i odświeżenie odłożone
    podejmuje przebieg. Falsyfikator: odłożone odświeżenie konsumowane wyłącznie przy przyłożeniu zbioru."""
    import sqlite3
    import threading
    from test_gui_pasek_szczegol import _czekaj
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con = db.connect(path)
    v = grid_mod.FramesView(con, now_fn=lambda: NOW, pola_poza_watkiem=True)
    v.resize(1400, 800)
    v.show()
    brama, wszedl = threading.Event(), threading.Event()
    porazki = []
    try:
        _czekaj(lambda: not v._zbior_w_drodze() and v._zbior_worker is None, "pierwszy zbiór")
        glowny = threading.get_ident()
        prawdziwe = queries.cards_pivot

        def _cp(c, ids, kws):
            if threading.get_ident() == glowny:
                return prawdziwe(c, ids, kws)
            wszedl.set()
            brama.wait(30)
            porazki.append(1)
            raise sqlite3.OperationalError("awaria składu w tle")
        monkeypatch.setattr(queries, "cards_pivot", _cp)
        v.refresh(w_tle=True)
        _czekaj(lambda: wszedl.is_set(), "skład w drodze")
        _zamknij_izolacje_obok(path)
        _aktywuj(v)
        assert v._run_id is None
        brama.set()
        _czekaj(lambda: len(porazki) == 2 and not v._zbior_w_drodze() and v._zbior_worker is None,
                "druga porażka składu")
        assert v._run_id == "R" and v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", 2)
    finally:
        brama.set()
        _zamknij_widok(v)
        con.close()


def test_zdanie_bledu_odczytu_schodzi_przy_udanym_odswiezeniu(qapp, tmp_path, monkeypatch):
    """Odczyt pustej szuflady pada błędem bazy (zdanie w szufladzie), następne odświeżenie się udaje - zdanie
    błędu schodzi, pustostan bez zdania. Falsyfikator: zdanie błędu niezapamiętane jako zdanie odświeżenia
    (stoi do następnego gestu)."""
    from PySide6.QtCore import QEvent
    blad = _blad_notadb(tmp_path)
    _path, con, _p = _baza_szuflady(tmp_path, 1)
    v = _widok_szuflady(con, inline=True)
    try:
        prawdziwy = queries.przebiegi_szuflady_izolowane
        monkeypatch.setattr(queries, "przebiegi_szuflady_izolowane", lambda c: (_ for _ in ()).throw(blad))
        QApplication.sendEvent(v, QEvent(QEvent.WindowActivate))
        assert v.drawer.result.text().startswith(i18n.t("grid.wb.error", msg="")[:4])
        monkeypatch.setattr(queries, "przebiegi_szuflady_izolowane", prawdziwy)
        QApplication.sendEvent(v, QEvent(QEvent.WindowActivate))
        assert v.drawer.result.text() == "" and v.drawer.label.text() == i18n.t("grid.drawer.empty")
    finally:
        _zamknij_widok(v)
        con.close()


def test_zdanie_cudzej_blokady_schodzi_gdy_juz_nic_nie_czeka(qapp, tmp_path, monkeypatch):
    """Okno B mówi „szufladę prowadzi inne okno” przy zmianach zwolnionych (gałąź cudzej blokady); okno A
    podejmuje je i zapisuje. Następne odświeżenie B: nic już nie czeka - zdanie cudzej blokady schodzi razem
    z etykietą. Falsyfikator: zdanie gałęzi cudzej blokady niezapamiętane jako zdanie odświeżenia."""
    from test_gui_pasek_szczegol import _czekaj
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con_a, a = _restart(path)
    con_b = b = None
    try:
        _makro_dodaj(a, "OBSERVER", "obs")               # A prowadzi szufladę
        con_b, b = _restart(path)
        _zamknij_izolacje_obok(path)
        b.set_writeback_busy(True)
        b.set_writeback_busy(False)
        assert b.drawer.result.text() == _obcy()
        _klik_w(a.drawer.btn_reject)                     # A odrzuca swój staging i podejmuje zwolnione
        a.set_writeback_busy(True)
        a.set_writeback_busy(False)
        assert a._run_id == "R"
        _klik_w(a.drawer.btn_commit)
        _czekaj(lambda: not a._wb.is_busy and not a._zbior_w_drodze(), "zapis w oknie A")
        b.set_writeback_busy(True)
        b.set_writeback_busy(False)
        assert b.drawer.result.text() == "" and b.drawer.label.text() == i18n.t("grid.drawer.empty")
    finally:
        if b is not None:
            _zamknij_widok(b)
            con_b.close()
        _zamknij_widok(a)
        con_a.close()


def test_aktywacja_przy_otwartym_edytorze_odklada_podjecie_do_zamkniecia(qapp, tmp_path, monkeypatch):
    """Przebieg nazw zwolniony rekoncyliacją drugiego połączenia, a w tabeli otwarty edytor komórki: aktywacja
    okna nie podejmuje przebiegu (podgląd przeładowany pod edytorem), zamknięcie edytora (Escape) - podejmuje.
    Falsyfikatory: odświeżenie bez odłożenia przy edytorze; zamknięcie edytora bez podjęcia odłożonego."""
    from PySide6.QtCore import QEvent
    from PySide6.QtTest import QTest
    from test_gui_drogi_reki import _otworz_edytor
    from test_gui_pasek_szczegol import _czekaj
    path, _pliki, run = _nazwy_przerwane_smiercia(tmp_path, monkeypatch)
    con = db.connect(path)
    v = _widok_szuflady(con, inline=True)
    try:
        _rekoncyliacja_obok(path)
        idx, ed, _inny = _otworz_edytor(qapp, v, "TELESCOP")
        QApplication.sendEvent(v, QEvent(QEvent.WindowActivate))
        assert v.table.indexWidget(idx) is ed and v._rename_run_id is None
        QTest.keyClick(ed.wartosc, Qt.Key_Escape)
        _czekaj(lambda: v._rename_run_id is not None, "podjęcie po zamknięciu edytora")
        assert v._rename_run_id == run and v._rename_pending_count() == 2
    finally:
        _zamknij_widok(v)
        con.close()


def test_dokoncz_zapis_rozstrzygajacy_ostatni_wpis_wlasnego_przebiegu_oddaje_blokade(qapp, tmp_path, monkeypatch):
    """Zapis w miejscu WŁASNEGO przebiegu (jedna karta), którego re-sync pada, a związany wpis zostaje czekający
    (atrapa stanu pisarza: status związanego wpisu, jak przy śmierci procesu - `_zatrzymany_izolacja`; pisarz
    dziennika połyka wyjątek zapisu fazy i rozstrzyga wpis jako `failed`, więc sama atrapa wyjątku tego stanu
    nie daje; reszta prawdziwa): przebieg trzyma blokadę. „Dokończ zapis” (prawdziwy gest) rozstrzyga ten ostatni
    wpis - przebieg przy zerze zamyka się, blokada schodzi, drugie okno przyjmuje staging. Falsyfikator: ogon gestu
    izolacji bez zamknięcia pustego przebiegu."""
    from test_gui_izolacja_zapisu import _baza, _fazy
    from horreum.gui.wb_worker import WritebackWorker, _zapis_kart
    con, pliki = _baza(tmp_path, n=1, do_zapisu=())
    v = _widok_szuflady(con, inline=True)
    con_b = db.connect(str(tmp_path / "h.db"))
    b = None
    try:
        _makro_dodaj(v, "OBSERVER", "obs")
        prawdziwy = writeback.scan.scan_file

        def _resync_pada_wpis_czeka(c, t, now, pr, sc):
            writeback.scan.scan_file = lambda p, **kw: (_ for _ in ()).throw(OSError(64, "zerwany udział"))
            try:
                wynik = _zapis_kart(c, t, now, pr, sc)
            finally:
                writeback.scan.scan_file = prawdziwy
            with c:
                c.execute("UPDATE pending_changes SET status = 'pending' WHERE inplace_op_id IS NOT NULL")
            return wynik
        monkeypatch.setitem(WritebackWorker._OPS, "commit", _resync_pada_wpis_czeka)
        _klik_w(v.drawer.btn_commit)
        monkeypatch.setitem(WritebackWorker._OPS, "commit", _zapis_kart)
        assert _fazy(con) == ["written"] and v._pending_count() == 1 and _trzyma_blokade(v), _statusy(con)
        _gest_izolacji(v, "dokoncz", pliki[0][1], monkeypatch)
        assert v._run_id is None and not _trzyma_blokade(v)
        b = _widok_szuflady(con_b, inline=True)
        _makro_dodaj(b, "FILTER", "Ha")
        assert b._pending_count() == 1, b.drawer.result.text()
    finally:
        if b is not None:
            _zamknij_widok(b)
        con_b.close()
        _zamknij_widok(v)
        con.close()


# ============================================================ AR-323 - zdania szuflady: odmowa, podjęcie, ślad, blokada


def _blokada_obca(path):
    """Blokada szuflady trzymana przez „inny proces” - drugi `QLockFile` na tym samym pliku (wzór wyłączności
    szuflady, `FramesView._wez_szuflade`). Wołający zwalnia ją `unlock()`."""
    from PySide6.QtCore import QLockFile
    blokada = QLockFile(path + ".szuflada.lock")
    blokada.setStaleLockTime(0)
    assert blokada.tryLock(0)
    return blokada


def _nazwy_czekaja(path, run_id="R3"):
    """Przebieg nazw `run_id` z trzema wierszami czekającymi (staging porzucony bez zapisu) - połączenie
    zamknięte."""
    from horreum import repo
    con = db.connect(path)
    try:
        for lid, p, mt in con.execute("SELECT id, path, mtime FROM location ORDER BY id").fetchall():
            repo.stage_rename(con, run_id=run_id, location_id=lid, old_path=p, new_path=p + ".x",
                              expected_mtime=mt)
    finally:
        con.close()


def _aktywacja(v):
    from PySide6.QtCore import QEvent
    QApplication.sendEvent(v, QEvent(QEvent.WindowActivate))
    QApplication.processEvents()


def _akcje(v):
    d = v.drawer
    return (d.btn_commit.isVisible(), d.btn_commit.isEnabled(), d.btn_reject.isVisible(), d.btn_reject.isEnabled())


@pytest.mark.parametrize("stan", ["nazwy", "cudza"])
def test_stan_czwarty_chowa_zatwierdz_i_odrzuc(qapp, tmp_path, monkeypatch, stan):
    """Kropka „◌” (zmiany czekają poza tą szufladą - nazwy z otwartym zamiarem albo przebieg przy cudzej
    blokadzie): Zatwierdź i Odrzuć niewidoczne, bo nie mają tu nic do zrobienia, a gest mówi zdanie obok
    (dawniej stały wygaszone - sonda natywna). Po podjęciu widoczne i czynne, po „Odrzuć” pustostan „○”
    z widocznymi wygaszonymi. Falsyfikator: `_pusta` bez chowania akcji w gałęziach „◌”."""
    blokada = None
    if stan == "nazwy":
        path, _pliki, _run = _nazwy_przerwane_smiercia(tmp_path, monkeypatch)
    else:
        path, con, _p = _baza_szuflady(tmp_path, 3)
        con.close()
        _nazwy_czekaja(path)
        blokada = _blokada_obca(path)
    con, v = _restart(path)
    try:
        assert _kropka(v)[0] == "◌"
        assert _akcje(v) == (False, False, False, False)
        if stan == "nazwy":
            _rekoncyliacja_obok(path)
        else:
            blokada.unlock()
        v.set_writeback_busy(True)
        v.set_writeback_busy(False)
        assert _kropka(v)[0] == "●" and _akcje(v) == (True, True, True, True)
        _klik_w(v.drawer.btn_reject)
        if stan == "nazwy":
            # Pierwszy plik przemianowany przed śmiercią procesu (wiersz `applied` po rekoncyliacji): „Odrzuć”
            # stawia „Cofnij” nazw (AR-345) - jedyną akcją jest ono, Zatwierdź/Odrzuć schowane.
            assert _kropka(v)[0] == "○" and _akcje(v) == (False, False, False, False) and v._undo_btn.isVisible()
        else:
            assert _kropka(v)[0] == "○" and _akcje(v) == (True, False, True, False)
    finally:
        if blokada is not None and blokada.isLocked():
            blokada.unlock()
        _zamknij_widok(v)
        con.close()


def test_cudza_blokada_przy_otwarciu_mowi_ile_czeka_i_podejmuje_po_zwolnieniu(qapp, tmp_path):
    """Przebieg nazw czeka, a szufladę bazy trzyma inny proces: otwarte okno nie mówi „pusta”, tylko „3 zmiany
    czekają na podjęcie” z kropką „◌” i zdaniem, kto prowadzi szufladę (z PID); aktywacja przy dalej cudzej
    blokadzie tego nie zdejmuje. Blokada zwolniona, aktywacja - przebieg podjęty w tej sesji (dawniej dopiero
    przy następnym otwarciu bazy, a zdanie o innym oknie trwało). Falsyfikatory: przebieg odmówiony blokadą
    niezapamiętany (pustostan, brak podjęcia); `set_result` zamiast `_pusta` (kropka „○”)."""
    path, con, _p = _baza_szuflady(tmp_path, 3)
    con.close()
    _nazwy_czekaja(path)
    blokada = _blokada_obca(path)
    con, v = _restart(path)
    try:
        oczek = (i18n.t_plural("grid.drawer.pending_ready", 3), _obcy())
        assert v._rename_run_id is None
        assert (v.drawer.label.text(), v.drawer.result.text()) == oczek
        assert _kropka(v) == ("◌", "warn", i18n.t("grid.drawer.dot_held_tip"))
        _aktywacja(v)
        assert (v.drawer.label.text(), v.drawer.result.text()) == oczek and v._rename_run_id is None
        blokada.unlock()
        _aktywacja(v)
        assert v._rename_run_id == "R3" and v._rename_pending_count() == 3
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_rename_prev", 3)
        assert _obcy() not in v.drawer.result.text()
    finally:
        if blokada.isLocked():
            blokada.unlock()
        _zamknij_widok(v)
        con.close()


def test_zdanie_cudzej_blokady_bez_pid_ma_wlasny_wariant(qapp, tmp_path, monkeypatch):
    """Plik blokady bez czytelnego PID (`getLockInfo` puste): zdanie bez numeru procesu zamiast „PID None”.
    Falsyfikator: `foreign_owner` z `pid=None`."""
    from PySide6.QtCore import QLockFile
    path, con, _p = _baza_szuflady(tmp_path, 3)
    con.close()
    _nazwy_czekaja(path)
    blokada = _blokada_obca(path)
    monkeypatch.setattr(QLockFile, "getLockInfo", lambda self: ())
    con, v = _restart(path)
    try:
        assert v.drawer.result.text() == i18n.t("grid.drawer.foreign_owner_nopid")
    finally:
        blokada.unlock()
        _zamknij_widok(v)
        con.close()


def _droga_dokonczenia():
    return i18n.t("grid.drawer.isolated_finish", finish=i18n.t("grid.inplace.finish"), nav=i18n.t("nav.porzadki"),
                  row=i18n.t("tasks.pending_finish_frames"))


def test_cudza_blokada_nie_przeslania_przebiegu_zatrzymanego_izolacja(qapp, tmp_path, monkeypatch):
    """Przy otwarciu czekają: przebieg `R` zatrzymany izolacją (3 zmiany, zapis czeka na dokończenie) i zwykły
    `Z` (1 zmiana), a szufladę bazy trzyma inny proces. PRZED zwolnieniem izolacji: etykieta mówi zwykły
    przebieg („1 zmiana czeka na podjęcie”), a zdanie - kto prowadzi szufladę ORAZ etykietę i drogę `R`
    (dawniej zdanie zwolnionych wracało przed zdaniem wyłączonych i `R` znikał z ekranu; kropka „◌” zostawała).
    Odświeżenie przy dalej cudzej blokadzie zdania nie zmienia. Izolację zamyka drugie połączenie: `R` liczy
    się do czekających na podjęcie, zdanie izolacji schodzi. Blokada wolna - szuflada podejmuje najnowszy
    zapamiętany (`Z`). Falsyfikator: gałąź cudzej blokady w `_pusta` bez etykiety i drogi
    `_zdanie_wylaczonych`."""
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    _karta_martwego_procesu(path, "Z", wiersz=1)
    blokada = _blokada_obca(path)
    con, v = _restart(path)
    try:
        oczek = (i18n.t_plural("grid.drawer.pending_ready", 1),
                 " · ".join((_obcy(), i18n.t_plural("grid.drawer.pending_isolated", 3), _droga_dokonczenia())))
        assert v._run_id is None
        assert (v.drawer.label.text(), v.drawer.result.text()) == oczek
        assert _kropka(v)[0] == "◌" and _akcje(v)[0] is False
        _aktywacja(v)
        assert (v.drawer.label.text(), v.drawer.result.text()) == oczek and v._run_id is None
        _zamknij_izolacje_obok(path)
        _aktywacja(v)
        assert v._run_id is None
        assert (v.drawer.label.text(), v.drawer.result.text()) == (
            i18n.t_plural("grid.drawer.pending_ready", 1 + 2), _obcy())
        blokada.unlock()
        _aktywacja(v)
        assert v._run_id == "Z" and v._pending_count() == 1
    finally:
        if blokada.isLocked():
            blokada.unlock()
        _zamknij_widok(v)
        con.close()


def test_cudza_blokada_zapamietuje_najnowszy_zwykly_przebieg_starsze_wracaja_przy_otwarciu(qapp, tmp_path,
                                                                                         monkeypatch):
    """Reguła AR-280 pod cudzą blokadą: czekają dwa zwykłe przebiegi (`STARY`, `NOWY`) i `R` zatrzymany
    izolacją. Okno zapamiętuje do podjęcia WYŁĄCZNIE najnowszy zwykły (`NOWY`) i zatrzymany `R`. Blokada
    wolna - podejmuje `NOWY`; po „Odrzuć” nic (`R` dalej zatrzymany, `STARY` niezapamiętany - szuflada mówi
    o `R`); izolację zamyka drugie połączenie - podejmuje `R`, nie `STARY`. `STARY` podejmuje dopiero następne
    otwarcie bazy. Falsyfikatory: zapamiętanie wszystkich zwykłych przebiegów (podjęcie `STARY` po „Odrzuć”
    albo zamiast `R`); zapamiętanie najstarszego (podjęcie `STARY` przed `NOWY`)."""
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    _karta_martwego_procesu(path, "STARY", wiersz=1)
    _karta_martwego_procesu(path, "NOWY", wiersz=2)
    blokada = _blokada_obca(path)
    con, v = _restart(path)
    try:
        assert v._wylaczone_znane == {"NOWY", "R"}
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_ready", 1)
        blokada.unlock()
        _aktywacja(v)
        assert v._run_id == "NOWY" and v._wylaczone_znane == {"R"}
        _klik_w(v.drawer.btn_reject)
        assert v._run_id is None and v._wylaczone_znane == {"R"}
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_isolated", 3)
        _zamknij_izolacje_obok(path)
        _aktywacja(v)
        assert v._run_id == "R" and v._pending_count() == 2
    finally:
        if blokada.isLocked():
            blokada.unlock()
        _zamknij_widok(v)
        con.close()
    con, v = _restart(path)
    try:
        assert v._run_id == "STARY" and v._pending_count() == 1
    finally:
        _zamknij_widok(v)
        con.close()


def test_podjecie_bez_gestu_mowi_na_pasku_i_w_szufladzie(qapp, tmp_path, monkeypatch):
    """Zamiar nazw rozstrzyga drugie połączenie, okno tylko się aktywuje: szuflada podejmuje przebieg i mówi
    to zdaniem (liczba wpisów PODJĘTEGO przebiegu) w polu wyniku i na pasku - dawniej kolumna podglądu zmieniała
    się bez słowa (sonda natywna: zero emisji, wynik pusty). Falsyfikator: podjęcie bez zdania."""
    path, _pliki, run = _nazwy_przerwane_smiercia(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        zdania = []
        v.status_message.connect(zdania.append)
        _rekoncyliacja_obok(path)
        _aktywacja(v)
        zdanie = i18n.t_plural("grid.drawer.picked_up_names", 2)
        assert v._rename_run_id == run
        assert zdania == [zdanie], zdania
        assert v.drawer.result.text().startswith(zdanie + " · "), v.drawer.result.text()
    finally:
        _zamknij_widok(v)
        con.close()


def test_podjecie_przy_schowanych_zbiorach_nie_mowi_na_pasku(qapp, tmp_path, monkeypatch):
    """To samo podjęcie, gdy widok jest schowany (odświeżenie z końca cudzego zapisu albo etapu Dostawy, człowiek
    jest gdzie indziej): zdanie stoi w szufladzie, a pasek gospodarza zostaje raportowi miejsca, w którym
    człowiek jest. Falsyfikator: emisja bez warunku widoczności."""
    path, _pliki, run = _nazwy_przerwane_smiercia(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        zdania = []
        v.status_message.connect(zdania.append)
        v.hide()
        _rekoncyliacja_obok(path)
        v.set_writeback_busy(True)
        v.set_writeback_busy(False)
        assert v._rename_run_id == run and zdania == []
        assert v.drawer.result.text().startswith(i18n.t_plural("grid.drawer.picked_up_names", 2))
    finally:
        _zamknij_widok(v)
        con.close()


@pytest.mark.parametrize("gdzie", ["stos_schowany", "okno_zminimalizowane", "zbiory_widoczne"])
def test_podjecie_po_etapie_dostawy_mowi_na_pasku_tylko_przy_zbiorach_na_ekranie(qapp, tmp_path, monkeypatch,
                                                                                 gdzie):
    """PRAWDZIWY etap „Rozwiąż” z bramą; w jego biegu izolację zamyka drugie połączenie, a koniec etapu odświeża
    pustą szufladę i podejmuje przebieg. Zdanie podjęcia stoi w szufladzie zawsze, a na pasek gospodarza idzie
    wyłącznie przy Zbiorach na ekranie - ani przy innej stronie stosu, ani przy oknie zminimalizowanym (dziecko
    zminimalizowanego okna Qt liczy jako widoczne): tam pasek należy do raportu etapu. Falsyfikator: warunek
    emisji na samym `isVisible()` (pada wariant okna zminimalizowanego)."""
    import threading
    from horreum import derive
    from horreum.gui.app import NAV_DOM, NAV_ZBIORY
    from test_gui_pasek_szczegol import _czekaj
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    puszczona = threading.Event()
    prawdziwy = derive.DERIVED["resolve"]

    def _czeka(con, now, cancel):
        puszczona.wait(30)
        return prawdziwy(con, now, cancel)
    monkeypatch.setitem(derive.DERIVED, "resolve", _czeka)
    win = _okno_glowne(path, monkeypatch)
    g = win.grid_view
    try:
        _klik_nav(win, NAV_ZBIORY)
        assert g.drawer.label.text() == i18n.t_plural("grid.drawer.pending_isolated", 3)
        zdania = []
        g.status_message.connect(zdania.append)
        if gdzie == "stos_schowany":
            _klik_nav(win, NAV_DOM)
        elif gdzie == "okno_zminimalizowane":
            win.showMinimized()
            _czekaj(lambda: win.isMinimized(), "okno zminimalizowane")
        assert win.pipeline_view.run_stage("resolve") is None
        _czekaj(lambda: g._etap_w_biegu, "etap w biegu")
        _zamknij_izolacje_obok(path)
        puszczona.set()
        _czekaj(lambda: not g._etap_w_biegu and win.pipeline_view._thread is None, "koniec przebiegu")
        zdanie = i18n.t_plural("grid.drawer.picked_up", 2)
        assert g._run_id == "R" and g.drawer.result.text().startswith(zdanie), g.drawer.result.text()
        assert g.isVisible() == (gdzie != "stos_schowany")
        assert zdania == ([zdanie] if gdzie == "zbiory_widoczne" else []), zdania
    finally:
        puszczona.set()
        win.close()


def test_ponowny_staging_nazw_przebiegu_podjetego_zostawia_slad_w_dzienniku(qapp, tmp_path):
    """Staging trzech nazw, zamknięcie, restart (przebieg podjęty), ponowny staging z innym przesunięciem: zamiar
    z poprzedniej sesji schodzi z JEDNYM `staging.discarded` z liczbą, a przebieg prowadzi odtąd ta sesja.
    Kolejny ponowny staging (już staging tej sesji) - bez zdarzenia. Falsyfikator: `clear_waiting_staging` bez
    zdarzenia na przebiegu podjętym."""
    path, con, _p = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con, inline=True)
    v._on_rename_stage(_POL)
    run = v._rename_run_id
    _zamknij_widok(v)
    con.close()
    con, v = _restart(path)

    def _zdarzenia():
        return [(r["target"], json.loads(r["payload"])) for r in con.execute(
            "SELECT target, payload FROM event WHERE verb = 'staging.discarded'")]
    try:
        assert v._rename_run_id == run and v._run_poprzedni == run
        v._on_rename_stage({**_POL, "offset_hours": 1})
        assert _zdarzenia() == [(f"run:{run}", {"n": 3, "klinga": "nazwy"})]
        assert v._run_poprzedni is None and v._rename_pending_count() == 3
        v._on_rename_stage({**_POL, "offset_hours": 2})
        assert len(_zdarzenia()) == 1 and v._rename_pending_count() == 3
    finally:
        _zamknij_widok(v)
        con.close()


def test_ponowny_staging_podjetego_bez_czekajacych_nie_mowi_domowi_o_odrzuceniu(qapp, tmp_path):
    """Przebieg podjęty, którego wpisy zdjął w międzyczasie ktoś inny (drugie połączenie, CLI): ponowny staging
    nie zostawia zdarzenia odrzucenia z `n = 0` - Dom mówiłby wtedy „1 zmiana” o niczym (zdanie ogólne gestu).
    Falsyfikator: `_odrzuc_czekajace` na przebiegu podjętym bez czekających (zdarzenie `staging.discarded`
    z `n = 0`)."""
    from horreum import repo
    from horreum.gui import home as home_mod
    from horreum.gui.home import HomeView
    path, con, _p = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con, inline=True)
    v._on_rename_stage(_POL)
    run = v._rename_run_id
    _zamknij_widok(v)
    con.close()
    con, v = _restart(path)
    try:
        assert v._run_poprzedni == run
        con2 = db.connect(path)
        try:
            repo.clear_waiting_staging(con2, run_id=run, klinga="nazwy")
        finally:
            con2.close()
        v._on_rename_stage({**_POL, "offset_hours": 1})
        assert con.execute("SELECT count(*) FROM event WHERE verb = 'staging.discarded'").fetchone()[0] == 0
        h = HomeView(con, now_fn=lambda: NOW, poza_watkiem=False)
        try:
            gest = h._gest_ostatnio()
            assert gest is None or "staging.discarded" not in gest["verbs"], gest
            if gest is not None:
                assert home_mod.zdanie_gestu(gest) != i18n.t_plural("home.gest.many", 1)
        finally:
            h.close()
    finally:
        _zamknij_widok(v)
        con.close()


def test_odlozone_odswiezenie_schodzi_przy_strazniku(qapp, tmp_path, monkeypatch):
    """Aktywacja przy otwartym edytorze komórki odkłada odświeżenie pustej szuflady; edytor zatwierdza kartę
    Enterem (przebieg tej sesji) - odłożone odświeżenie trafia na strażnika i SCHODZI. Dawniej zostawało, a każde
    przejście „zbiór nie w drodze” powtarzało bezskuteczną próbę. Falsyfikator: zerowanie odłożenia po
    strażniku, nie przed nim."""
    from PySide6.QtTest import QTest
    from test_gui_drogi_reki import _otworz_edytor
    from test_gui_pasek_szczegol import _czekaj
    _path, con, _p = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con, inline=True)
    try:
        idx, ed, _inny = _otworz_edytor(qapp, v, "TELESCOP")
        _aktywacja(v)
        assert v._odswiezenie_po_zbiorze is True
        ed.wartosc.setText("EQ6")
        QTest.keyClick(ed.wartosc, Qt.Key_Return)
        _czekaj(lambda: v.table.indexWidget(idx) is None and not v._zbior_w_drodze(), "edytor zamknięty")
        QApplication.processEvents()
        assert v._run_id is not None and v._pending_count() == 1
        assert v._odswiezenie_po_zbiorze is False
        wolania = []
        prawdziwy = v._odswiez_pusta_szuflade
        monkeypatch.setattr(v, "_odswiez_pusta_szuflade", lambda: (wolania.append(1), prawdziwy())[1])
        v.refresh()
        _czekaj(lambda: not v._zbior_w_drodze(), "przeładowanie")
        assert wolania == []
    finally:
        _zamknij_widok(v)
        con.close()


def _nazwy_rozdarte(tmp_path, monkeypatch, n=3):
    """Staging `n` nazw w oknie, zamknięcie okna i zapis nazw drugim połączeniem ROZDARTY bez śmierci procesu:
    `os.rename` pierwszego pliku zaszedł, przepięcie bazy padło, a kompensacja nie wyszła (atrapy wyłącznie tych
    dwóch porażek - wzór `test_rename._rozdarty`; pisarz prawdziwy), anulowanie przed drugim plikiem. Pierwszy
    wiersz `failed` z kodem SAMEJ PRÓBY `torn_db_not` i otwartym zamiarem, reszta czeka; rekoncyliacja tego
    zamiaru jeszcze nie biegła (rekoncyliacja na wejściu zapisu zamiaru jeszcze nie widziała). Zwraca (ścieżka
    bazy, pliki, run_id) - połączenie zamknięte."""
    import sqlite3
    from horreum import repo
    from test_rename import _bez_kompensacji, _pad_raz
    path, con, pliki = _baza_szuflady(tmp_path, n)
    v = _widok_szuflady(con, inline=True)
    v._on_rename_stage(_POL)
    run = v._rename_run_id
    _zamknij_widok(v)
    pytania = []

    def _anuluj_po_pierwszym():
        pytania.append(1)
        return len(pytania) > 1
    with monkeypatch.context() as m:
        _pad_raz(m, repo, "_apply_relocation", sqlite3.OperationalError("disk I/O error"))
        _bez_kompensacji(m)
        wynik = writeback.commit_renames(con, run, now=NOW, should_cancel=_anuluj_po_pierwszym)
    assert wynik.cancelled and [f.reason.code for f in wynik.failed] == ["torn_db_not"], wynik
    assert sorted(tuple(r) for r in con.execute(
        "SELECT status, reason_code, in_flight FROM pending_renames WHERE run_id = ?", (run,))) == sorted(
        [("failed", "torn_db_not", "commit")] + [("pending", None, None)] * (n - 1))
    con.close()
    return path, pliki, run


@pytest.mark.parametrize("przerwanie", ["smierc", "rozdarcie"])
def test_odmowa_rekoncyliacji_nazw_mowi_powod_w_szufladzie(qapp, tmp_path, monkeypatch, przerwanie):
    """Zapis nazw przerwany - śmiercią procesu (wiersz zamiaru bez kodu) albo rozdarciem bez śmierci (wiersz
    `failed` z kodem samej próby `torn_db_not`). PRZED pierwszą rekoncyliacją pusta szuflada obiecuje, że zamiar
    rozstrzygnie „Przyjmij nowe” - kod próby to nie odmowa rekoncyliacji. Plik stoi pod OBIEMA nazwami (kopia
    pod starą): rekoncyliacja drugim połączeniem odmawia i zostawia powód na wierszu zamiaru (prawdziwy rdzeń
    i klinga powodu), a szuflada mówi ten powód zamiast obietnicy. Kopia zdjęta: rekoncyliacja rozstrzyga
    zamiar, wiersza z otwartym zamiarem już nie ma, a szuflada podejmuje przebieg. Falsyfikatory: zdanie nazw
    zatrzymanych bez gałęzi odmowy (dalej obietnica); odczyt powodów bez filtra kodów odmowy (`torn_db_not`
    przed rekoncyliacją ogłoszony jako odmowa)."""
    import shutil
    from horreum.gui.wb_worker import tekst_powodu
    from horreum.item_reasons import z_bazy
    if przerwanie == "smierc":
        path, _pliki, run = _nazwy_przerwane_smiercia(tmp_path, monkeypatch)
        czeka = 3
    else:
        path, _pliki, run = _nazwy_rozdarte(tmp_path, monkeypatch)
        czeka = 2
    con, v = _restart(path)
    try:
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_names_held", czeka)
        assert v.drawer.result.text() == _droga_nazw()
        assert queries.powody_zamiarow_nazw(con, {run}) == ([], 1)
        stara, nowa = con.execute("SELECT old_path, new_path FROM pending_renames "
                                  "WHERE in_flight IS NOT NULL").fetchone()
        shutil.copyfile(nowa, stara)
        assert [f.status for f in _rekoncyliacja_obok(path)] == ["blocked"]
        (w,), czekajace = queries.powody_zamiarow_nazw(con, {run})
        assert w["reason_code"] == "intent_both_names" and czekajace == 0
        v.set_writeback_busy(True)
        v.set_writeback_busy(False)
        # Zwięzłe zdanie (AR-387): droga człowieka i NAZWY plików na końcu, pełny powód (ze ścieżkami) stoi
        # w szczególe zdania. Wyrocznia nazw z `os.path.basename`, nie funkcją pod testem.
        odmowa = z_bazy(w["reason"], w["reason_code"], w["reason_args"])
        assert v.drawer.result.text() == i18n.t(
            "grid.drawer.refused.intent_both_names", src=os.path.basename(stara), dst=os.path.basename(nowa),
            way=i18n.t("grid.drawer.names_way_both", receive=i18n.t("pipeline.receive"), nav=i18n.t("nav.dostawa")))
        assert stara not in v.drawer.result.text() and v.drawer.result.szczegol() == tekst_powodu(odmowa)
        assert v.drawer.result.text().count("rozstrzyga człowiek") == 0, v.drawer.result.text()
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_names_held", czeka)
        os.remove(stara)
        assert [f.status for f in _rekoncyliacja_obok(path)] == ["reconciled"]
        assert con.execute("SELECT count(*) FROM pending_renames WHERE in_flight IS NOT NULL").fetchone()[0] == 0
        assert queries.powody_zamiarow_nazw(con, {run}) == ([], 0)
        v.set_writeback_busy(True)
        v.set_writeback_busy(False)
        assert v._rename_run_id == run and v._rename_pending_count() == 2
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_rename_prev", 2)
    finally:
        _zamknij_widok(v)
        con.close()


def test_powod_zamiaru_spoza_przebiegow_zdania_nie_trafia_do_zdania(qapp, tmp_path, monkeypatch):
    """Trzy przebiegi z otwartymi zamiarami: `A` (trzy nazwy, zapis przerwany śmiercią - zamiar bez kodu),
    `B` (jedna nazwa) i `C` (dwie nazwy, anulowanie przed drugą) - oba zapisy rozdarte, a rekoncyliacja obu
    ODMÓWIŁA (inny `mtime` pod nową nazwą - powody różne, bo różne pliki). `B` nie ma już wierszy czekających,
    więc zdanie szuflady mówi o `A` i `C`: liczba obu, obietnica dla zamiaru `A`, który czeka na rekoncyliację,
    i powód odmowy `C` - bez powodu `B`. Prawdziwy rdzeń i klinga powodu. Falsyfikatory: odczyt powodów bez
    zbioru przebiegów zdania (powód `B` w zdaniu); obietnica wyłącznie przy braku odmów (zamiar `A` bez słowa,
    co go rozstrzygnie)."""
    import sqlite3
    from datetime import datetime
    from horreum import repo
    from horreum.item_reasons import z_bazy
    from test_rename import _bez_kompensacji, _pad_raz
    path, con, _p = _baza_szuflady(tmp_path, 6)
    lok = con.execute("SELECT id, path, mtime FROM location ORDER BY id").fetchall()
    for run, (lid, p, mt) in [("A", w) for w in lok[:3]] + [("B", lok[3])] + [("C", w) for w in lok[4:]]:
        repo.stage_rename(con, run_id=run, location_id=lid, old_path=p, new_path=p + ".x", expected_mtime=mt)
    # `mtime` pod nową nazwą zmieniony zaraz po rozdarciu: rekoncyliacja na wejściu następnego zapisu ma
    # odmówić, nie rozstrzygnąć zamiaru `B`.
    for run, stara in (("B", lok[3][1]), ("C", lok[4][1])):
        pytania = []
        with monkeypatch.context() as m:
            _pad_raz(m, repo, "_apply_relocation", sqlite3.OperationalError("disk I/O error"))
            _bez_kompensacji(m)
            writeback.commit_renames(con, run, now=NOW,
                                     should_cancel=lambda p=pytania: p.append(1) or len(p) > 1)
        st = os.stat(stara + ".x")
        os.utime(stara + ".x", (st.st_atime, st.st_mtime + 5000))
    assert [f.reason.code for f in writeback.reconcile_renames(con, now=NOW)] == ["intent_mtime_differs"] * 2
    with monkeypatch.context() as m:
        _pad_raz(m, repo, "_apply_relocation", KeyboardInterrupt())
        with pytest.raises(KeyboardInterrupt):
            writeback.commit_renames(con, "A", now=NOW)
    assert sorted(tuple(r) for r in con.execute(
        "SELECT run_id, status, reason_code FROM pending_renames WHERE in_flight IS NOT NULL")) == [
        ("A", "pending", None), ("B", "failed", "intent_mtime_differs"), ("C", "failed", "intent_mtime_differs")]
    con.close()
    con, v = _restart(path)
    try:
        assert queries.powody_zamiarow_nazw(con, {"A"}) == ([], 1)
        (wb,), czekajace = queries.powody_zamiarow_nazw(con, {"B"})
        assert wb["run_id"] == "B" and czekajace == 0
        (wc,), czekajace = queries.powody_zamiarow_nazw(con, {"A", "C"})
        assert wc["run_id"] == "C" and czekajace == 1

        def _odmowa(w):                  # zwięzłe zdanie (AR-387): nazwa `os.path.basename`, czasy lokalne do sekundy
            p = dict(z_bazy(w["reason"], w["reason_code"], w["reason_args"]).params)
            chwile = [datetime.fromisoformat(p[k]).astimezone() for k in ("mtime", "db_mtime")]
            # Para po dwóch stronach przestawienia zegara maszyny mówi przesunięcie strefy `±HH:MM` (z ISO).
            strefy = chwile[0].utcoffset() != chwile[1].utcoffset()
            mt, db_mt = (c.strftime("%Y-%m-%d %H:%M:%S") + (c.isoformat()[-6:] if strefy else "") for c in chwile)
            return i18n.t("grid.drawer.refused.intent_mtime_differs", path=os.path.basename(p["path"]),
                          mtime=mt, db_mtime=db_mt, way=i18n.t("grid.drawer.names_way_check"))
        assert _odmowa(wb) != _odmowa(wc)
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_names_held", 3 + 1)
        assert v.drawer.result.text() == " · ".join((_droga_nazw(), _odmowa(wc)))
    finally:
        _zamknij_widok(v)
        con.close()


def test_wzor_z_nieznanym_tokenem_spoza_edytora_mowi_zdaniem(qapp, tmp_path):
    """Wzór nazwy z tokenem spoza słownika podany poza edytorem (wywołanie z parametrem - edytor daje tylko
    znane tokeny): zero wyjątku ze slotu, zdanie błędu wzoru na pasku i w szufladzie, żadnego przebiegu ani
    wiersza stagingu (AR-208). Falsyfikator: `validate_template` bez gałęzi nieznanego tokenu (odmowa
    `compose_name` wychodzi ze slotu)."""
    _path, con, _p = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con, inline=True)
    try:
        zdania = []
        v.status_message.connect(zdania.append)
        v._on_rename_stage({**_POL, "template": ["datetime", "planeta"]})
        assert zdania[-1].startswith(i18n.t("grid.rename.error", e="")) and "'planeta'" in zdania[-1], zdania
        assert v.drawer.result.text() == zdania[-1]
        assert v._rename_run_id is None
        assert con.execute("SELECT count(*) FROM pending_renames").fetchone()[0] == 0
    finally:
        _zamknij_widok(v)
        con.close()
