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
