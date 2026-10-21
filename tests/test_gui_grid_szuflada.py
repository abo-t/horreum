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

from horreum import db, writeback
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
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
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
        assert v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=2)
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
    podjęty musi być `R`, a zdanie liczy wyłącznie przebiegi do podjęcia. Falsyfikatory: predykat bez
    któregokolwiek z trzech wykluczeń."""
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
        assert v.drawer.result.text() == ""
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
        assert v._run_id is None and v.drawer.label.text() == i18n.t("grid.drawer.empty")
        assert v.drawer.result.text() == i18n.t_plural("grid.wb.rejected", 2)
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
    """Zapis (żywe „Cofnij”), potem staging samych pominięć - „Cofnij” i wiersz szuflady z numerem commitu
    zostają (reguła „Popraw f/”: „Cofnij” znika, gdy do szuflady COŚ wchodzi), przyczyny mówi pasek.
    Falsyfikator: `_dismiss_undo` przed makrem (szuflada bez akcji i bez numeru commitu)."""
    _path, con, _p = _cztery_pliki_z_kopia(tmp_path)
    v = _widok_szuflady(con, inline=True)
    try:
        zdania = []
        v.status_message.connect(zdania.append)
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _klik_w(v.drawer.btn_commit)
        cid = v._undo_commit_id
        wiersz = v.drawer.label.text() + " | " + v.drawer.result.text()
        _makro_przyciskiem(v, "EXPTIME", "abc")
        assert v._undo_mode == "macro" and v._undo_btn.isVisible()
        assert v.drawer.label.text() + " | " + v.drawer.result.text() == wiersz
        assert wiersz.count(f"commit {cid})") == 1
        assert " 3: " in zdania[-1] and " · 1: " in zdania[-1]
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
            ident = f"commit {v._undo_commit_id})"
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
            ident, etykieta = f"commit {v._undo_commit_id})", i18n.t("grid.wb.committed_label", n=2)
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
        op = "undo" if klinga == "karty" else "undo_rename"
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
        assert b.drawer.result.text() == i18n.t("grid.drawer.foreign_owner")
        zdania = []
        b.status_message.connect(zdania.append)
        _makro_przyciskiem(b, "TELESCOP", "AZ-GTI")
        assert zdania[-1] == i18n.t("grid.drawer.foreign_owner") and b._run_id is None
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
        assert v._run_id is None and v.drawer.label.text() == i18n.t("grid.drawer.empty")
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
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
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
        ident = f"commit {v._undo_commit_id})"
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
