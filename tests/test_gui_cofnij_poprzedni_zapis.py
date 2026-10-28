"""Szuflada Zbiorów - „Cofnij poprzedni zapis” (AR-389, decyzja CEO): po „Cofnij” przebiegu kart, które cofnęło się
w całości, ten sam przycisk cofa starszy zapis TYCH SAMYCH plików - etykieta „Cofnij poprzedni zapis (commit N)”, zdanie
„Starszy zapis kart tych plików z RRRR-MM-DD (commit N)”; nigdy dowolny starszy przebieg, jeden krok (starszy łańcuch -
CLI `header-fix --undo`). Reguła wyboru - `queries.poprzedni_zapis_kart`; przycisk - `FramesView._postaw_cofnij_poprzedni`,
straże gestu - `grid._PrzyciskCofnij`.

Kliki prawdziwe: `QTest` na widżecie, a tam, gdzie liczy się droga spontaniczna (wykrywanie dwukliku, gest przytrzymany
przez przezbrojenie) - na `windowHandle()` okna. Zapisy poprzednich sesji prawdziwym rdzeniem (jak okno kart albo CLI),
cofnięcia klikiem w szufladzie z prawdziwym wątkiem zapisu, zmiany z zewnątrz bajtami albo `fits.setval` i skanem. Bez
podmiany reguły klasy cofnięcia - restart po dwóch cofnięciach atomowych stoi na regule klasy z rodowodem stanu lokacji
(AR-421), nie na warunkach wyboru poprzednika. TELESCOP: RC8 - stan wyjściowy."""
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from astropy.io import fits
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from horreum import db, repo, scan, writeback
from horreum.gui import i18n, queries
from horreum.gui.wb_worker import WritebackWorker

from test_gui_grid_szuflada import (_baza_szuflady, _blokada_obca, _klik_w, _makro_przyciskiem, _nazwy_czekaja,
                                    _restart, _trzyma_blokade, _widok_szuflady, _zamknij_widok)
from test_gui_pasek_szczegol import _czekaj
from test_gui_szuflada_przebieg import _DZIEN, _POLSKIE, _bez_cofnij, _koniec_biegu

_NOW = "2026-07-03T14:00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _tel(p):
    return fits.getval(str(p), "TELESCOP")


def _staging(con, run_id, wiersze, wartosc):
    """Wpisy TELESCOP = `wartosc` przebiegu `run_id` na plikach nr `wiersze` (odcisk i wartość z bieżącego stanu)."""
    for w in wiersze:
        lid, sciezka, hh = con.execute("SELECT id, path, header_hash FROM location ORDER BY id LIMIT 1 OFFSET ?",
                                       (w,)).fetchone()
        repo.stage_pending(con, run_id=run_id, location_id=lid, keyword="TELESCOP", idx=0, op="set",
                           old_value=fits.getval(sciezka, "TELESCOP"), new_value=wartosc, new_type="str",
                           new_comment=None, expected_header_hash=hh)


def _commity(con, run_id):
    return tuple(r[0] for r in con.execute("SELECT id FROM commits WHERE run_id = ? ORDER BY id", (run_id,)))


def _zapis(con, run_id, wiersze, wartosc, *, inplace=True):
    """Przebieg kart `run_id` zapisany prawdziwym rdzeniem (w miejscu albo drogą atomową). Zwraca jego commity."""
    _staging(con, run_id, wiersze, wartosc)
    wynik = writeback.commit(con, run_id, now=_NOW, inplace=inplace)
    assert wynik.applied and not wynik.failed, wynik
    return _commity(con, run_id)


def _skan(con, p):
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=_NOW, summary=scan.ScanSummary(),
                       pochodzenie=repo.ZEWNETRZNE)


def _starszy(c1):
    """Człon zdania szuflady przy „Cofnij poprzedni zapis” z kotwicą commitu."""
    return " · " + i18n.t("grid.drawer.older_write", day=_DZIEN) + i18n.t("grid.wb.commit_id", id=c1)


def _po_oknie(v):
    """Koniec okna przezbrojenia „Cofnij poprzedni zapis” (przycisk znów czynny) - prawdziwy zegar."""
    _czekaj(lambda: v._undo_btn.isEnabled(), "koniec okna przezbrojenia")


def _klik_cofnij(v, opis):
    """Klik „Cofnij” człowieka, który czeka, aż przycisk będzie czynny (po oknie przezbrojenia)."""
    _po_oknie(v)
    _klik_w(v._undo_btn)
    _koniec_biegu(v, opis)


def _odczekaj(ms):
    from test_gui_pasek_szczegol import _czekaj_ms
    _czekaj_ms(ms)


def _dwa_zapisy(tmp_path, *, inplace=True):
    """Restart po dwóch przebiegach kart na jednym pliku (R1 RC8 → EQ6, R2 EQ6 → EQ8): `(path, con, v, p, przed, c1)`,
    szuflada z „Cofnij” przebiegu R2."""
    path, con, (p,) = _baza_szuflady(tmp_path, 1)
    przed = p.read_bytes()
    (c1,) = _zapis(con, "R1", [0], "EQ6", inplace=inplace)
    (c2,) = _zapis(con, "R2", [0], "EQ8", inplace=inplace)
    con.close()
    con, v = _restart(path)
    assert v._undo_mode == "macro" and v._undo_commity == (c2,)
    return path, con, v, p, przed, c1


def _po_cofnieciu_r2(tmp_path, **kw):
    """`_dwa_zapisy` + klik „Cofnij” (R2): szuflada z „Cofnij poprzedni zapis” przebiegu R1."""
    path, con, v, p, przed, c1 = _dwa_zapisy(tmp_path, **kw)
    _klik_cofnij(v, "cofnięcie R2")
    assert _tel(p) == "EQ6" and v._undo_mode == "poprzedni" and v._undo_commity == (c1,), v.drawer.result.text()
    return path, con, v, p, przed, c1


def _brama_cofniecia(monkeypatch):
    """Cofnięcie przebiegu w wątku zapisu czeka na bramę testu; `wolania` - cele kolejnych wołań `undo_run`."""
    brama, wolania = threading.Event(), []
    prawdziwy = WritebackWorker._OPS["undo_run"]

    def _za_brama(c, t, now, pr, sc):
        wolania.append(t)
        brama.wait(30)
        return prawdziwy(c, t, now, pr, sc)
    monkeypatch.setitem(WritebackWorker._OPS, "undo_run", _za_brama)
    return brama, wolania


# ============================================================ przycisk po „Cofnij” i klik


@pytest.mark.parametrize("lang", ["pl", "en"])
@pytest.mark.parametrize("inplace", [True, False], ids=["w_miejscu", "atomowo"])
def test_cofnij_stawia_cofnij_poprzedni_zapis_a_klik_przywraca_plik_sprzed_obu(qapp, tmp_path, inplace, lang):
    """Dwa przebiegi kart na jednym pliku, restart, klik „Cofnij” (R2): ten sam przycisk mówi „Cofnij poprzedni zapis
    (commit 1)” z zakresem R1 zamrożonym teraz, zdanie cofnięcia kończy się „Starszy zapis kart tych plików z …
    (commit 1)”, etykieta „Zatwierdzono: 1”, Zatwierdź/Odrzuć schowane, blokada szuflady oddana. Drugi klik przywraca
    bajty sprzed obu zapisów, a przycisk znika - bez trzeciego kroku. EN bez polskich znaków. Falsyfikatory: ogon
    cofnięcia bez gałęzi poprzedniego zapisu (pustostan); etykieta „Cofnij” przy nowym celu."""
    i18n.set_lang(lang)
    path, con, v, p, przed, c1 = _dwa_zapisy(tmp_path, inplace=inplace)
    try:
        _klik_cofnij(v, "cofnięcie R2")
        assert _tel(p) == "EQ6"
        assert v._undo_btn.isVisible() and v._undo_mode == "poprzedni" and v._undo_commity == (c1,)
        assert v._undo_btn.text() == i18n.t("grid.drawer.undo_older", id=c1)
        assert v.drawer.result.text().endswith(_starszy(c1)), v.drawer.result.text()
        assert v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=1)
        assert not v.drawer.btn_commit.isVisible() and not _trzyma_blokade(v)
        if lang == "en":
            assert not set(v.drawer.result.text() + v._undo_btn.text()) & _POLSKIE, v.drawer.result.text()
        _klik_cofnij(v, "cofnięcie poprzedniego zapisu")
        assert p.read_bytes() == przed
        assert _bez_cofnij(v) and v._undo_mode is None
    finally:
        i18n.set_lang("pl")
        _zamknij_widok(v)
        con.close()


def test_cofnij_zapisu_z_tej_sesji_stawia_cofnij_poprzedni(qapp, tmp_path):
    """Starszy przebieg zapisany wcześniej (okno kart, CLI), nowszy - makrem i „Zatwierdź” w tej sesji: „Cofnij” po
    zapisie w sesji też stawia „Cofnij poprzedni zapis” - reguła nie zależy od tego, skąd przyszło „Cofnij”.
    Falsyfikator: gałąź wyłącznie dla „Cofnij” ostatniego zapisu po otwarciu bazy."""
    _path, con, (p,) = _baza_szuflady(tmp_path, 1)
    (c1,) = _zapis(con, "R1", [0], "EQ6")
    v = _widok_szuflady(con)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ8")
        _klik_w(v.drawer.btn_commit)
        _koniec_biegu(v, "zapis w sesji")
        assert _tel(p) == "EQ8" and v._undo_mode == "macro"
        _klik_cofnij(v, "cofnięcie zapisu z sesji")
        assert _tel(p) == "EQ6" and v._undo_mode == "poprzedni" and v._undo_commity == (c1,)
        assert v._undo_btn.text() == i18n.t("grid.drawer.undo_older", id=c1)
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ tylko starszy zapis TYCH SAMYCH plików, bez szukania dalej


@pytest.mark.parametrize("r1, r2", [([0, 1], [0]), ([1], [0]), ([0], [0, 1])],
                         ids=["szerszy", "rozlaczny", "podzbior"])
def test_poprzednik_na_innych_plikach_niz_cofniety_bez_cofnij_poprzedni(qapp, tmp_path, r1, r2):
    """Starszy przebieg zapisał inne pliki niż cofnięty: także plik, którego cofnięty nie dotknął (R1 na 0 i 1, R2 na
    0), wyłącznie inne pliki (R1 na 1, R2 na 0) albo tylko część plików cofniętego (R1 na 0, R2 na 0 i 1 - najwęższe
    odczytanie „tych samych plików”: zdanie o „tych plikach” mówiłoby o pliku, którego klik nie cofa). Po „Cofnij”
    przycisk znika. Falsyfikatory: lokacje poprzednika jako podzbiór cofniętego zamiast równości; bez warunku
    lokacji."""
    path, con, pliki = _baza_szuflady(tmp_path, 2)
    _zapis(con, "R1", r1, "EQ6")
    _zapis(con, "R2", r2, "EQ8")
    con.close()
    con, v = _restart(path)
    try:
        _klik_cofnij(v, "cofnięcie R2")
        assert _tel(pliki[0]) == ("EQ6" if 0 in r1 else "RC8")
        assert _bez_cofnij(v) and v._undo_mode is None
    finally:
        _zamknij_widok(v)
        con.close()


def test_poprzednik_cofniety_kiedys_w_czesci_bez_cofnij_poprzedni(qapp, tmp_path):
    """R1 zapisał pliki A i B (A0/B0 → A1/B1); B zmieniony z zewnątrz (skan), cofnięcie R1 przywraca A0, B odmawia;
    oba pliki wracają z zewnątrz do A1/B1 (skan), R2 zapisuje oba i cofa się w całości (A1/B1). Zakres R1 obejmuje dziś
    tylko B (cofnięcie A ma trwały dowód zakończenia) - klik „Cofnij poprzedni” dałby A1/B0, stan, którego nigdy nie
    było. Przycisk nie staje. Falsyfikator: poprzednik bez warunku „zakres obejmuje każdą jego lokację”."""
    path, con, (pa, pb) = _baza_szuflady(tmp_path, 2)
    (c1,) = _zapis(con, "R1", [0, 1], "EQ6")
    po_r1 = [pa.read_bytes(), pb.read_bytes()]
    fits.setval(str(pb), "OBSERVER", value="obcy")
    _skan(con, pb)
    u = writeback.undo_run(con, (c1,), now=_NOW)
    assert _tel(pa) == "RC8" and [fr.path for fr in u.blocked] == [str(pb)] and not u.already, u.blocked
    for p, bajty in zip((pa, pb), po_r1):
        p.write_bytes(bajty)
        _skan(con, p)
    _zapis(con, "R2", [0, 1], "EQ8")
    con.close()
    con, v = _restart(path)
    try:
        _klik_cofnij(v, "cofnięcie R2")
        assert [_tel(pa), _tel(pb)] == ["EQ6", "EQ6"]
        zakres_r1 = writeback.przebieg_do_cofniecia(con, "R1")
        assert zakres_r1 is not None and zakres_r1.zatwierdzone == 1, "scena nic by nie mierzyła"
        assert _bez_cofnij(v) and v._undo_mode is None
    finally:
        _zamknij_widok(v)
        con.close()


def test_poprzednik_nadpisany_z_zewnatrz_bez_cofnij_i_bez_szukania_dalej(qapp, tmp_path):
    """R0 RC8 → EQ6, R1 EQ6 → EQ8, potem bajty wyniku R0 wracają z zewnątrz (skan), R2 EQ6 → C14. Po „Cofnij” (R2) plik
    ma wynik R0, ale bezpośrednio poprzedni zapis to R1, którego w pliku nie ma: przycisk znika - R0 byłby „dowolnym
    starszym przebiegiem”. Warunek wstępny: R0 sam przeszedłby warunki (inaczej test nic by nie mierzył).
    Falsyfikatory: filtr odcisku przed wyborem poprzednika; szukanie dalej po porażce warunku (oba stawiają R0)."""
    path, con, (p,) = _baza_szuflady(tmp_path, 1)
    _zapis(con, "R0", [0], "EQ6")
    po_r0 = p.read_bytes()
    _zapis(con, "R1", [0], "EQ8")
    p.write_bytes(po_r0)
    _skan(con, p)
    _zapis(con, "R2", [0], "C14")
    con.close()
    con, v = _restart(path)
    try:
        _klik_cofnij(v, "cofnięcie R2")
        assert p.read_bytes() == po_r0
        assert _bez_cofnij(v) and v._undo_mode is None
        zakres_r0 = writeback.przebieg_do_cofniecia(con, "R0")
        assert zakres_r0 is not None and zakres_r0.cofnij, "R0 bez zakresu - scena nic by nie mierzyła"
    finally:
        _zamknij_widok(v)
        con.close()


def test_poprzednik_ze_zmiany_obiektu_bez_cofnij_poprzedni(qapp, tmp_path):
    """Starszy zapis pliku to commit przebiegu zmiany obiektu (`object_change_run` - ma własne okno i wiersz
    Porządków): po „Cofnij” przebiegu kart przycisk znika. Falsyfikator: bez warunku zmiany obiektu."""
    path, con, (p,) = _baza_szuflady(tmp_path, 1)
    with con:
        con.execute("INSERT INTO object_change_run (run_id, mode, created_at) VALUES ('OC', 'align', ?)", (_NOW,))
    _zapis(con, "OC", [0], "EQ6")
    _zapis(con, "R2", [0], "EQ8")
    con.close()
    con, v = _restart(path)
    try:
        _klik_cofnij(v, "cofnięcie R2")
        assert _tel(p) == "EQ6" and _bez_cofnij(v) and v._undo_mode is None
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ jeden krok - w sesji i po restarcie


@pytest.mark.parametrize("inplace", [True, False], ids=["w_miejscu", "atomowo"])
def test_trzy_zapisy_jeden_krok_w_sesji_i_po_restarcie(qapp, tmp_path, inplace):
    """Trzy przebiegi kart na jednym pliku (RC8 → EQ6 → EQ8 → C14): „Cofnij”, „Cofnij poprzedni zapis” - plik z wynikiem
    pierwszego przebiegu, przycisk znika (najstarszego szuflada nie proponuje). Po restarcie szuflada nie stawia
    niczego, a plik zostaje bez zmian. Po cofnięciach atomowych restart stoi na regule klasy z rodowodem (AR-421):
    cofnięcie R2, a po nim R1 z innego przebiegu - R2 „już cofnięty”. Falsyfikatory: kolejny poprzednik po trybie
    poprzedniego zapisu (trzeci krok w sesji); reguła klasy bez łańcucha między przebiegami (restart stawia „Cofnij”
    R2)."""
    path, con, (p,) = _baza_szuflady(tmp_path, 1)
    _zapis(con, "R0", [0], "EQ6", inplace=inplace)
    po_r0 = p.read_bytes()
    (c1,) = _zapis(con, "R1", [0], "EQ8", inplace=inplace)
    _zapis(con, "R2", [0], "C14", inplace=inplace)
    con.close()
    con, v = _restart(path)
    try:
        _klik_cofnij(v, "cofnięcie R2")
        assert _tel(p) == "EQ8" and v._undo_mode == "poprzedni" and v._undo_commity == (c1,)
        _klik_cofnij(v, "cofnięcie R1")
        assert p.read_bytes() == po_r0
        assert _bez_cofnij(v) and v._undo_mode is None
    finally:
        _zamknij_widok(v)
        con.close()
    con, v = _restart(path)
    try:
        assert _bez_cofnij(v) and v._undo_mode is None
        assert queries.ostatni_zapis_szuflady(con) is None
        assert p.read_bytes() == po_r0
    finally:
        _zamknij_widok(v)
        con.close()


def test_cofniety_zapis_po_objezdzie_z_zewnatrz_nie_wraca_po_restarcie(qapp, tmp_path):
    """Drogą atomową: C1 RC8 → EQ6 (R1), C2 EQ6 → RC8 (R2). „Cofnij” C2 (plik EQ6), potem plik zmieniany z zewnątrz:
    EQ8 i z powrotem bajty po cofnięciu (dwa skany), „Cofnij poprzedni zapis” C1 (plik RC8). Po restarcie zakres R2
    pusty, szuflada bez przycisku, plik bez trzeciej zmiany - zapis C2 jest „już cofnięty” według historii pliku
    (reguła klasy z rodowodem, AR-421), choć plik ma jego wynik. Falsyfikator: reguła klasy bez łańcucha między
    przebiegami - restart stawia „Cofnij” C2, a klik przywróciłby EQ6, wynik zapisu, który człowiek cofnął."""
    path, con, (p,) = _baza_szuflady(tmp_path, 1)
    (c1,) = _zapis(con, "R1", [0], "EQ6", inplace=False)
    _zapis(con, "R2", [0], "RC8", inplace=False)
    con.close()
    con, v = _restart(path)
    try:
        _klik_cofnij(v, "cofnięcie C2")
        assert _tel(p) == "EQ6" and v._undo_mode == "poprzedni" and v._undo_commity == (c1,)
        po_cofnieciu = p.read_bytes()
        fits.setval(str(p), "TELESCOP", value="EQ8")
        _skan(con, p)
        p.write_bytes(po_cofnieciu)
        _skan(con, p)
        assert _tel(p) == "EQ6"
        _klik_cofnij(v, "cofnięcie C1")
        assert _tel(p) == "RC8" and _bez_cofnij(v)
        po_obu = p.read_bytes()
    finally:
        _zamknij_widok(v)
        con.close()
    con, v = _restart(path)
    try:
        assert writeback.przebieg_do_cofniecia(con, "R2") is None
        assert queries.ostatni_zapis_szuflady(con) is None and _bez_cofnij(v)
        assert p.read_bytes() == po_obu
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ podwójny klik i gest sprzed przezbrojenia


def _srodek_w_oknie(v):
    return v._undo_btn.mapTo(v.window(), v._undo_btn.rect().center())


def _klik_okna(v, delay=-1):
    """Klik lewym drogą spontaniczną (`windowHandle()` - QGuiApplication wykrywa dwuklik) w punkt przycisku."""
    QTest.mouseClick(v.window().windowHandle(), Qt.LeftButton, Qt.KeyboardModifier.NoModifier, _srodek_w_oknie(v),
                     delay)


def test_dwuklik_cofnij_cofa_jeden_przebieg(qapp, tmp_path):
    """Dwuklik na „Cofnij” drogą spontaniczną (`QTest.mouseDClick` na `windowHandle()` - drugie naciśnięcie Qt doręcza
    jako `MouseButtonDblClick`), cofnięcie szybsze niż dwuklik (wątek zapisu inline): cofa się wyłącznie R2, przycisk
    stoi z nowym celem, wygaszony na okno przezbrojenia. Falsyfikator: przycisk bez okna przezbrojenia i bez połknięcia
    dwukliku - drugie naciśnięcie klika „Cofnij poprzedni zapis” i cofa też R1."""
    path, con, v, p, _przed, c1 = _dwa_zapisy(tmp_path)
    try:
        v._writeback_async = False
        QTest.mouseDClick(v.window().windowHandle(), Qt.LeftButton, Qt.KeyboardModifier.NoModifier,
                          _srodek_w_oknie(v), 10)
        _koniec_biegu(v, "dwuklik")
        assert _tel(p) == "EQ6"
        assert v._undo_mode == "poprzedni" and v._undo_commity == (c1,) and v._undo_btn.isVisible()
    finally:
        _zamknij_widok(v)
        con.close()


@pytest.mark.parametrize("gest", ["dwa_kliki_700_ms", "trojklik"])
def test_klik_na_upewnienie_w_oknie_przezbrojenia_nie_cofa_poprzedniego(qapp, tmp_path, gest):
    """Drugi klik w tym samym punkcie 700 ms po „Cofnij” (pomiar natywny: przycisk zmienia cel po 0,1 s pod kursorem)
    albo trójklik (trzecie naciśnięcie to zwykły klik): okno przezbrojenia trzyma przycisk wygaszony - cofa się
    wyłącznie R2. Po oknie przycisk znów czynny, a klik cofa R1. Falsyfikator: przezbrojenie bez okna."""
    path, con, v, p, przed, c1 = _dwa_zapisy(tmp_path)
    try:
        v._writeback_async = False
        if gest == "trojklik":
            QTest.mouseDClick(v.window().windowHandle(), Qt.LeftButton, Qt.KeyboardModifier.NoModifier,
                              _srodek_w_oknie(v), 10)
            # Trzecie naciśnięcie w interwale dwukliku: po dwukliku Qt liczy je jako zwykłe naciśnięcie. Domyślne
            # opóźnienie - zwolnienie odsuwa zegar QTest o interwał, więc klik po oknie nie zleje się w dwuklik.
            _klik_okna(v)
        else:
            _klik_okna(v)
            _odczekaj(700)
            assert not v._undo_btn.isEnabled() and v._undo_mode == "poprzedni"
            _klik_okna(v)
        _koniec_biegu(v, gest)
        assert _tel(p) == "EQ6" and v._undo_mode == "poprzedni" and v._undo_commity == (c1,)
        _po_oknie(v)
        _klik_okna(v)
        _koniec_biegu(v, "klik po oknie")
        assert p.read_bytes() == przed and _bez_cofnij(v)
    finally:
        _zamknij_widok(v)
        con.close()


def test_spacja_dwa_razy_przy_fokusie_cofa_jeden_przebieg(qapp, tmp_path):
    """Fokus na „Cofnij”, spacja dwa razy szybko (drogą okna - do widżetu z fokusem): cofa się wyłącznie R2. W oknie
    przezbrojenia fokus schodzi z przycisku (wygaszenie przeniosłoby go na następny widżet, a druga spacja trafiłaby tam)
    i wraca po oknie - trzecia spacja cofa R1. Falsyfikatory: przezbrojenie bez okna (druga spacja cofa R1); okno bez
    zdjęcia fokusu (fokus ląduje na innym widżecie i nie wraca)."""
    path, con, v, p, przed, c1 = _dwa_zapisy(tmp_path)
    try:
        v._writeback_async = False
        v.activateWindow()
        QApplication.processEvents()
        v._undo_btn.setFocus()
        assert v._undo_btn.hasFocus(), "fokus nie stanął na przycisku - test nic by nie mierzył"
        okno = v.window().windowHandle()
        QTest.keyClick(okno, Qt.Key_Space)
        QTest.keyClick(okno, Qt.Key_Space)
        _koniec_biegu(v, "dwie spacje")
        assert _tel(p) == "EQ6" and v._undo_mode == "poprzedni" and v._undo_commity == (c1,)
        assert v.window().focusWidget() is None
        _po_oknie(v)
        assert v._undo_btn.hasFocus()
        QTest.keyClick(okno, Qt.Key_Space)
        _koniec_biegu(v, "spacja po oknie")
        assert p.read_bytes() == przed and _bez_cofnij(v)
    finally:
        _zamknij_widok(v)
        con.close()


@pytest.mark.parametrize("koniec", ["zapis_skonczony_w_oknie", "zapis_trwa_po_oknie"])
def test_zapis_innej_powierzchni_w_oknie_nie_wlacza_przycisku(qapp, tmp_path, koniec):
    """Cudzy zapis plików (okno „Napraw nagłówek…” - `set_writeback_busy`) w oknie przezbrojenia: jego koniec w oknie
    nie włącza przycisku przed końcem okna, a okno skończone w biegu zapisu nie włącza go wbrew niemu - przycisk
    staje się czynny dopiero, gdy minęło okno I skończył się zapis. Falsyfikatory: prośba widoku o stan stosowana od
    razu w oknie; koniec okna bez pamięci prośby widoku."""
    path, con, v, _p, _przed, _c1 = _dwa_zapisy(tmp_path)
    try:
        v._writeback_async = False
        _klik_okna(v)
        _koniec_biegu(v, "cofnięcie R2")
        assert v._undo_mode == "poprzedni" and not v._undo_btn.isEnabled()
        v.set_writeback_busy(True)
        if koniec == "zapis_skonczony_w_oknie":
            v.set_writeback_busy(False)
            assert not v._undo_btn.isEnabled(), "koniec cudzego zapisu włączył przycisk w oknie"
            _po_oknie(v)
        else:
            _czekaj(lambda: not v._undo_btn._okno.isActive(), "koniec okna w biegu zapisu")
            QApplication.processEvents()
            assert not v._undo_btn.isEnabled(), "koniec okna włączył przycisk w biegu cudzego zapisu"
            v.set_writeback_busy(False)
        assert v._undo_btn.isEnabled()
    finally:
        _zamknij_widok(v)
        con.close()


def test_klik_w_biegu_cofniecia_nie_startuje_drugiego(qapp, tmp_path, monkeypatch):
    """Drugi klik w „Cofnij” w biegu cofnięcia (prawdziwy wątek zapisu zatrzymany bramą) dociera do przycisku, ale nie
    startuje drugiego cofnięcia i nie trafia w nowy cel - ten staje dopiero po końcu biegu. Falsyfikator: straż
    jednego zapisu naraz zdjęta (drugie wołanie `undo_run` przed zwolnieniem bramy)."""
    from PySide6.QtTest import QSignalSpy
    path, con, v, p, _przed, c1 = _dwa_zapisy(tmp_path)
    brama, wolania = _brama_cofniecia(monkeypatch)
    try:
        kliki = QSignalSpy(v._undo_btn.clicked)
        _klik_w(v._undo_btn)
        _czekaj(lambda: wolania, "cofnięcie w biegu")
        _klik_w(v._undo_btn)
        _odczekaj(200)
        assert kliki.count() == 2 and len(wolania) == 1, (kliki.count(), wolania)
        brama.set()
        _koniec_biegu(v, "koniec cofnięcia")
        assert len(wolania) == 1 and _tel(p) == "EQ6"
        assert v._undo_mode == "poprzedni" and v._undo_commity == (c1,)
    finally:
        brama.set()
        _zamknij_widok(v)
        con.close()


@pytest.mark.parametrize("gest", ["mysz", "spacja"])
def test_wcisniecie_sprzed_przezbrojenia_nie_klika_nowego_celu(qapp, tmp_path, monkeypatch, gest):
    """Przycisk wciśnięty w biegu cofnięcia R2 (mysz drogą okna albo spacja) i puszczony dopiero po przezbrojeniu na
    „Cofnij poprzedni zapis”: R1 zostaje nietknięty, przycisk nie wraca do stanu wciśniętego po ruchu myszy. Na widoku
    chroni to już okno przezbrojenia (przycisk wygaszony); straże samego przycisku pinuje
    `test_przycisk_gest_sprzed_uzbrojenia_bez_okna`."""
    path, con, v, p, _przed, c1 = _dwa_zapisy(tmp_path)
    try:
        brama, wolania = _brama_cofniecia(monkeypatch)
        _klik_w(v._undo_btn)
        _czekaj(lambda: wolania, "cofnięcie w biegu")
        okno, srodek = v.window().windowHandle(), _srodek_w_oknie(v)
        if gest == "mysz":
            QTest.mousePress(okno, Qt.LeftButton, Qt.KeyboardModifier.NoModifier, srodek)
        else:
            QTest.keyPress(v._undo_btn, Qt.Key_Space)
        assert v._undo_btn.isDown(), "naciśnięcie nie trafiło w przycisk - test nic by nie mierzył"
        brama.set()
        _czekaj(lambda: not v._wb.is_busy and v._undo_mode == "poprzedni", "przezbrojenie")
        if gest == "mysz":
            QTest.mouseMove(okno, srodek + QPoint(1, 0))
            assert not v._undo_btn.isDown()
            QTest.mouseRelease(okno, Qt.LeftButton, Qt.KeyboardModifier.NoModifier, srodek + QPoint(1, 0))
        else:
            QTest.keyRelease(v._undo_btn, Qt.Key_Space)
        _koniec_biegu(v, "po zwolnieniu")
        assert len(wolania) == 1 and _tel(p) == "EQ6"
        assert v._undo_mode == "poprzedni" and v._undo_commity == (c1,)
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ sam przycisk `_PrzyciskCofnij` (bez widoku)


@pytest.fixture
def przycisk(qapp):
    """Wspólny przycisk „Cofnij” w osobnym oknie: `(okno, przycisk, kliki)` - `kliki` liczy `clicked`."""
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from horreum.gui.grid import _PrzyciskCofnij
    okno = QWidget()
    przycisk = _PrzyciskCofnij("Cofnij")
    QVBoxLayout(okno).addWidget(przycisk)
    okno.resize(300, 100)
    okno.show()
    QTest.qWaitForWindowExposed(okno)
    kliki = []
    przycisk.clicked.connect(lambda: kliki.append(1))
    yield okno, przycisk, kliki
    okno.close()


def _srodek(okno, przycisk):
    return przycisk.mapTo(okno, przycisk.rect().center())


def test_przycisk_dwuklik_lewym_to_jedno_klikniecie(przycisk):
    """Dwuklik lewym drogą okna to jedno `clicked` także bez przezbrojenia („Cofnij zostaje” po cofnięciu niedomkniętym
    - dwuklik ponawiał dwa razy). Falsyfikator: przycisk bez połknięcia `MouseButtonDblClick`."""
    okno, btn, kliki = przycisk
    QTest.mouseDClick(okno.windowHandle(), Qt.LeftButton, Qt.KeyboardModifier.NoModifier, _srodek(okno, btn), 10)
    QApplication.processEvents()
    assert kliki == [1]


@pytest.mark.parametrize("gest", ["mysz", "spacja"])
def test_przycisk_gest_sprzed_uzbrojenia_bez_okna(przycisk, gest):
    """Naciśnięcie sprzed przezbrojenia BEZ okna (`uzbroj(..., okno_ms=0)` - zmiana celu na makro albo nazwy) nie klika
    nowego celu: mysz - ruch połknięty (przycisk nie wraca do stanu wciśniętego), zwolnienie bez kliku; spacja -
    `uzbroj` gasi `down`. Falsyfikatory: ruch sprzed przezbrojenia oddany Qt; `uzbroj` bez `setDown(False)`."""
    okno, btn, kliki = przycisk
    srodek = _srodek(okno, btn)
    if gest == "mysz":
        QTest.mousePress(okno.windowHandle(), Qt.LeftButton, Qt.KeyboardModifier.NoModifier, srodek)
        btn.uzbroj("Cofnij")
        QTest.mouseMove(okno.windowHandle(), srodek + QPoint(1, 0))
        assert not btn.isDown()
        QTest.mouseRelease(okno.windowHandle(), Qt.LeftButton, Qt.KeyboardModifier.NoModifier, srodek + QPoint(1, 0))
    else:
        QTest.keyPress(btn, Qt.Key_Space)
        assert btn.isDown(), "spacja nie wcisnęła przycisku - test nic by nie mierzył"
        btn.uzbroj("Cofnij")
        QTest.keyRelease(btn, Qt.Key_Space)
    QApplication.processEvents()
    assert kliki == []
    _klik = (lambda: QTest.mouseClick(btn, Qt.LeftButton)) if gest == "mysz" else (
        lambda: QTest.keyClick(btn, Qt.Key_Space))
    _klik()
    assert kliki == [1], "nowe naciśnięcie po przezbrojeniu klika"


def test_przycisk_w_oknie_przezbrojenia_bezpiecznik_zdarzen(przycisk):
    """Okno przezbrojenia: przycisk wygaszony, a gdyby ktoś go włączył z pominięciem `setEnabled` tej klasy, naciśnięcie
    myszy i spacja w oknie dalej nie klikają (straż zdarzeń); prośba `setEnabled(True)` w oknie czeka na jego koniec.
    Falsyfikator: straż zdarzeń zdjęta."""
    from PySide6.QtWidgets import QPushButton
    okno, btn, kliki = przycisk
    btn.uzbroj("Cofnij poprzedni zapis (commit 1)", okno_ms=5000)
    assert not btn.isEnabled()
    btn.setEnabled(True)
    assert not btn.isEnabled()
    QPushButton.setEnabled(btn, True)                # z pominięciem prośby widoku
    QTest.mouseClick(okno.windowHandle(), Qt.LeftButton, Qt.KeyboardModifier.NoModifier, _srodek(okno, btn))
    QTest.keyClick(btn, Qt.Key_Space)
    QApplication.processEvents()
    assert kliki == []
    btn.uzbroj("Cofnij")                             # przezbrojenie bez okna kończy okno i oddaje stan prośby
    assert btn.isEnabled()
    QTest.keyClick(btn, Qt.Key_Space)
    assert kliki == [1]


# ============================================================ wyłączność, migawka, szuflada z czekającymi


def test_poprzedni_pod_cudza_blokada_bez_cofnij(qapp, tmp_path):
    """Szufladę bazy prowadzi inny proces (blokada trzymana po otwarciu widoku): „Cofnij” cofa R2, ale „Cofnij poprzedni
    zapis” nie staje - decyzja zapada wyłącznie pod blokadą szuflady; obca blokada stoi, widok jej nie trzyma.
    Falsyfikator: odczyt poprzedniego zapisu bez blokady szuflady."""
    path, con, v, p, _przed, _c1 = _dwa_zapisy(tmp_path)
    blokada = _blokada_obca(path)
    try:
        _klik_cofnij(v, "cofnięcie R2 pod cudzą blokadą")
        assert _tel(p) == "EQ6" and _bez_cofnij(v) and v._undo_mode is None
        assert blokada.isLocked() and not _trzyma_blokade(v)
    finally:
        blokada.unlock()
        _zamknij_widok(v)
        con.close()


def test_poprzedni_z_jednej_migawki(qapp, tmp_path, monkeypatch):
    """Odczyt poprzedniego zapisu pod blokadą w JEDNEJ migawce: drugie połączenie cofa R1 tuż przed odczytem jego
    zakresu (bariera w czwartym wołaniu `przebieg_do_cofniecia` - dwa na odczyt przed blokadą, dwa pod nią). Przycisk
    staje z zakresem stanu sprzed bariery (klik dostanie od rdzenia „już cofnięte”), a nie z pary dwóch chwil.
    Falsyfikator: odczyty bez transakcji odczytu (zakres po cofnięciu - brak przycisku)."""
    path, con, v, _p, _przed, c1 = _dwa_zapisy(tmp_path)
    prawdziwy, wolania = writeback.przebieg_do_cofniecia, []

    def _z_bariera(c, run_id):
        wolania.append(run_id)
        if len(wolania) == 4:
            con2 = db.connect(path)
            try:
                writeback.undo_run(con2, (c1,), now=_NOW)
            finally:
                con2.close()
        return prawdziwy(c, run_id)
    try:
        v._writeback_async = False
        monkeypatch.setattr(writeback, "przebieg_do_cofniecia", _z_bariera)
        _klik_cofnij(v, "cofnięcie R2")
        assert wolania == ["R2", "R1", "R2", "R1"], "bariera nie zadziałała - test nic by nie mierzył"
        assert v._undo_mode == "poprzedni" and v._undo_commity == (c1,)
    finally:
        monkeypatch.undo()
        _zamknij_widok(v)
        con.close()


def test_bez_cofnij_poprzedni_gdy_w_szufladzie_cos_czeka(qapp, tmp_path):
    """Po otwarciu widoku drugie połączenie zostawia czekające zmiany nazw (inne okno): „Cofnij” cofa R2, ale „Cofnij
    poprzedni zapis” nie staje - żywe „Cofnij” wyłączyłoby zdanie szuflady o czekających. Falsyfikator: odczyt bez
    warunku „nic nie czeka”."""
    path, con, v, p, _przed, _c1 = _dwa_zapisy(tmp_path)
    try:
        _nazwy_czekaja(path, "N")
        _klik_cofnij(v, "cofnięcie R2 przy czekających nazwach")
        assert _tel(p) == "EQ6" and _bez_cofnij(v) and v._undo_mode is None
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ etykieta, kotwica, porażki przy żywym poprzednim


@pytest.mark.parametrize("klinga", ["karty", "nazwy"])
def test_etykieta_cofnij_wraca_po_nowym_zapisie(qapp, tmp_path, klinga):
    """„Cofnij poprzedni zapis” stoi, potem nowy zapis szuflady (makro albo zmiana nazw - panel i „Do stagingu”
    klikiem, „Zatwierdź”): wspólny przycisk wraca do etykiety „Cofnij” i jest czynny od razu (przezbrojenie bez okna
    zamyka okno poprzedniego). Falsyfikator: etykieta trybu ustawiana wyłącznie przy poprzednim zapisie."""
    _path, con, v, _p, _przed, _c1 = _po_cofnieciu_r2(tmp_path)
    try:
        if klinga == "karty":
            _makro_przyciskiem(v, "TELESCOP", "C14")
        else:
            if not v.rename_bar.isVisible():
                _klik_w(v.sel_bar.btn_rename)
            _klik_w(v.rename_bar.btn_stage)
            assert v._rename_pending_count() == 1, "staging nazw nie wszedł - test nic by nie mierzył"
        _klik_w(v.drawer.btn_commit)
        _koniec_biegu(v, "nowy zapis")
        assert v._undo_mode == ("macro" if klinga == "karty" else "rename")
        assert v._undo_btn.text() == i18n.t("grid.action.undo") and v._undo_btn.isEnabled()
    finally:
        _zamknij_widok(v)
        con.close()


def test_zdanie_przy_zywym_poprzednim_niesie_identyfikator_raz(qapp, tmp_path):
    """„Cofnij poprzedni zapis” stoi, a „Podgląd” makra z błędem definicji zastępuje zdanie wyniku: zdanie niesie
    kotwicę commitu poprzedniego zapisu dokładnie raz (droga `header-fix --undo N` po restarcie), etykieta zostaje.
    Falsyfikator: kotwica wyłącznie przy trybie makra (zero)."""
    _path, con, v, _p, _przed, c1 = _po_cofnieciu_r2(tmp_path)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6", przycisk="prev", comp="1 +")
        assert v._undo_mode == "poprzedni" and v._undo_btn.isVisible()
        assert v.drawer.result.text().count(f"commit {c1})") == 1, v.drawer.result.text()
        assert v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=1)
    finally:
        _zamknij_widok(v)
        con.close()


def test_poprzednik_z_dwoch_commitow_etykieta_commity(qapp, tmp_path):
    """Starszy przebieg zapisany z przerwaniem i dokończony (`writeback.commit` z `should_cancel` po pierwszym pliku,
    potem drugie `commit` - commity 1 i 2), nowszy na obu plikach: po „Cofnij” etykieta „Cofnij poprzedni zapis
    (commity 1, 2)” i kotwica obu commitów w zdaniu; klik cofa oba. Falsyfikator: etykieta z jednym commitem."""
    path, con, pliki = _baza_szuflady(tmp_path, 2)
    przed = [p.read_bytes() for p in pliki]
    _staging(con, "R1", [0, 1], "EQ6")
    pytania = []
    assert writeback.commit(con, "R1", now=_NOW, inplace=True,
                            should_cancel=lambda: pytania.append(1) or len(pytania) > 1).cancelled
    assert writeback.commit(con, "R1", now=_NOW, inplace=True).applied
    c = _commity(con, "R1")
    assert len(c) == 2, c
    _zapis(con, "R2", [0, 1], "EQ8")
    con.close()
    con, v = _restart(path)
    try:
        _klik_cofnij(v, "cofnięcie R2")
        assert v._undo_mode == "poprzedni" and v._undo_commity == c
        ids = ", ".join(str(x) for x in c)
        assert v._undo_btn.text() == i18n.t("grid.drawer.undo_older_n", ids=ids)
        assert v.drawer.result.text().endswith(i18n.t("grid.drawer.older_write", day=_DZIEN)
                                               + i18n.t("grid.wb.commit_ids", ids=ids)), v.drawer.result.text()
        _klik_cofnij(v, "cofnięcie R1")
        assert [p.read_bytes() for p in pliki] == przed
    finally:
        _zamknij_widok(v)
        con.close()


def test_cofnij_poprzedni_niedomkniete_zostaje_z_recepta_trybu(qapp, tmp_path, monkeypatch):
    """Cofnięcie poprzedniego zapisu, którego re-sync bazy pada (`failed` - „ponowne cofnięcie dokończy”): przycisk
    zostaje z etykietą i zakresem poprzedniego zapisu, recepta ponowienia nazywa TEN przycisk, zdanie niesie kotwicę
    commitu; ponowienie przywraca bajty sprzed obu zapisów i przycisk znika. Falsyfikator: recepta z etykietą
    „Cofnij”."""
    _path, con, v, p, przed, c1 = _po_cofnieciu_r2(tmp_path)
    etykieta = i18n.t("grid.drawer.undo_older", id=c1)
    try:
        with monkeypatch.context() as m:
            m.setattr(writeback.scan, "scan_file",
                      lambda path, **kw: (_ for _ in ()).throw(OSError(64, "zerwany udział")))
            _klik_cofnij(v, "cofnięcie poprzedniego z błędem")
        tekst = v.drawer.result.text()
        assert v._undo_mode == "poprzedni" and v._undo_commity == (c1,) and v._undo_btn.isVisible()
        assert v._undo_btn.text() == etykieta
        assert i18n.t("grid.wb.undo_retry", undo=etykieta) in tekst, tekst
        assert tekst.endswith(i18n.t("grid.wb.commit_id", id=c1)), tekst
        _klik_cofnij(v, "ponowienie")
        assert p.read_bytes() == przed and _bez_cofnij(v) and v._undo_mode is None
    finally:
        _zamknij_widok(v)
        con.close()


def test_awaria_wykonawcy_cofniecia_poprzedniego_zostawia_przycisk(qapp, tmp_path, monkeypatch):
    """Cofnięcie poprzedniego zapisu pada wyjątkiem całej operacji (ogon porażki wykonawcy, nie ogon cofnięcia):
    przycisk zostaje z etykietą i zakresem poprzedniego zapisu, etykieta szuflady „Zatwierdzono: 1”, zdanie błędu
    z kotwicą commitu; ponowienie domyka bez trzeciego kroku. Falsyfikator: kotwica wyłącznie przy trybie makra."""
    from test_gui_bledy_systemu import _odmowa
    _path, con, v, p, przed, c1 = _po_cofnieciu_r2(tmp_path)
    try:
        with monkeypatch.context() as m:
            m.setitem(WritebackWorker._OPS, "undo_run", _odmowa)
            _klik_cofnij(v, "awaria cofnięcia poprzedniego")
        blad = (i18n.t("grid.wb.op.undo_run", msg=i18n.t("objchg.item.os_denied", os_code="WinError 5"))
                + i18n.t("grid.wb.commit_id", id=c1))
        assert v._undo_mode == "poprzedni" and v._undo_commity == (c1,) and v._undo_btn.isVisible()
        assert v._undo_btn.text() == i18n.t("grid.drawer.undo_older", id=c1)
        assert v.drawer.result.text() == blad, v.drawer.result.text()
        assert v.drawer.label.text() == i18n.t("grid.wb.committed_label", n=1)
        _klik_cofnij(v, "ponowienie po awarii")
        assert p.read_bytes() == przed and _bez_cofnij(v) and v._undo_mode is None
    finally:
        _zamknij_widok(v)
        con.close()


def test_wyjatek_odczytu_poprzedniego_chowa_przycisk(qapp, tmp_path, monkeypatch):
    """Odczyt poprzedniego zapisu pada wyjątkiem spoza błędu bazy (EXPECT rdzenia) w ogonie cofnięcia domkniętego:
    wyjątek leci dalej, a przycisk znika - nie zostaje widoczny przy trybie None z zakresem cofniętego już R2.
    Falsyfikator: ogon bez sprzątania przycisku przy wyjątku."""
    _path, con, v, _p, _przed, _c1 = _dwa_zapisy(tmp_path)
    try:
        res = writeback.undo_run(con, v._undo_commity, now=_NOW)
        assert res.complete

        def _pada(*_a, **_k):
            raise RuntimeError("złamany inwariant rodowodu")
        monkeypatch.setattr(queries, "poprzedni_zapis_kart", _pada)
        with pytest.raises(RuntimeError):
            v._after_undo("undo_run", res)
        assert not v._undo_btn.isVisible() and v._undo_mode is None
    finally:
        monkeypatch.undo()
        _zamknij_widok(v)
        con.close()


def test_blad_bazy_w_odczycie_pod_blokada_oddaje_blokade(qapp, tmp_path, monkeypatch):
    """Drugi odczyt poprzedniego zapisu (pod blokadą szuflady) pada błędem bazy: „Cofnij poprzedni” nie staje, a widok
    oddaje blokadę wziętą na ten odczyt - w ogonie cofnięcia i SAM gest (`_postaw_cofnij_poprzedni` wprost, zanim
    odświeżenie szuflady odda ją przy okazji, wzór `tests/test_gui_szuflada_przebieg.py:704-707`). Falsyfikator:
    oddanie blokady poza `finally`."""
    import sqlite3
    _path, con, v, p, _przed, _c1 = _dwa_zapisy(tmp_path)
    prawdziwy, wolania = queries.poprzedni_zapis_kart, []

    def _drugi_pada(c, run_id):
        wolania.append(run_id)
        if len(wolania) % 2 == 0:
            raise sqlite3.OperationalError("database is locked")
        return prawdziwy(c, run_id)
    try:
        v._writeback_async = False
        monkeypatch.setattr(queries, "poprzedni_zapis_kart", _drugi_pada)
        _klik_cofnij(v, "cofnięcie R2")
        assert len(wolania) == 2, "drugi odczyt nie padł - test nic by nie mierzył"
        assert _tel(p) == "EQ6" and _bez_cofnij(v) and not _trzyma_blokade(v)
        assert v._postaw_cofnij_poprzedni("R2", "") is False and len(wolania) == 4
        assert not _trzyma_blokade(v)
    finally:
        monkeypatch.undo()
        _zamknij_widok(v)
        con.close()


def test_restart_przy_stojacym_cofnij_poprzedni_bez_przycisku(qapp, tmp_path):
    """„Cofnij poprzedni zapis” stoi, ale człowiek go nie klika i zamyka program: po restarcie szuflada go nie stawia
    (decyzja: przycisk wyłącznie w sesji; najnowszy zapis R2 jest cofnięty, starszy - CLI). Falsyfikator: restart
    pytający o poprzedni zapis."""
    path, con, v, p, _przed, _c1 = _po_cofnieciu_r2(tmp_path)
    _zamknij_widok(v)
    con.close()
    con, v = _restart(path)
    try:
        assert _bez_cofnij(v) and v._undo_mode is None and _tel(p) == "EQ6"
    finally:
        _zamknij_widok(v)
        con.close()


# ============================================================ reguła odczytu bez okna


def _scena_reguly(tmp_path, kod):
    """Baza sceny reguły `kod` po cofnięciu przebiegu R2 (prawdziwy rdzeń, bez okna): `(con, oczekiwany przebieg albo
    None)`."""
    path, con, pliki = _baza_szuflady(tmp_path, 2)
    if kod == "obiekt":
        with con:
            con.execute("INSERT INTO object_change_run (run_id, mode, created_at) VALUES ('R1', 'align', ?)", (_NOW,))
    if kod == "b":
        _zapis(con, "R0", [0], "EQ6")
        po_r0 = pliki[0].read_bytes()
        _zapis(con, "R1", [0], "EQ8")
        pliki[0].write_bytes(po_r0)
        _skan(con, pliki[0])
        _zapis(con, "R2", [0], "C14")
    elif kod == "c":
        (c1,) = _zapis(con, "R1", [0], "EQ6")
        po_r1 = pliki[0].read_bytes()
        assert writeback.undo_run(con, (c1,), now=_NOW).complete
        pliki[0].write_bytes(po_r1)                     # wynik R1 wraca z zewnątrz - jego cofnięcie w miejscu domknięte
        _skan(con, pliki[0])
        _zapis(con, "R2", [0], "EQ8")
    elif kod == "czesciowy":
        (c1,) = _zapis(con, "R1", [0, 1], "EQ6")
        po_r1 = [p.read_bytes() for p in pliki]
        fits.setval(str(pliki[1]), "OBSERVER", value="obcy")
        _skan(con, pliki[1])
        assert not writeback.undo_run(con, (c1,), now=_NOW).complete    # plik 0 wraca, plik 1 odmawia
        for p, bajty in zip(pliki, po_r1):
            p.write_bytes(bajty)
            _skan(con, p)
        _zapis(con, "R2", [0, 1], "EQ8")
    elif kod == "zywy":
        # R2 NIE cofnięty, a jego wynik jest bajt w bajt wynikiem R1 (plik wrócił z zewnątrz do stanu wyjściowego, R2
        # zapisał tę samą kartę): (a)-(c) poprzednika przechodzą - odmawia wyłącznie warunek „R2 nie ma czego cofać”.
        przed = pliki[0].read_bytes()
        _zapis(con, "R1", [0], "EQ6")
        pliki[0].write_bytes(przed)
        _skan(con, pliki[0])
        _zapis(con, "R2", [0], "EQ6")
    else:
        _zapis(con, "R1", [0, 1] if kod in ("a", "niepodmieniony") else [0], "EQ6")
        _zapis(con, "R2", [0, 1] if kod in ("niepodmieniony", "podzbior") else [0], "EQ8")
    if kod != "zywy":
        assert writeback.undo_run(con, _commity(con, "R2"), now=_NOW).complete
    if kod == "niepodmieniony":
        # Backup R2 na pliku 1 bez podmiany: R2 tego pliku nie zmienił, więc nie należy do „tych plików”.
        with con:
            con.execute("UPDATE header_backups SET unreplaced_at = ? WHERE commit_id IN (SELECT id FROM commits "
                        "WHERE run_id = 'R2') AND location_id = (SELECT id FROM location ORDER BY id LIMIT 1 OFFSET 1)",
                        (_NOW,))
    if kod == "czeka":
        _nazwy_czekaja(path, "N")
    return con, ("R1" if kod == "przechodzi" else None)


@pytest.mark.parametrize("kod", ["przechodzi", "zywy", "a", "podzbior", "b", "c", "czesciowy", "obiekt", "czeka",
                                 "niepodmieniony"])
def test_poprzedni_zapis_kart_regula(tmp_path, kod):
    """Reguła `queries.poprzedni_zapis_kart` po cofnięciu R2: przechodzi - R1 z datą najnowszego commitu i zakresem;
    None, gdy R2 ma co cofać (także gdy jego wynik jest bajt w bajt wynikiem R1), poprzednik ma plik spoza cofniętego
    (a) albo tylko część jego plików (a - równość zbiorów), poprzednika nie ma w pliku (b - także gdy starszy zapis
    jest), poprzednik nie ma czego cofać (c - jego cofnięcie w miejscu domknięte, wynik wrócił z zewnątrz), zakres
    poprzednika nie obejmuje każdej jego lokacji (c - cofnięty kiedyś w części), poprzednik to zmiana obiektu,
    w szufladzie coś czeka, plik bez podmiany przez R2 jest poza „tymi plikami”. Migawka własna zamknięta po odczycie;
    w transakcji wołającego - w niej. Falsyfikatory: brak któregokolwiek warunku; L z backupami bez podmiany."""
    con, oczek = _scena_reguly(tmp_path, kod)
    try:
        wynik = queries.poprzedni_zapis_kart(con, "R2")
        assert (wynik and wynik["run_id"]) == oczek, wynik
        assert not con.in_transaction
        if oczek is not None:
            assert wynik["kiedy"] == _NOW and wynik["zakres"].commity == _commity(con, "R1")
            con.execute("BEGIN")
            try:
                assert queries.poprzedni_zapis_kart(con, "R2")["run_id"] == oczek and con.in_transaction
            finally:
                con.rollback()
    finally:
        con.close()
