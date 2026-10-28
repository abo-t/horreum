"""Szuflada Zbiorów - „Cofnij” CAŁEGO przebiegu (AR-345), jedno zdanie wyniku częściowego zapisu (AR-344)
i gest „Ponów nieudane (N)” (AR-347). Kliki prawdziwe (`QTest.mouseClick` na widżecie), wątek zapisu prawdziwy
tam, gdzie gest go ma (zapis przerwany „Anuluj”), czekanie pętlą zdarzeń; atrapy wyłącznie awarii."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from horreum import db, repo, writeback
from horreum.gui import grid as grid_mod, i18n

from test_gui_grid_szuflada import (_POL, _baza_szuflady, _klik_w, _makro_przyciskiem, _obcy, _przerwany_zapis,
                                    _restart, _trzyma_blokade, _widok_szuflady, _zamknij_widok)
from test_gui_pasek_szczegol import _anuluj_w_biegu, _brama_po_pierwszym_pliku, _czekaj


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _bajty(pliki):
    return [p.read_bytes() for p in pliki]


def _koniec_biegu(v, opis):
    _czekaj(lambda: not v._wb.is_busy and not v._zbior_w_drodze(), opis)
    QApplication.processEvents()


def _prog_error():
    return i18n.t("objchg.item.prog_error")


# ============================================================ AR-345 - „Cofnij” cofa cały przebieg


def test_przerwany_i_dokonczony_cofnij_przywraca_wszystkie_pliki(qapp, tmp_path, monkeypatch):
    """Falsyfikator briefu: trzy pliki, makro TELESCOP kliknięciem, „Zatwierdź” z prawdziwym wątkiem i „Anuluj” po
    pierwszym pliku, drugie „Zatwierdź”, „Cofnij” - bajty WSZYSTKICH trzech plików wracają, kotwica niesie oba
    commity. Falsyfikator: „Cofnij” samego commitu ostatniej operacji (plik pierwszego zostaje zmieniony)."""
    _path, con, pliki = _baza_szuflady(tmp_path, 3)
    przed = _bajty(pliki)
    v = _widok_szuflady(con)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _przerwany_zapis(v, monkeypatch)
        assert v._pending_count() == 2
        _klik_w(v.drawer.btn_commit)
        _koniec_biegu(v, "dokończenie zapisu")
        assert v._undo_commity == (1, 2) and v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=3)
        assert v.drawer.result.text().endswith(i18n.t("grid.wb.commit_ids", ids="1, 2")), v.drawer.result.text()
        _klik_w(v._undo_btn)
        _koniec_biegu(v, "cofnięcie przebiegu")
        assert _bajty(pliki) == przed
        assert not v._undo_btn.isVisible() and v._undo_mode is None
    finally:
        _zamknij_widok(v)
        con.close()


def test_odrzuc_po_przerwanym_zapisie_stawia_cofnij_zapisanego(qapp, tmp_path, monkeypatch):
    """Wariant „Odrzuć”: po „Anuluj” klik „Odrzuć” zdejmuje dwa czekające wpisy, a szuflada oferuje „Cofnij”
    pliku zapisanego przed przerwaniem (zdanie mówi, skąd przycisk); klik przywraca jego bajty. Falsyfikator:
    „Odrzuć” bez reguły (pustostan, plik zostaje zmieniony bez drogi w szufladzie)."""
    _path, con, pliki = _baza_szuflady(tmp_path, 3)
    przed = _bajty(pliki)
    v = _widok_szuflady(con)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _przerwany_zapis(v, monkeypatch)
        _klik_w(v.drawer.btn_reject)
        assert v._undo_btn.isVisible() and v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=1)
        assert v.drawer.result.text().startswith(i18n.t_plural("grid.wb.rejected", 2)
                                                 + i18n.t_plural("grid.wb.written_before", 1))
        _klik_w(v._undo_btn)
        _koniec_biegu(v, "cofnięcie po odrzuceniu")
        assert _bajty(pliki) == przed
    finally:
        _zamknij_widok(v)
        con.close()


def test_restart_cofnij_obejmuje_commit_sprzed_restartu(qapp, tmp_path, monkeypatch):
    """Wariant „restart”: przebieg przerwany, okno zamknięte, nowe okno podejmuje przebieg, „Zatwierdź” dokańcza,
    „Cofnij” - bajty wszystkich plików wracają, także pliku zapisanego przed restartem (decyzja CEO). Falsyfikator:
    zakres „Cofnij” z commitów tej sesji albo tej operacji."""
    path, con, pliki = _baza_szuflady(tmp_path, 3)
    przed = _bajty(pliki)
    v = _widok_szuflady(con)
    _makro_przyciskiem(v, "TELESCOP", "EQ6")
    _przerwany_zapis(v, monkeypatch)
    _zamknij_widok(v)
    con.close()
    con, v = _restart(path)
    try:
        assert v._pending_count() == 2
        _klik_w(v.drawer.btn_commit)
        _koniec_biegu(v, "dokończenie po restarcie")
        _klik_w(v._undo_btn)
        _koniec_biegu(v, "cofnięcie po restarcie")
        assert _bajty(pliki) == przed
    finally:
        _zamknij_widok(v)
        con.close()


def test_dokonczenie_samymi_blokadami_stawia_cofnij_wczesniejszego_zapisu(qapp, tmp_path, monkeypatch):
    """Przebieg przerwany po pierwszym pliku, dwa pozostałe pliki zmienione z zewnątrz (dokończenie je blokuje):
    operacja nic nie podmienia, a „Cofnij” stoi dla pliku sprzed przerwania i zdanie mówi „1 plik zapisany
    wcześniej”. Falsyfikator: gałąź „nic nie podmieniono” = pustostan."""
    from astropy.io import fits
    _path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    try:
        przed_pierwszy = pliki[0].read_bytes()
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _przerwany_zapis(v, monkeypatch)
        for p in pliki[1:]:
            fits.setval(str(p), "OBSERVER", value="obcy")
        _klik_w(v.drawer.btn_commit)
        _koniec_biegu(v, "dokończenie samymi blokadami")
        assert v._undo_btn.isVisible() and v._undo_commity == (1,)
        assert i18n.t_plural("grid.wb.written_before", 1) in v.drawer.result.text(), v.drawer.result.text()
        _klik_w(v._undo_btn)
        _koniec_biegu(v, "cofnięcie")
        assert pliki[0].read_bytes() == przed_pierwszy
    finally:
        _zamknij_widok(v)
        con.close()


def test_odrzuc_nazw_po_przerwanym_zapisie_stawia_cofnij_nazw(qapp, tmp_path, monkeypatch):
    """Nazwy (lustro kart): zmiana trzech nazw przerwana po pierwszym pliku, „Odrzuć” - „Cofnij” nazw przywraca
    nazwę pierwszego pliku. Falsyfikator: `_on_reject_rename` bez reguły (wiersz `applied` bez drogi w szufladzie)."""
    _path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    try:
        v._on_rename_stage(_POL)
        stary = v.model._preview
        brama, doszlo = _brama_po_pierwszym_pliku(monkeypatch)
        _klik_w(v.drawer.btn_commit)
        _anuluj_w_biegu(v, brama, doszlo, stary)
        assert sum(not p.exists() for p in pliki) == 1
        _klik_w(v.drawer.btn_reject)
        assert v._undo_mode == "rename" and v._undo_btn.isVisible()
        _klik_w(v._undo_btn)
        _koniec_biegu(v, "cofnięcie nazw")
        assert all(p.exists() for p in pliki)
    finally:
        _zamknij_widok(v)
        con.close()


def test_cofnij_przebiegu_cofa_zakres_zamrozony(qapp, tmp_path):
    """Zakres „Cofnij” zamrożony w chwili postawienia: commit dopisany do tego przebiegu PÓŹNIEJ (drugie
    połączenie, rdzeń) nie wchodzi do cofnięcia - wraca plik commitu z szuflady, plik późniejszego zostaje.
    Falsyfikator: cofnięcie czyta commity przebiegu przy kliku."""
    from astropy.io import fits
    path, con, pliki = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con, inline=True)
    try:
        f0, f1 = [r[0] for r in con.execute("SELECT id FROM frame ORDER BY id")]
        v.refresh()
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        con.execute("DELETE FROM pending_changes WHERE location_id = (SELECT id FROM location WHERE frame_id = ?)",
                    (f1,))
        con.commit()
        run = v._run_id
        _klik_w(v.drawer.btn_commit)
        assert v._undo_commity == (1,)
        con2 = db.connect(path)
        try:
            loc = con2.execute("SELECT id, header_hash FROM location WHERE frame_id = ?", (f1,)).fetchone()
            repo.stage_pending(con2, run_id=run, location_id=loc["id"], keyword="TELESCOP", idx=0, op="set",
                               old_value="RC8", new_value="EQ8", new_type="str", new_comment=None,
                               expected_header_hash=loc["header_hash"])
            writeback.commit(con2, run, now="2026-07-03T14:00:00", inplace=True)
        finally:
            con2.close()
        _klik_w(v._undo_btn)
        assert [fits.getheader(str(p))["TELESCOP"] for p in pliki] == ["RC8", "EQ8"]
    finally:
        _zamknij_widok(v)
        con.close()


def test_przebieg_wyczyszczony_do_zera_po_zapisie_dostaje_cofnij(qapp, tmp_path, monkeypatch):
    """Przebieg z zapisem przerwanym, z którego czekające wpisy zeszły gdzie indziej (drugie połączenie): zamknięcie
    pustego przebiegu - wspólna droga ponownego makra i stagingu nazw bez zmian oraz ogona gestu izolacji - stawia
    „Cofnij” zapisanego pliku. Falsyfikator: `_zamknij_puste_przebiegi` bez zwrotu zamkniętych przebiegów."""
    path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _przerwany_zapis(v, monkeypatch)
        run = v._run_id
        con2 = db.connect(path)
        try:
            repo.clear_waiting_staging(con2, run_id=run, klinga="karty")
        finally:
            con2.close()
        v._cofnij_po_zamknieciu(v._zamknij_puste_przebiegi())
        assert v._run_id is None and v._undo_btn.isVisible() and v._undo_commity == (1,)
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ AR-345 - podjęcie przebiegu pod blokadą


def _okno_prowadzi_przebieg(tmp_path):
    path, con_a, pliki = _baza_szuflady(tmp_path, 2)
    a = _widok_szuflady(con_a, inline=True)
    _makro_przyciskiem(a, "TELESCOP", "EQ6")
    assert _trzyma_blokade(a) and a._pending_count() == 2
    return path, con_a, a


def test_podjecie_zwolnionego_czyta_przebieg_pod_blokada(qapp, tmp_path, monkeypatch):
    """Okno B zapamiętało przebieg R okna A (cudza blokada przy otwarciu). Między odczytem kandydatów a blokadą A
    zapisuje R do końca i oddaje szufladę (bariera w `_wez_szuflade` B): B nie podejmuje nieaktualnego R, nie
    trzyma blokady, a jego staging zakłada nowy przebieg. Falsyfikator: podjęcie z odczytu sprzed blokady."""
    path, con_a, a = _okno_prowadzi_przebieg(tmp_path)
    con_b = db.connect(path)
    b = _widok_szuflady(con_b, inline=True)
    try:
        run = a._run_id
        assert run in b._wylaczone_znane and b._run_id is None
        prawdziwa = b._wez_szuflade
        bariera = []

        def _z_bariera():
            if not bariera:
                bariera.append(1)
                _klik_w(a.drawer.btn_commit)             # A domyka R i oddaje szufladę
                _czekaj(lambda: not _trzyma_blokade(a), "A oddaje szufladę")
            return prawdziwa()
        monkeypatch.setattr(b, "_wez_szuflade", _z_bariera)
        b.set_writeback_busy(True)
        b.set_writeback_busy(False)                      # odświeżenie pustej szuflady B → `_podejmij_zwolnione`
        assert bariera, "bariera nie zadziałała - test nic by nie mierzył"
        assert b._run_id is None and not _trzyma_blokade(b)
        monkeypatch.undo()
        _makro_przyciskiem(b, "TELESCOP", "AZ-GTI")
        assert b._run_id not in (None, run)
    finally:
        _zamknij_widok(b)
        con_b.close()
        _zamknij_widok(a)
        con_a.close()


def test_podjecie_przy_otwarciu_czyta_przebieg_pod_blokada(qapp, tmp_path, monkeypatch):
    """To samo przy otwarciu bazy (konstruktor B): A domyka R między odczytem kandydatów a blokadą B - B nie
    podejmuje R. Falsyfikator: `_podejmij_przebieg_poprzedni` bez drugiego odczytu pod blokadą."""
    path, con_a, a = _okno_prowadzi_przebieg(tmp_path)
    prawdziwa = grid_mod.FramesView._wez_szuflade
    bariera = []

    def _z_bariera(self):
        if self is not a and not bariera:
            bariera.append(1)
            _klik_w(a.drawer.btn_commit)
            _czekaj(lambda: not _trzyma_blokade(a), "A oddaje szufladę")
        return prawdziwa(self)
    monkeypatch.setattr(grid_mod.FramesView, "_wez_szuflade", _z_bariera)
    con_b = db.connect(path)
    b = _widok_szuflady(con_b, inline=True)
    try:
        assert bariera and b._run_id is None and not _trzyma_blokade(b)
    finally:
        monkeypatch.undo()
        _zamknij_widok(b)
        con_b.close()
        _zamknij_widok(a)
        con_a.close()


# ============================================================ AR-344 - jedno zdanie wyniku częściowego


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_awaria_nazw_po_zapisie_wszystkich_mowi_wynik_czesciowy(qapp, tmp_path, monkeypatch, lang):
    """Zmiana trzech nazw zapisana, potem wyjątek operacji: jedno zdanie „3 z 3 przemianowane, potem błąd: … -
    „Cofnij” przywraca stare nazwy” z identyfikatorem przebiegu; EN bez polskich znaków. Falsyfikator: zdanie
    operacji „nie powiodła się” obok „Przemianowano: 3”."""
    from horreum.gui.wb_worker import WritebackWorker
    i18n.set_lang(lang)
    _path, con, _p = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con, inline=True)
    try:
        v._on_rename_stage(_POL)
        run = v._rename_run_id
        prawdziwe = WritebackWorker._OPS["commit_rename"]

        def _zmien_i_pada(c, t, now, pr, sc):
            prawdziwe(c, t, now, pr, sc)
            raise ValueError("złamany inwariant po zmianie nazw")
        monkeypatch.setitem(WritebackWorker._OPS, "commit_rename", _zmien_i_pada)
        _klik_w(v.drawer.btn_commit)
        assert v.drawer.result.text() == (
            i18n.t_plural("grid.wb.partial_rename", 3, m=3, msg=_prog_error())
            + i18n.t("grid.wb.partial_undo_names", undo=i18n.t("grid.action.undo"))
            + i18n.t("grid.wb.run_id", id=run)), v.drawer.result.text()
        if lang == "en":
            assert not set(v.drawer.result.text()) & set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"), v.drawer.result.text()
    finally:
        i18n.set_lang("pl")
        _zamknij_widok(v)
        con.close()


def test_awaria_przed_pierwszym_postepem_liczy_pliki_z_bazy(qapp, tmp_path, monkeypatch):
    """Wyjątek po zapisie PIERWSZEGO pliku, zanim rdzeń zgłosił jakikolwiek postęp (zapis statusu wpisu pada
    `database is locked`, droga atomowa): zdanie „1 z 3 zapisany, potem błąd: … - 3 do dokończenia” - liczba
    plików operacji ustalona przed pierwszym zapisem, zapisane z faktów bazy. Falsyfikator: M z postępu
    (brak źródła - zdanie operacji bez liczby)."""
    import sqlite3
    from astropy.io import fits
    from horreum.gui.wb_worker import tekst_powodu
    from horreum.item_reasons import powod_okna
    _path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con, inline=True)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        wyjatek = sqlite3.OperationalError("database is locked")
        monkeypatch.setattr(writeback, "write_changes_inplace",
                            lambda *a, **k: writeback.Fallback("droga atomowa w teście"))
        monkeypatch.setattr(repo, "set_pending_status", lambda *a, **k: (_ for _ in ()).throw(wyjatek))
        _klik_w(v.drawer.btn_commit)
        assert fits.getheader(str(pliki[0]))["TELESCOP"] == "EQ6", "pierwszy plik nie zapisany - test nic nie mierzy"
        assert v.drawer.result.text() == (
            i18n.t_plural("grid.wb.partial_commit", 1, m=3, msg=tekst_powodu(powod_okna(wyjatek)))
            + i18n.t("grid.wb.partial_finish", n=3)), v.drawer.result.text()
    finally:
        monkeypatch.undo()
        _zamknij_widok(v)
        con.close()


# ============================================================ AR-344 - fakty wykonawcy


def test_fakty_zuzyte_raz_awaria_nastepnej_operacji_ich_nie_widzi(qapp, tmp_path):
    """Udany zapis zużywa fakty wykonawcy; awaria NASTĘPNEJ operacji (bez faktów) mówi zdaniem operacji, nie
    wynikiem częściowym poprzedniej. Falsyfikator: ogon sukcesu bez zużycia faktów."""
    _path, con, _p = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con, inline=True)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _klik_w(v.drawer.btn_commit)
        assert v._undo_mode == "macro"
        v._on_wb_failed("commit", _prog_error(), "")
        assert v.drawer.result.text().startswith(i18n.t("grid.wb.op.commit", msg=_prog_error())), \
            v.drawer.result.text()
    finally:
        _zamknij_widok(v)
        con.close()


def test_zatwierdz_klasyfikuje_backupy_przebiegu_raz(qapp, tmp_path, monkeypatch):
    """Klik „Zatwierdź”: fakty wykonawcy (zakres „Cofnij” przebiegu i pliki TEJ operacji) i „Cofnij” szuflady
    z JEDNEJ klasyfikacji backupów (`writeback._klasy_przebiegu`; każda to kilka zapytań na plik). Falsyfikator:
    osobny odczyt zakresu przebiegu w wykonawcy (dwie klasyfikacje)."""
    _path, con, _p = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con, inline=True)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        prawdziwe, wywolania = writeback._klasy_przebiegu, []
        monkeypatch.setattr(writeback, "_klasy_przebiegu", lambda c, r: wywolania.append(r) or prawdziwe(c, r))
        _klik_w(v.drawer.btn_commit)
        assert v._undo_commity == (1,) and v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=2)
        assert len(wywolania) == 1, wywolania
    finally:
        _zamknij_widok(v)
        con.close()


def test_udany_zapis_przy_padzie_odczytu_faktow_stawia_cofnij_tej_operacji(qapp, tmp_path, monkeypatch):
    """Odczyt zakresu w wykonawcy pada po UDANYM zapisie: „Cofnij” stoi z zakresem commitu tej operacji
    (`CommitResult.commit_id` jest wiarygodny). Falsyfikator: brak faktów = brak „Cofnij”."""
    _path, con, pliki = _baza_szuflady(tmp_path, 2)
    przed = _bajty(pliki)
    v = _widok_szuflady(con, inline=True)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        with monkeypatch.context() as m:
            m.setattr(writeback, "_klasy_przebiegu", lambda *a, **k: (_ for _ in ()).throw(sqlite3_blad()))
            _klik_w(v.drawer.btn_commit)
        assert v._undo_btn.isVisible() and v._undo_commity == (1,)
        _klik_w(v._undo_btn)
        assert _bajty(pliki) == przed
    finally:
        _zamknij_widok(v)
        con.close()


def sqlite3_blad():
    import sqlite3
    return sqlite3.OperationalError("database is locked")


def test_awaria_przy_padzie_odczytu_faktow_wychodzi_z_postepu_bez_cofnij(qapp, tmp_path, monkeypatch):
    """Awaria zapisu i pad odczytu faktów: szuflada wychodzi z trybu postępu (pasek i „Anuluj” schowane), „Cofnij”
    nie staje (zakresu nie da się ustalić), zdanie mówi „co najmniej N z M” z postępu. Falsyfikator: odczyt bazy
    w ogonie awarii przed wyjściem z postępu."""
    from horreum.gui.wb_worker import WritebackWorker, _zapis_kart

    def _zapisz_i_pada(c, t, now, pr, sc):
        _zapis_kart(c, t, now, pr, sc)
        raise ValueError("złamany inwariant po zapisie")
    _path, con, _p = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con, inline=True)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        monkeypatch.setitem(WritebackWorker._OPS, "commit", _zapisz_i_pada)
        # Odczyt zakresu pada WSZĘDZIE (wykonawca i wątek okna) - ogon awarii nie może go wołać przed wyjściem
        # z postępu.
        monkeypatch.setattr(writeback, "_klasy_przebiegu", lambda *a, **k: (_ for _ in ()).throw(sqlite3_blad()))
        _klik_w(v.drawer.btn_commit)
        assert not v.drawer.bar.isVisible() and not v.drawer.btn_cancel.isVisible()
        assert v._undo_mode is None
        assert v.drawer.result.text() == i18n.t_plural("grid.wb.partial_commit_min", 3, m=3, msg=_prog_error()), \
            v.drawer.result.text()
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ AR-347 - „Ponów nieudane (N)”


def _zajety(monkeypatch, plik):
    """Blokada współdzielenia pliku `plik` zajęta (WinError 32 po ponowieniach) - zapis tego pliku `failed`."""
    prawdziwa = writeback._exclusive
    monkeypatch.setattr(writeback, "_LOCK_RETRY_DELAYS", (0,))

    def _blokada(path):
        if os.path.basename(path) == plik.name:
            raise writeback._blad_windows(32, path)
        return prawdziwa(path)
    monkeypatch.setattr(writeback, "_exclusive", _blokada)


def test_ponow_nieudane_zapisuje_zajety_plik_a_cofnij_cofa_caly_przebieg(qapp, tmp_path, monkeypatch):
    """Falsyfikator briefu: plik zajęty (WinError 32) przy zapisie trzech - po „Zatwierdź” widoczny i czynny
    „Ponów nieudane (1)” obok „Cofnij”; klik wraca wpis `pending` do TEGO SAMEGO przebiegu; „Zatwierdź” zapisuje
    plik; „Cofnij” przywraca bajty wszystkich trzech. Falsyfikatory: brak gestu; ponowienie w nowym przebiegu
    („Cofnij” nie obejmie pierwszego zapisu)."""
    _path, con, pliki = _baza_szuflady(tmp_path, 3)
    przed = _bajty(pliki)
    v = _widok_szuflady(con, inline=True)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        run = v._run_id
        with monkeypatch.context() as m:
            _zajety(m, pliki[1])
            _klik_w(v.drawer.btn_commit)
        retry = v.drawer.btn_retry
        assert retry.isVisible() and retry.isEnabled() and retry.text() == i18n.t("grid.drawer.retry", n=1)
        assert v._undo_btn.isVisible()
        _klik_w(retry)
        assert v._run_id == run and v._pending_count() == 1 and not retry.isVisible()
        assert v.drawer.btn_commit.isVisible() and not v._undo_btn.isVisible()
        _klik_w(v.drawer.btn_commit)
        assert v._undo_commity == (1, 2) and not retry.isVisible()
        _klik_w(v._undo_btn)
        assert _bajty(pliki) == przed
    finally:
        _zamknij_widok(v)
        con.close()


def test_ponow_nieudane_nazw(qapp, tmp_path, monkeypatch):
    """Nazwy: plik zajęty przy zmianie nazwy (WinError 32 po ponowieniach) - „Ponów nieudane (1)”, klik i
    „Zatwierdź” zmieniają nazwę, „Cofnij” nazw przywraca wszystkie. Falsyfikator: gest wyłącznie dla kart."""
    _path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con, inline=True)
    try:
        v._on_rename_stage(_POL)
        prawdziwy = writeback.os.rename

        def _rename(src, dst):
            if os.path.basename(src) == pliki[1].name:
                raise OSError(None, "plik używany przez inny proces", src, 32)
            return prawdziwy(src, dst)
        with monkeypatch.context() as m:
            m.setattr(writeback, "_PODMIANA_PONOWIENIA", (0,))
            m.setattr(writeback.os, "rename", _rename)
            _klik_w(v.drawer.btn_commit)
        assert pliki[1].exists() and v.drawer.btn_retry.isVisible()
        _klik_w(v.drawer.btn_retry)
        assert v._rename_pending_count() == 1
        _klik_w(v.drawer.btn_commit)
        assert not any(p.exists() for p in pliki)
        _klik_w(v._undo_btn)
        assert all(p.exists() for p in pliki)
    finally:
        _zamknij_widok(v)
        con.close()


def test_ponowienie_bieg_wygasza_a_staging_chowa(qapp, tmp_path, monkeypatch):
    """Cykl przycisku: bieg operacji (także gestu spoza stagingu) tylko WYGASZA „Ponów nieudane” - po biegu wraca
    czynny; etap Dostawy wygasza i przywraca jak „Cofnij”; nowy staging go chowa. Falsyfikatory: `begin_progress`
    chowa przycisk; `set_busy` go nie wygasza."""
    _path, con, pliki = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con, inline=True)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        with monkeypatch.context() as m:
            _zajety(m, pliki[1])
            _klik_w(v.drawer.btn_commit)
        retry = v.drawer.btn_retry
        assert retry.isVisible() and retry.isEnabled()
        v.drawer.begin_progress(0)
        assert retry.isVisible() and not retry.isEnabled()
        v.drawer.end_progress()
        assert retry.isVisible() and retry.isEnabled()
        v.set_busy(True)
        assert not retry.isEnabled()
        v.set_busy(False)
        assert retry.isVisible() and retry.isEnabled()
        _makro_przyciskiem(v, "TELESCOP", "AZ-GTI")
        assert v._pending_count() > 0 and not retry.isVisible()
    finally:
        _zamknij_widok(v)
        con.close()


def test_ponowienie_pod_cudza_blokada_odmawia(qapp, tmp_path, monkeypatch):
    """„Ponów nieudane” wraca wpisy do przebiegu, więc bierze blokadę szuflady jak każdy staging: drugie okno
    prowadzi szufladę - zdanie właściciela, nic nie wchodzi do stagingu. Falsyfikator: ponowienie bez blokady."""
    path, con, pliki = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con, inline=True)
    con_b = db.connect(path)
    b = None
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        run = v._run_id
        with monkeypatch.context() as m:
            _zajety(m, pliki[1])
            _klik_w(v.drawer.btn_commit)
        assert v.drawer.btn_retry.isVisible()
        _czekaj(lambda: not _trzyma_blokade(v), "okno oddaje szufladę po zapisie")
        b = _widok_szuflady(con_b, inline=True)
        _makro_przyciskiem(b, "TELESCOP", "AZ-GTI")
        assert _trzyma_blokade(b)
        _klik_w(v.drawer.btn_retry)
        assert v.drawer.result.text() == _obcy() and v._run_id is None
        assert not [r for r in writeback.pending_for_run(con, run) if r["status"] == "pending"]
    finally:
        if b is not None:
            _zamknij_widok(b)
        con_b.close()
        _zamknij_widok(v)
        con.close()


# ============================================================ AR-367 - „Cofnij” ostatniego zapisu po otwarciu bazy


_POLSKIE = set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
_DZIEN = "2026-07-03"                  # `NOW` testów szuflady - znacznik bez strefy, więc dzień lokalny ten sam


def _karta_zapisana(con, run_id, wiersz, wartosc="EQ6"):
    """Przebieg `run_id` z kartą TELESCOP na pliku nr `wiersz`, zapisany prawdziwym rdzeniem (bez okna) - jak
    zapis okna kart albo CLI. Zwraca commit przebiegu."""
    lid, hh = con.execute("SELECT id, header_hash FROM location ORDER BY id LIMIT 1 OFFSET ?", (wiersz,)).fetchone()
    repo.stage_pending(con, run_id=run_id, location_id=lid, keyword="TELESCOP", idx=0, op="set", old_value="RC8",
                       new_value=wartosc, new_type="str", new_comment=None, expected_header_hash=hh)
    writeback.commit(con, run_id, now="2026-07-03T14:00:00", inplace=True)
    return con.execute("SELECT max(id) FROM commits WHERE run_id = ?", (run_id,)).fetchone()[0]


def _bez_cofnij(v):
    return not hasattr(v, "_undo_btn") or not v._undo_btn.isVisible()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_restart_po_pelnym_zapisie_stawia_cofnij_ostatniego_przebiegu(qapp, tmp_path, monkeypatch, lang):
    """Falsyfikator briefu: 4 pliki, makro TELESCOP kliknięciem, „Zatwierdź”, „Anuluj” po pierwszym pliku, drugie
    „Zatwierdź” (commity 1, 2), zamknięcie widoku i nowy widok na tej samej bazie. Szuflada pokazuje ostatni zapis
    kart: zdanie z datą i kotwicą obu commitów, etykieta „Zatwierdzono: 4”, kropka „○”, przycisk „Cofnij”, blokada
    szuflady oddana; klik przywraca bajty wszystkich czterech plików. EN bez polskich znaków. Falsyfikator: gałąź
    „nic nie czeka” bez ostatniego zapisu (pusta szuflada, droga tylko przez CLI)."""
    i18n.set_lang(lang)
    path, con, pliki = _baza_szuflady(tmp_path, 4)
    przed = _bajty(pliki)
    v = _widok_szuflady(con)
    _makro_przyciskiem(v, "TELESCOP", "EQ6")
    _przerwany_zapis(v, monkeypatch)
    _klik_w(v.drawer.btn_commit)
    _koniec_biegu(v, "dokończenie zapisu")
    _zamknij_widok(v)
    con.close()
    con, v = _restart(path)
    try:
        assert v._undo_btn.isVisible() and v._undo_mode == "macro" and v._undo_commity == (1, 2)
        assert v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=4)
        assert v.drawer.result.text() == (
            i18n.t_plural("grid.drawer.last_write", 4, day=_DZIEN, undo=i18n.t("grid.action.undo"))
            + i18n.t("grid.wb.commit_ids", ids="1, 2")), v.drawer.result.text()
        assert v.drawer.dot.text() == "○" and not v.drawer.btn_commit.isVisible()
        assert not _trzyma_blokade(v)
        if lang == "en":
            assert not set(v.drawer.result.text()) & _POLSKIE, v.drawer.result.text()
        _klik_w(v._undo_btn)
        _koniec_biegu(v, "cofnięcie po restarcie")
        assert _bajty(pliki) == przed
    finally:
        i18n.set_lang("pl")
        _zamknij_widok(v)
        con.close()


def test_restart_po_cofnieciu_ostatniego_nie_wraca_do_starszego(qapp, tmp_path):
    """Dwa przebiegi kart zapisane rdzeniem (R1 na pierwszym pliku, R2 na drugim), R2 cofnięty: szuflada po otwarciu
    nie stawia „Cofnij” - ostatni zapis jest cofnięty, a R1 nie jest „ostatnim zapisem”. Falsyfikator: kandydat
    z filtrem „przebieg bez cofnięcia” (cofnięcie do starszego R1)."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    _karta_zapisana(con, "R1", 0)
    c2 = _karta_zapisana(con, "R2", 1)
    writeback.undo_run(con, (c2,), now="2026-07-03T15:00:00")
    con.close()
    con, v = _restart(path)
    try:
        assert _bez_cofnij(v) and v._undo_mode is None
        assert v.drawer.label.text() == i18n.t("grid.drawer.empty")
    finally:
        _zamknij_widok(v)
        con.close()


def test_restart_pomija_przebieg_zmiany_obiektu_nowszy(qapp, tmp_path):
    """Przebieg kart R (commit 1), potem commit przebiegu zmiany obiektu (`object_change_run`) na innym pliku: szuflada
    po otwarciu stawia „Cofnij” przebiegu R - przebieg zmiany obiektu ma własne okno i wiersz Porządków.
    Falsyfikator: kandydat = najwyższy commit w ogóle, a przy zmianie obiektu nic (szuflada pusta)."""
    path, con, _p = _baza_szuflady(tmp_path, 2)
    c1 = _karta_zapisana(con, "R", 0)
    with con:
        con.execute("INSERT INTO object_change_run (run_id, mode, created_at) VALUES ('OC', 'align', ?)",
                    ("2026-07-03T14:00:00",))
    c2 = _karta_zapisana(con, "OC", 1)
    assert c2 > c1
    con.close()
    con, v = _restart(path)
    try:
        assert v._undo_btn.isVisible() and v._undo_commity == (c1,)
    finally:
        _zamknij_widok(v)
        con.close()


def test_restart_bez_cofnij_przy_zmianach_wylaczonych(qapp, tmp_path, monkeypatch):
    """Przebieg z commitem i wpisami czekającymi na dokończenie zapisu w miejscu (zatrzymany izolacją - sam jest
    najnowszym przebiegiem kart): szuflada po otwarciu mówi, ile zmian czeka i co je zwolni (kropka „◌”), a nie
    stawia „Cofnij” - żywe „Cofnij” wyłączyłoby to zdanie. Falsyfikator: odczyt ostatniego zapisu bez warunku
    „nic nie czeka w szufladzie”."""
    from test_gui_grid_szuflada import _kropka, _zatrzymany_izolacja
    path, _pliki = _zatrzymany_izolacja(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        assert _bez_cofnij(v) and v._run_id is None
        assert _kropka(v)[0] == "◌"
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending_isolated", 3)
    finally:
        _zamknij_widok(v)
        con.close()


def test_restart_pod_cudza_blokada_bez_cofnij_i_oddaje_blokade(qapp, tmp_path):
    """Szufladę bazy prowadzi inny proces (blokada trzymana): nowy widok nie stawia „Cofnij” ostatniego zapisu. Po
    zwolnieniu blokady następny widok stawia je i NIE trzyma blokady (przebiegu do prowadzenia nie ma).
    Falsyfikatory: decyzja bez blokady szuflady; blokada wzięta przy decyzji i niezwolniona."""
    from test_gui_grid_szuflada import _blokada_obca
    path, con, _p = _baza_szuflady(tmp_path, 1)
    c1 = _karta_zapisana(con, "R", 0)
    con.close()
    blokada = _blokada_obca(path)
    try:
        con, v = _restart(path)
        try:
            assert _bez_cofnij(v)
        finally:
            _zamknij_widok(v)
            con.close()
    finally:
        blokada.unlock()
    con, v = _restart(path)
    try:
        assert v._undo_btn.isVisible() and v._undo_commity == (c1,)
        assert not _trzyma_blokade(v)
        # Decyzja oddaje blokadę SAMA, nie dopiero `_refresh_drawer` końca konstruktora (drugie wołanie wprost,
        # jak `test_cli_blokada_szuflady`).
        v._podejmij_przebieg_poprzedni()
        assert v._undo_btn.isVisible() and not _trzyma_blokade(v)
    finally:
        _zamknij_widok(v)
        con.close()


def test_restart_zakres_z_jednej_migawki(qapp, tmp_path, monkeypatch):
    """Odczyt ostatniego zapisu pod blokadą (przebieg, zakres) w JEDNEJ migawce: drugie połączenie cofa przebieg
    między odczytem kandydata a odczytem zakresu (bariera w `writeback.przebieg_do_cofniecia` przy drugim
    odczycie - pierwszy idzie przed blokadą). „Cofnij” stoi z zakresem stanu sprzed bariery, a nie z pary dwóch
    chwil. Falsyfikator: odczyt bez transakcji odczytu (zakres po cofnięciu - brak „Cofnij”)."""
    path, con, _p = _baza_szuflady(tmp_path, 1)
    c1 = _karta_zapisana(con, "R", 0)
    con.close()
    prawdziwy, wolania = writeback.przebieg_do_cofniecia, []

    def _z_bariera(c, run_id):
        wolania.append(run_id)
        if len(wolania) == 2:
            con2 = db.connect(path)
            try:
                writeback.undo_run(con2, (c1,), now="2026-07-03T15:00:00")
            finally:
                con2.close()
        return prawdziwy(c, run_id)
    monkeypatch.setattr(writeback, "przebieg_do_cofniecia", _z_bariera)
    con, v = _restart(path)
    try:
        assert len(wolania) == 2, "bariera nie zadziałała - test nic by nie mierzył"
        assert v._undo_btn.isVisible() and v._undo_commity == (c1,)
    finally:
        monkeypatch.undo()
        _zamknij_widok(v)
        con.close()


def test_restart_z_nieudanym_wpisem_stawia_ponow_nieudane(qapp, tmp_path, monkeypatch):
    """Zapis trzech plików z jednym zajętym (WinError 32 - wpis `failed`, plik nietknięty), zamknięcie i nowy widok:
    szuflada stawia „Cofnij” i „Ponów nieudane (1)” - stan zamkniętego przebiegu jak w sesji. Falsyfikator: ostatni
    zapis bez drogi ponowienia (wpis nieudany tylko przez nowe makro)."""
    path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con, inline=True)
    _makro_przyciskiem(v, "TELESCOP", "EQ6")
    with monkeypatch.context() as m:
        _zajety(m, pliki[1])
        _klik_w(v.drawer.btn_commit)
    assert v.drawer.btn_retry.isVisible()
    _zamknij_widok(v)
    con.close()
    con, v = _restart(path)
    try:
        assert v._undo_btn.isVisible() and v._undo_commity == (1,)
        assert v.drawer.btn_retry.isVisible() and v.drawer.btn_retry.text() == i18n.t("grid.drawer.retry", n=1)
        assert v.drawer.label.text() == (i18n.t("grid.wb.committed_label", n=2)
                                         + i18n.t_plural("grid.drawer.retry_label", 1))
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ AR-367 - przebieg w zdaniu, ponowienie w etykiecie


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_dokonczenie_mowi_ile_teraz_i_ile_w_przebiegu(qapp, tmp_path, monkeypatch, lang):
    """Przebieg przerwany po pierwszym pliku i dokończony: etykieta „Zatwierdzono: 3” liczy przebieg, a zdanie mówi
    obie liczby - „2 zapisane teraz · razem 3 w przebiegu” przed kotwicą obu commitów. Falsyfikator: zdanie
    z samą liczbą operacji obok etykiety przebiegu."""
    i18n.set_lang(lang)
    _path, con, _p = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _przerwany_zapis(v, monkeypatch)
        _klik_w(v.drawer.btn_commit)
        _koniec_biegu(v, "dokończenie zapisu")
        assert v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=3)
        assert v.drawer.result.text() == (i18n.t_plural("grid.wb.applied_now", 2)
                                          + i18n.t_plural("grid.wb.run_total", 3)
                                          + i18n.t("grid.wb.commit_ids", ids="1, 2")), v.drawer.result.text()
        if lang == "en":
            assert not set(v.drawer.result.text()) & _POLSKIE, v.drawer.result.text()
    finally:
        i18n.set_lang("pl")
        _zamknij_widok(v)
        con.close()


def test_zapis_jednej_operacji_bez_czlonu_przebiegu(qapp, tmp_path):
    """Przebieg jednej operacji (zapis bez przerwania): zdanie jak dotąd - „2 zapisane” i kotwica, bez „teraz”
    i bez członu przebiegu. Falsyfikator: człon przebiegu przy każdym zapisie."""
    _path, con, _p = _baza_szuflady(tmp_path, 2)
    v = _widok_szuflady(con, inline=True)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _klik_w(v.drawer.btn_commit)
        assert v.drawer.result.text() == (i18n.t_plural("grid.wb.applied", 2)
                                          + i18n.t("grid.wb.commit_id", id=1)), v.drawer.result.text()
    finally:
        _zamknij_widok(v)
        con.close()


def test_dokonczenie_nazw_mowi_ile_teraz_i_ile_w_przebiegu(qapp, tmp_path, monkeypatch):
    """Nazwy (lustro kart): zmiana trzech nazw przerwana po pierwszym pliku i dokończona - „Przemianowano: 3” obok
    „2 przemianowane teraz · razem 3 w przebiegu”. Falsyfikator: zdanie z samą liczbą operacji."""
    _path, con, _p = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    try:
        v._on_rename_stage(_POL)
        run = v._rename_run_id
        stary = v.model._preview
        brama, doszlo = _brama_po_pierwszym_pliku(monkeypatch)
        _klik_w(v.drawer.btn_commit)
        _anuluj_w_biegu(v, brama, doszlo, stary)
        _klik_w(v.drawer.btn_commit)
        _koniec_biegu(v, "dokończenie zmiany nazw")
        assert v.drawer.label.text() == i18n.t("grid.rename.renamed_label", n=3)
        assert v.drawer.result.text() == (i18n.t_plural("grid.wb.renamed_now", 2)
                                          + i18n.t_plural("grid.wb.run_total", 3)
                                          + i18n.t("grid.wb.run_id", id=run)), v.drawer.result.text()
    finally:
        _zamknij_widok(v)
        con.close()


def test_awaria_dokonczenia_mowi_razem_w_przebiegu(qapp, tmp_path, monkeypatch):
    """Przebieg przerwany po pierwszym pliku, potem „Zatwierdź” reszty, która zapisuje i rzuca: wynik częściowy
    „2 z 2 zapisane, potem błąd: … - „Cofnij” cofa zapisane · razem 3 w przebiegu” obok „Zatwierdzono: 3”.
    Falsyfikator: wynik częściowy z samą liczbą operacji obok etykiety przebiegu."""
    from horreum.gui.wb_worker import WritebackWorker, _zapis_kart

    def _zapisz_i_pada(c, t, now, pr, sc):
        _zapis_kart(c, t, now, pr, sc)
        raise ValueError("złamany inwariant po zapisie")
    _path, con, _p = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _przerwany_zapis(v, monkeypatch)
        monkeypatch.setitem(WritebackWorker._OPS, "commit", _zapisz_i_pada)
        _klik_w(v.drawer.btn_commit)
        _koniec_biegu(v, "dokończenie z awarią")
        assert v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=3)
        assert v.drawer.result.text() == (
            i18n.t_plural("grid.wb.partial_commit", 2, m=2, msg=_prog_error())
            + i18n.t("grid.wb.partial_undo", undo=i18n.t("grid.action.undo"))
            + i18n.t_plural("grid.wb.run_total", 3)
            + i18n.t("grid.wb.commit_ids", ids="1, 2")), v.drawer.result.text()
    finally:
        _zamknij_widok(v)
        con.close()


def test_etykieta_mowi_ile_do_ponowienia(qapp, tmp_path, monkeypatch):
    """Plik zajęty przy zapisie trzech: obok „Ponów nieudane (1)” etykieta „Zatwierdzono: 2 · 1 do ponowienia”,
    kropka „○” bez zmian. Klik ponowienia - etykieta wraca do stagingu bez członu; „Zatwierdź” - „Zatwierdzono: 3”
    i zdanie „1 zapisany teraz · razem 3 w przebiegu”. Falsyfikator: stan „do ponowienia” wyłącznie w przycisku."""
    _path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con, inline=True)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        with monkeypatch.context() as m:
            _zajety(m, pliki[1])
            _klik_w(v.drawer.btn_commit)
        assert v.drawer.label.text() == (i18n.t("grid.wb.committed_label", n=2)
                                         + i18n.t_plural("grid.drawer.retry_label", 1)), v.drawer.label.text()
        assert v.drawer.dot.text() == "○"
        _klik_w(v.drawer.btn_retry)
        assert v.drawer.label.text() == i18n.t_plural("grid.drawer.pending", 1)
        _klik_w(v.drawer.btn_commit)
        assert v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=3)
        assert v.drawer.result.text().startswith(i18n.t_plural("grid.wb.applied_now", 1)
                                                 + i18n.t_plural("grid.wb.run_total", 3)), v.drawer.result.text()
    finally:
        _zamknij_widok(v)
        con.close()


def test_czlon_ponowienia_schodzi_z_przyciskiem(qapp, tmp_path, monkeypatch):
    """„Ponów nieudane”, gdy wpis ponowiono już gdzie indziej (drugie połączenie): przycisk znika, zdanie mówi, że
    nie ma czego ponawiać, a etykieta przy żywym „Cofnij” wraca do „Zatwierdzono: 2” - bez członu „do ponowienia”.
    Falsyfikator: człon etykiety niezdejmowany przy chowaniu przycisku."""
    path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con, inline=True)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        run = v._run_id
        with monkeypatch.context() as m:
            _zajety(m, pliki[1])
            _klik_w(v.drawer.btn_commit)
        assert v.drawer.btn_retry.isVisible()
        con2 = db.connect(path)
        try:
            assert repo.ponow_nieudane(con2, run_id=run, klinga="karty") == 1
        finally:
            con2.close()
        _klik_w(v.drawer.btn_retry)
        assert not v.drawer.btn_retry.isVisible() and v._undo_btn.isVisible()
        assert v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=2), v.drawer.label.text()
    finally:
        _zamknij_widok(v)
        con.close()


def test_etykieta_nazw_mowi_ile_do_ponowienia(qapp, tmp_path, monkeypatch):
    """Nazwy: plik zajęty przy zmianie nazwy - obok „Ponów nieudane (1)” etykieta „Przemianowano: 2 · 1 do
    ponowienia”. Falsyfikator: człon wyłącznie dla kart."""
    _path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con, inline=True)
    try:
        v._on_rename_stage(_POL)
        prawdziwy = writeback.os.rename

        def _rename(src, dst):
            if os.path.basename(src) == pliki[1].name:
                raise OSError(None, "plik używany przez inny proces", src, 32)
            return prawdziwy(src, dst)
        with monkeypatch.context() as m:
            m.setattr(writeback, "_PODMIANA_PONOWIENIA", (0,))
            m.setattr(writeback.os, "rename", _rename)
            _klik_w(v.drawer.btn_commit)
        assert v.drawer.label.text() == (i18n.t("grid.rename.renamed_label", n=2)
                                         + i18n.t_plural("grid.drawer.retry_label", 1)), v.drawer.label.text()
    finally:
        _zamknij_widok(v)
        con.close()


def test_odmiana_nowych_zdan_szuflady():
    """Wpisy mnogie nowych zdań szuflady: PL 1 / 2 / 5 / 12 / 22 (forma 2-4, 5+, -naście i 22 jak 2), EN 1 / inne.
    Falsyfikator: wpis prosty albo forma `few` w miejscu `many`."""
    cofnij = {"undo": "Cofnij"}
    pl = {
        "grid.drawer.last_write": ["1 plik", "2 pliki", "5 plików", "12 plików", "22 pliki"],
        "grid.wb.applied_now": ["1 zapisany teraz", "2 zapisane teraz", "5 zapisanych teraz", "12 zapisanych teraz",
                                "22 zapisane teraz"],
        "grid.wb.renamed_now": ["1 przemianowany teraz", "2 przemianowane teraz", "5 przemianowanych teraz",
                                "12 przemianowanych teraz", "22 przemianowane teraz"],
        "grid.wb.run_total": [f" · razem {n} w przebiegu" for n in (1, 2, 5, 12, 22)],
        "grid.drawer.retry_label": [f" · {n} do ponowienia" for n in (1, 2, 5, 12, 22)],
    }
    en = {
        "grid.drawer.last_write": ["1 file", "2 files", "5 files", "12 files", "22 files"],
        "grid.wb.applied_now": [f"{n} applied now" for n in (1, 2, 5, 12, 22)],
        "grid.wb.renamed_now": [f"{n} renamed now" for n in (1, 2, 5, 12, 22)],
        "grid.wb.run_total": [f" · {n} in the run in total" for n in (1, 2, 5, 12, 22)],
        "grid.drawer.retry_label": [f" · {n} to retry" for n in (1, 2, 5, 12, 22)],
    }
    try:
        for lang, oczekiwane in (("pl", pl), ("en", en)):
            i18n.set_lang(lang)
            for klucz, formy in oczekiwane.items():
                for n, forma in zip((1, 2, 5, 12, 22), formy):
                    zdanie = i18n.t_plural(klucz, n, day=_DZIEN, **cofnij)
                    assert forma in zdanie, (lang, klucz, n, zdanie)
                    if lang == "en":
                        assert not set(zdanie) & _POLSKIE, zdanie
    finally:
        i18n.set_lang("pl")


# ============================================================ AR-361 - zamknięcie przebiegu klikiem, człon „skąd Cofnij”


def test_ponowne_makro_po_przerwanym_stawia_cofnij_z_czlonem(qapp, tmp_path, monkeypatch):
    """Zapis przerwany po pierwszym pliku, potem makro bez żadnej zmiany (same pominięcia) kliknięciem - przebieg
    przy zerze zamyka się, „Cofnij” stoi dla zapisanego pliku, a zdanie gestu mówi, skąd przycisk („1 plik zapisany
    wcześniej”); klik przywraca bajty pliku. Falsyfikatory: ogon makra bez „Cofnij” zamkniętego przebiegu; zdanie
    gestu bez członu (nadpisany w tej samej turze)."""
    _path, con, pliki = _baza_szuflady(tmp_path, 3)
    przed = _bajty(pliki)
    v = _widok_szuflady(con)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        _przerwany_zapis(v, monkeypatch)
        _makro_przyciskiem(v, "EXPTIME", "abc")          # same pominięcia - zero zmian
        assert v._run_id is None and v._undo_btn.isVisible() and v._undo_commity == (1,)
        assert i18n.t_plural("grid.wb.written_before", 1) in v.drawer.result.text(), v.drawer.result.text()
        assert v.drawer.result.text().startswith(i18n.t_plural("grid.macro.staged", 0, s=3)), v.drawer.result.text()
        _klik_w(v._undo_btn)
        _koniec_biegu(v, "cofnięcie")
        assert _bajty(pliki) == przed
    finally:
        _zamknij_widok(v)
        con.close()


def test_ponowny_staging_nazw_klikiem_stawia_cofnij_z_czlonem(qapp, tmp_path, monkeypatch):
    """Zmiana trzech nazw przerwana po pierwszym pliku, potem „Do stagingu” panelu nazw KLIKNIĘCIEM ze wzorem, który
    nazw nie zmienia: przebieg nazw zamyka się, „Cofnij” nazw stoi, a zdanie gestu mówi „1 plik zapisany wcześniej”
    i identyfikator przebiegu. Falsyfikatory: ogon stagingu nazw bez „Cofnij”; zdanie gestu bez członu."""
    _path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    try:
        v._on_rename_stage(_POL)
        run = v._rename_run_id
        stary = v.model._preview
        brama, doszlo = _brama_po_pierwszym_pliku(monkeypatch)
        _klik_w(v.drawer.btn_commit)
        _anuluj_w_biegu(v, brama, doszlo, stary)
        if not v.rename_bar.isVisible():
            _klik_w(v.sel_bar.btn_rename)
        v.rename_bar.template_editor.set_template([{"t": "orig", "re": ".*"}])
        _klik_w(v.rename_bar.btn_stage)
        assert v._undo_mode == "rename" and v._undo_btn.isVisible() and v._undo_rename_run_id == run
        tekst = v.drawer.result.text()
        assert i18n.t_plural("grid.wb.written_before", 1) in tekst and tekst.endswith(
            i18n.t("grid.wb.run_id", id=run)), tekst
    finally:
        _zamknij_widok(v)
        con.close()


@pytest.mark.parametrize("podjecie", [False, True])
def test_dokoncz_zapis_klikiem_menu_stawia_cofnij_z_czlonem(qapp, tmp_path, monkeypatch, podjecie):
    """Zapis w miejscu WŁASNEGO przebiegu, którego re-sync pada (wpis związany czeka), potem „Dokończ zapis” z menu
    tabeli (prawy klik w wiersz): przebieg przy zerze zamyka się, „Cofnij” stoi, a zdanie gestu mówi „1 plik zapisany
    wcześniej” - bez podjęcia innego przebiegu (człon podjęcia pusty) i z nim (człon podjęcia za członem „skąd
    Cofnij”; człon podjęcia z atrapy `_podejmij_po_izolacji` - rdzeń podjęcia ma własne testy). Falsyfikatory: ogon
    gestu bez „Cofnij”; drugie zdanie szuflady wyłącznie przy członie podjęcia (człon „skąd Cofnij” nadpisany)."""
    from horreum.gui.wb_worker import WritebackWorker, _zapis_kart
    from test_gui_izolacja_zapisu import _baza, _fazy
    from test_gui_lead_copy import _prawy_klik, _wiersz
    con, pliki = _baza(tmp_path, n=1, do_zapisu=())
    v = _widok_szuflady(con, inline=True)
    try:
        from test_gui_grid_szuflada import _makro_dodaj
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
        assert _fazy(con) == ["written"] and v._pending_count() == 1
        if podjecie:
            monkeypatch.setattr(v, "_podejmij_po_izolacji", lambda op: "człon podjęcia")
        v.apply_perspective(grid_mod.PRESET_PENDING_FINISH)
        _czekaj(lambda: not v._zbior_w_drodze(), "perspektywa zapisu czekającego")
        _prawy_klik(v, _wiersz(v, pliki[0][1]))
        try:
            assert v._menu_tabeli.isVisible() and v.act_finish_write.isEnabled()
            v.act_finish_write.trigger()
        finally:
            v._menu_tabeli.hide()
        _koniec_biegu(v, "dokończenie zapisu z menu")
        assert v._run_id is None and v._undo_btn.isVisible() and v._undo_commity == (1,)
        czlon = i18n.t_plural("grid.wb.written_before", 1) + (" · człon podjęcia" if podjecie else "")
        assert czlon + i18n.t("grid.wb.commit_id", id=1) in v.drawer.result.text(), v.drawer.result.text()
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ AR-347 - kto rozstrzyga odmowę rekoncyliacji


def _odmowa_obu_nazw(tmp_path, monkeypatch):
    """Zapis nazw rozdarty (`_nazwy_rozdarte`), nowe okno, kopia pliku pod starą nazwą: rekoncyliacja drugim
    połączeniem odmawia `intent_both_names`. Zwraca (ścieżka, połączenie, widok, stara nazwa)."""
    import shutil
    from test_gui_grid_szuflada import _nazwy_rozdarte, _rekoncyliacja_obok
    path, _pliki, _run = _nazwy_rozdarte(tmp_path, monkeypatch)
    con, v = _restart(path)
    stara, nowa = con.execute("SELECT old_path, new_path FROM pending_renames WHERE in_flight IS NOT NULL").fetchone()
    shutil.copyfile(nowa, stara)
    assert [f.reason.code for f in _rekoncyliacja_obok(path)] == ["intent_both_names"]
    return path, con, v, stara


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_odmowa_rekoncyliacji_mowi_raz_kto_rozstrzyga(qapp, tmp_path, monkeypatch, lang):
    """Odmowa rekoncyliacji, którą rozstrzyga człowiek (plik pod obiema nazwami): zwięzłe zdanie szuflady (AR-387)
    mówi drogę człowieka („usuń jedną kopię, potem „Przyjmij nowe””) RAZ, a „rozstrzyga człowiek” wcale - droga to
    mówi. EN tak samo, bez polskich znaków. Falsyfikator: szablon z ogonem (droga albo „rozstrzyga człowiek” za
    drogą)."""
    i18n.set_lang(lang)
    _path, con, v, _stara = _odmowa_obu_nazw(tmp_path, monkeypatch)
    try:
        v.set_writeback_busy(True)
        v.set_writeback_busy(False)
        tekst = v.drawer.result.text()
        assert i18n.t("grid.drawer.names_way_taken").removeprefix(" - ") not in tekst, tekst
        assert tekst.count(i18n.t("grid.drawer.names_way_both", receive=i18n.t("pipeline.receive"),
                                  nav=i18n.t("nav.dostawa"))) == 1, tekst
        if lang == "en":
            assert not set(tekst) & _POLSKIE, tekst
    finally:
        i18n.set_lang("pl")
        _zamknij_widok(v)
        con.close()


def test_odmowa_przejsciowa_obiecuje_rekoncyliacje(qapp, tmp_path, monkeypatch):
    """Odmowa PRZEJŚCIOWA (dysk nie odpowiada przy rekoncyliacji - `disk_silent`): zdanie mówi powód i obietnicę,
    że zamiar rozstrzygnie „Przyjmij nowe” albo kolejny zapis nazw - bez „rozstrzyga człowiek”, które przy tym
    kodzie było fałszem. Falsyfikator: kod przejściowy jak odmowa człowieka (bez obietnicy)."""
    from horreum import scan
    from test_gui_grid_szuflada import _droga_nazw, _nazwy_rozdarte, _rekoncyliacja_obok
    path, _pliki, _run = _nazwy_rozdarte(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        with monkeypatch.context() as m:
            m.setattr(scan, "_mtime_iso", lambda st: (_ for _ in ()).throw(OSError(64, "zerwany udział")))
            assert [f.reason.code for f in _rekoncyliacja_obok(path)] == ["disk_silent"]
        v.set_writeback_busy(True)
        v.set_writeback_busy(False)
        tekst = v.drawer.result.text()
        assert _droga_nazw() in tekst and "rozstrzyga człowiek" not in tekst, tekst
        assert i18n.t("grid.drawer.names_held_refused", reason="")[:20] in tekst, tekst
    finally:
        _zamknij_widok(v)
        con.close()


def test_kody_odmowy_rozdzielone_na_przejsciowe_i_drogi():
    """Każdy kod odmowy rekoncyliacji ma w szufladzie albo obietnicę następnej rekoncyliacji (zbiór przejściowych),
    albo drogę człowieka z katalogu (PL i EN) - rozłącznie. Falsyfikator: nowy kod odmowy bez drogi (zdanie
    szuflady padłoby przy pierwszej takiej odmowie)."""
    from horreum.gui.i18n_catalog import CATALOG
    from horreum.item_reasons import KODY_ODMOWY_REKONCYLIACJI, KODY_PRZEJSCIOWE_REKONCYLIACJI
    drogi = grid_mod.FramesView._DROGI_ODMOWY_NAZW
    assert not set(drogi) & KODY_PRZEJSCIOWE_REKONCYLIACJI
    assert set(drogi) | KODY_PRZEJSCIOWE_REKONCYLIACJI == KODY_ODMOWY_REKONCYLIACJI
    for klucz in drogi.values():
        assert set(CATALOG[klucz]) >= {"pl", "en"}, klucz


def test_zdanie_wylaczonych_z_jednej_migawki(qapp, tmp_path, monkeypatch):
    """Odmowa rekoncyliacji widoczna przy odświeżeniu, a między odczytem przebiegów nazw w locie i odczytem powodów
    drugie połączenie rozstrzyga zamiar (kopia usunięta, rekoncyliacja przechodzi - bariera w
    `queries.powody_zamiarow_nazw`): zdanie mówi odmowę ze stanu sprzed bariery, a nie etykietę zamiaru w locie
    z obietnicą zamiaru już rozstrzygniętego. Falsyfikator: trzy odczyty zdania bez transakcji odczytu."""
    from horreum.gui import queries as queries_mod
    from test_gui_grid_szuflada import _rekoncyliacja_obok
    path, con, v, stara = _odmowa_obu_nazw(tmp_path, monkeypatch)
    prawdziwe, bariera = queries_mod.powody_zamiarow_nazw, []

    def _z_bariera(c, run_ids):
        if not bariera:
            bariera.append(1)
            os.remove(stara)
            assert [f.status for f in _rekoncyliacja_obok(path)] == ["reconciled"]
        return prawdziwe(c, run_ids)
    try:
        monkeypatch.setattr(queries_mod, "powody_zamiarow_nazw", _z_bariera)
        v.set_writeback_busy(True)
        v.set_writeback_busy(False)
        assert bariera, "bariera nie zadziałała - test nic by nie mierzył"
        assert i18n.t("grid.drawer.names_way_both", receive=i18n.t("pipeline.receive"),
                      nav=i18n.t("nav.dostawa")) in v.drawer.result.text(), v.drawer.result.text()
    finally:
        monkeypatch.undo()
        _zamknij_widok(v)
        con.close()


# ============================================================ AR-347 - wielokropek w środku zdania szuflady


def _zdanie_pliku_zajetego():
    return (i18n.t_plural("grid.wb.applied", 3) + " · " + i18n.t_plural("grid.wb.errors", 1)
            + i18n.t("grid.wb.detail_sep", detail=i18n.t("objchg.reason.busy")
                     + " (X:\\L\\NGC7000\\2024-03-15\\RC8\\Ha\\sz1.fits)")
            + i18n.t("grid.wb.commit_id", id=1))


def test_elizja_zdania_zostawia_poczatek_i_kotwice(qapp):
    """Zdanie wyniku z długą ścieżką pliku zajętego w polu węższym niż zdanie: początek (liczby wyniku) i koniec
    (nazwa pliku i kotwica „(commit 1)”) zostają, wielokropek stoi w środku. Struktura, nie piksele (offscreen).
    Falsyfikator: elizja w prawo (kotwica za wielokropkiem)."""
    from PySide6.QtGui import QFontMetrics
    from horreum.gui.grid_selection import _ZdanieWyniku, elizja_zdania
    fm = QFontMetrics(_ZdanieWyniku("").font())
    zdanie = _zdanie_pliku_zajetego()
    wynik = elizja_zdania(fm, zdanie, int(fm.horizontalAdvance(zdanie) * 0.4))
    assert wynik != zdanie and "…" in wynik, wynik
    assert wynik.endswith("sz1.fits)" + i18n.t("grid.wb.commit_id", id=1)), wynik
    assert wynik.startswith(i18n.t_plural("grid.wb.applied", 3)), wynik


def test_pole_wyniku_maluje_przez_elizje_zdania(qapp, tmp_path, monkeypatch):
    """Pole wyniku szuflady maluje zdanie JEDNĄ regułą elizji (`grid_selection.elizja_zdania`) do szerokości
    prostokąta zdania (bez wcięcia wskaźnika szczegółu). Falsyfikator: `paintEvent` z elizją wprost."""
    from horreum.gui import grid_selection
    _path, con, _p = _baza_szuflady(tmp_path, 1)
    v = _widok_szuflady(con, inline=True)
    prawdziwa, wolania = grid_selection.elizja_zdania, []
    try:
        v.drawer.result.ustaw(_zdanie_pliku_zajetego(), "szczegół")
        monkeypatch.setattr(grid_selection, "elizja_zdania",
                            lambda fm, tekst, szer: wolania.append((tekst, szer)) or prawdziwa(fm, tekst, szer))
        v.drawer.result.grab()
        assert wolania and wolania[-1] == (v.drawer.result.text(), v.drawer.result._prostokat_tekstu().width())
    finally:
        monkeypatch.undo()
        _zamknij_widok(v)
        con.close()


# ============================================================ AR-387 - zdanie odmowy rekoncyliacji mówi nazwy plików


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_odmowa_obu_nazw_mowi_nazwy_plikow_pelne_sciezki_w_szczegole(qapp, tmp_path, monkeypatch, lang):
    """Odmowa rekoncyliacji „plik pod obiema nazwami” (prawdziwy rdzeń): zdanie szuflady mówi NAZWY obu plików, pełnej
    ścieżki w nim nie ma - stoi w szczególe zdania (wskaźnik i podpowiedź pola) wierszem pełnego powodu. EN tak samo.
    Falsyfikatory: zdanie z pełną formą powodu (wielokropek w środku zjadał właśnie nazwy); szczegół niepołożony."""
    from horreum.gui.wb_worker import tekst_powodu
    from horreum.item_reasons import z_bazy
    from horreum.gui import queries
    i18n.set_lang(lang)
    _path, con, v, stara = _odmowa_obu_nazw(tmp_path, monkeypatch)
    try:
        v.set_writeback_busy(True)
        v.set_writeback_busy(False)
        tekst = v.drawer.result.text()
        (w,), _czekajace = queries.powody_zamiarow_nazw(con, {r[0] for r in con.execute(
            "SELECT run_id FROM pending_renames WHERE in_flight IS NOT NULL")})
        nowa = con.execute("SELECT new_path FROM pending_renames WHERE in_flight IS NOT NULL").fetchone()[0]
        assert os.path.basename(stara) in tekst and os.path.basename(nowa) in tekst, tekst
        assert stara not in tekst and nowa not in tekst, tekst
        assert v.drawer.result.szczegol() == tekst_powodu(z_bazy(w["reason"], w["reason_code"], w["reason_args"]))
        assert stara in v.drawer.result.szczegol() and stara in v.drawer.result.toolTip()
        if lang == "en":
            assert not set(tekst) & _POLSKIE, tekst
    finally:
        i18n.set_lang("pl")
        _zamknij_widok(v)
        con.close()


def test_odmowa_rekoncyliacji_padla_mowi_tekst_systemu_przez_czytelny_powod(qapp, tmp_path, monkeypatch):
    """Szew krótkiej formy z `czytelny_powod`: rekoncyliacja pada wyjątkiem systemu spoza klas (WinError 87 ze ścieżką
    w zapisie `repr`; atrapa wyłącznie awarii - prawdziwy rdzeń zapisu i rekoncyliacji). Zdanie szuflady mówi tekst
    systemu TĄ SAMĄ drogą co pełna forma: oczekiwanie liczy `czytelny_powod` w biegu testu, więc test mówi prawdę przed
    i po zmianie tej funkcji. Falsyfikator: krótka forma z surową prozą parametru (podwojone ukośniki `repr`)."""
    from horreum.gui.wb_worker import czytelny_powod
    from horreum.item_reasons import z_bazy
    from test_gui_grid_szuflada import _nazwy_rozdarte, _rekoncyliacja_obok
    path, _pliki, run = _nazwy_rozdarte(tmp_path, monkeypatch)
    con, v = _restart(path)
    try:
        with monkeypatch.context() as m:
            m.setattr(writeback, "_location_rename",
                      lambda c, lid: (_ for _ in ()).throw(OSError(22, "Parametr jest niepoprawny", r"X:\L\a.fits", 87)))
            assert [f.reason.code for f in _rekoncyliacja_obok(path)] == ["reconcile_failed"]
        from horreum.gui import queries
        (w,), _czekajace = queries.powody_zamiarow_nazw(con, {run})
        detail = dict(z_bazy(w["reason"], w["reason_code"], w["reason_args"]).params)["detail"]
        assert "\\\\" in detail, detail                  # tekst systemu ze ścieżką w zapisie `repr`
        v.set_writeback_busy(True)
        v.set_writeback_busy(False)
        tekst = v.drawer.result.text()
        assert czytelny_powod(detail) in tekst and "\\\\" not in tekst, tekst
        assert v.drawer.result.szczegol() == "", v.drawer.result.szczegol()   # bez ścieżek w parametrach - bez szczegółu
    finally:
        _zamknij_widok(v)
        con.close()
