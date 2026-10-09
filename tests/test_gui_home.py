"""Dom (`gui/home.py`) i nawigacja okna wokół niego: start na Domu, sidebar z nagłówkiem „Więcej",
kafle i ich trasy, „Popraw · N" = plakietka Porządków, „Co mam" = suma teczek, teczki w wątku tła,
„Ostatnio" z receptą paska i z dziennika, menu „Więcej…", przejścia między drogami przy biegu
Dostawy i przy otwartym stagingu, PL/EN.

Sterujemy oknem bez pytest-qt (offscreen, QApplication ręcznie). `importorskip` na poziomie modułu -
bez PySide6 plik się pomija (izolacja §7.2)."""
import copy
import itertools
import os
import time
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from horreum import db
from horreum.gui import grid as grid_mod
from horreum.gui import home as home_mod
from horreum.gui import i18n, queries
from horreum.gui import tasks as tasks_mod
from horreum.gui.app import (
    NAV_DOM, NAV_DOSTAWA, NAV_PLANER, NAV_PORZADKI, NAV_WIECEJ, NAV_ZBIORY, NAV_ZNAJDZ, STRONA_DOM,
    STRONA_DOSTAWA, STRONA_PLANER, STRONA_PORZADKI, STRONA_ZBIORY, MainWindow,
)
from horreum.gui.grid import CzlonRecepty, FramesView, Recepta
from horreum.gui.home import HomeView
from horreum.gui.i18n_catalog import CATALOG

from fixture_s8 import NOW, build

DOM_NOW = "2026-10-09T12:00:00+00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _watki_inline(monkeypatch):
    """Wątki tła okna (pokrycie pól, skład zbioru, teczki Domu) INLINE - asercje stoją zaraz po
    geście. Drogę produkcyjną teczek sprawdzają testy `HomeView` na prawdziwym wątku niżej."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)


def _s8(tmp_path, name="s8.db"):
    path = str(tmp_path / name)
    build(path, object_axis=True)            # §8 + oś obiektu: 6 zadań w Porządkach, 2 obiekty
    return path


def _baza_domu(path, obiekty, *, extra=True):
    """Baza Domu bez plików: `obiekty` = [(kanon, [(date_obs, exptime), …]), …] - aktywne lighty
    z obiektem. `extra` dokłada lighty, których ani teczki, ani „Co mam" nie liczą (bez obiektu,
    wycofany, zastąpiony) i light bez czasu i godziny. Zwraca otwarte połączenie."""
    con = db.open_db(path)
    con.execute("INSERT INTO camera (id, model_canon, is_mono, created_at) VALUES "
                "(1, 'ASI2600MM', 1, ?)", (NOW,))
    con.execute("INSERT INTO telescope (id, telescop_canon, label, status, created_at) VALUES "
                "(1, 'A140R', NULL, 'proposed', ?)", (NOW,))
    con.execute("INSERT INTO config (id, telescope_id, camera_id, status, created_at) VALUES "
                "(10, 1, 1, 'proposed', ?)", (NOW,))
    n = [0]

    def light(object_id, date_obs, exptime, *, header=True):
        n[0] += 1
        fid = con.execute(
            "INSERT INTO frame (sha1_data, kind, filetype, camera_id, config_id, object_id, "
            "filter_canon, first_seen_at) VALUES (?, 'light', 'fits', 1, 10, ?, 'Ha', ?)",
            (f"sha{n[0]}", object_id, NOW)).lastrowid
        if header:
            con.execute("INSERT INTO header (frame_id, raw_json, date_obs, exptime, xbinning) "
                        "VALUES (?, '{}', ?, ?, 1)", (fid, date_obs, exptime))
        con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (fid, f"X:\\lib\\{n[0]}.fits"))
        return fid

    pierwszy = None
    for i, (canon, lighty) in enumerate(obiekty, start=1):
        con.execute("INSERT INTO object (id, canon) VALUES (?, ?)", (i, canon))
        for date_obs, exptime in lighty:
            fid = light(i, date_obs, exptime)
            pierwszy = pierwszy or fid
    if extra:
        light(None, "2024-04-01T22:00:00", 9000.0)                 # bez obiektu
        wyc = light(1, "2024-04-02T22:00:00", 9000.0)
        zas = light(1, "2024-04-03T22:00:00", 9000.0)
        con.execute("UPDATE frame SET retired_at = ? WHERE id = ?", (NOW, wyc))
        con.execute("UPDATE frame SET superseded_by = ? WHERE id = ?", (pierwszy, zas))
        light(1, None, None)                                         # bez czasu i bez nocy
        light(1, None, None, header=False)                           # bez nagłówka w ogóle
    con.commit()
    return con


_TRZY = [("Mniejszy", [("2024-03-05T22:00:00", 600.0)]),
         ("Wiekszy", [("2024-03-01T23:00:00", 3600.0), ("2024-03-02T01:30:00", 3600.0),
                      ("2024-03-02T23:10:00", 1800.0)]),
         ("Sredni", [("2024-03-02T02:00:00", 1200.0), ("2024-03-02T03:00:00", 1200.0)])]


def _obiekty(n):
    """`n` obiektów po jednym lighcie, godziny malejące z numerem - kolejność teczek = numeracja."""
    return [(f"OBJ{i:02d}", [("2024-03-01T23:00:00", 100.0 * (40 - i))]) for i in range(1, n + 1)]


def _dwanascie():
    return _obiekty(12)


def _widoczne(h):
    return [k.accessibleName() for k in h.karty if not k.isHidden()]


def _wysokosc_na_rzedy(h, n, *, ze_stopka=True, luz=None):
    """Wysokość Domu, w której mieści się DOKŁADNIE `n` rzędów kart (domyślnie pół rzędu luzu,
    gdy jest rząd następny) - z tą samą miarą reszty ekranu, której używa kod (zawinięty tekst
    liczony dla bieżącej szerokości)."""
    rzedy = h._wysokosci_rzedow()
    odstep = h.teczki_siatka.verticalSpacing()
    if luz is None:
        luz = rzedy[n] // 2 if n < len(rzedy) else 2
    return h._wysokosc_poza_teczkami(ze_stopka=ze_stopka) + sum(rzedy[:n]) + odstep * (n - 1) + luz


def _reszta_przy_szerokosci(h, w):
    h.resize(w, h.height())
    QApplication.processEvents()
    return h._wysokosc_poza_teczkami()


def _bez_przewijania(h):
    """Dom nie przewija w pionie: prawdziwy pasek QScrollArea ukryty, a pion treści dla bieżącej
    szerokości mieści się w viewporcie (po zdarzeniach, więc z paskiem poziomym, gdy ten stoi)."""
    QApplication.processEvents()
    uklad = h._tresc.layout()
    pion = uklad.heightForWidth(h.width()) if uklad.hasHeightForWidth() else uklad.sizeHint().height()
    return not h._scroll.verticalScrollBar().isVisible() and pion <= h._scroll.viewport().height()


def _zdarzenia(path, rows):
    """Dopisz eventy do dziennika bazy pod `path` (osobne połączenie - jak zapis z innej drogi)."""
    con = db.open_db(path)
    con.executemany("INSERT INTO event (ts, actor, verb, target) VALUES (?, ?, ?, ?)", rows)
    con.commit()
    con.close()


def _pokazane(win):
    win.resize(1400, 800)
    win.show()
    QApplication.processEvents()
    QApplication.processEvents()
    return win


def _czekaj_na_watek(home, limit_s=10.0):
    koniec = time.monotonic() + limit_s
    while home._thread is not None and time.monotonic() < koniec:
        QTest.qWait(20)
    assert home._thread is None, "wątek teczek nie skończył w limicie"


# ---------------------------------------------------------------- read-model Domu (queries)

def test_home_summary_rowna_sumie_teczek(tmp_path):
    """„Co mam" i teczki stoją na jednym ekranie, więc liczą TĘ SAMĄ populację: lighty i godziny
    linii sum = suma po teczkach `release_readiness`. Light bez obiektu, wycofany i zastąpiony nie
    liczą się nigdzie; light bez czasu liczy się jako light z zerem godzin. Noce DISTINCT po
    archiwum wg definicji facetu Noc (01:30 to jeszcze noc poprzedniego dnia), nie suma nocy teczek.

    Falsyfikator: zdejmij `JOIN object` z `home_summary` → lightów o jeden więcej niż w teczkach."""
    con = _baza_domu(str(tmp_path / "d.db"), _TRZY)
    try:
        s = queries.home_summary(con)
        teczki = queries.release_readiness(con)
        assert s["lights"] == sum(r["lights"] for r in teczki) == 8
        assert s["hours"] == pytest.approx(sum(r["hours"] for r in teczki))
        assert s["hours"] == pytest.approx((600 + 3600 * 2 + 1800 + 1200 * 2) / 3600)
        assert s["objects"] == len(teczki) == 3
        # noce: 03-01 (23:00 i 01:30), 03-02 (23:10), 03-01 (02:00 i 03:00 dnia 02), 03-05
        assert s["nights"] == 3
        assert sum(r["nights"] for r in teczki) == 4, "suma teczek liczy wspólną noc dwa razy"
        assert s["last_night"] == "2024-03-05"
    finally:
        con.close()


def test_home_summary_pustej_bazy(tmp_path):
    con = db.open_db(str(tmp_path / "pusta.db"))
    try:
        assert queries.home_summary(con) == {"objects": 0, "lights": 0, "hours": 0.0,
                                             "nights": 0, "last_night": None}
        assert queries.last_hand_gesture(con) is None
    finally:
        con.close()


def test_last_hand_gesture_to_wspolny_ts_i_actor(tmp_path):
    """Gest = wszystkie eventy z `ts` i `actor` OSTATNIEGO eventu ręki (cofnięcie uwag mieszanego
    zaznaczenia emituje naraz `note.set` i `note.cleared`). Późniejszy event automatu nie jest
    gestem ręki; event innej ręki z tym samym `ts` i starszy gest tej samej ręki do niego nie należą.
    Goły `user` (oś piksela kamery) też jest ręką."""
    path = str(tmp_path / "g.db")
    db.open_db(path).close()
    ts = "2026-10-04T12:00:00+00:00"
    _zdarzenia(path, [("2026-10-01T10:00:00+00:00", "user:local", "object.assigned", "frame:9"),
                      (ts, "user:local", "note.set", "frame:1"),
                      (ts, "user:inny", "note.set", "frame:5"),
                      (ts, "user:local", "note.cleared", "frame:2"),
                      (ts, "user:local", "note.set", "frame:3"),
                      ("2026-10-05T10:00:00+00:00", "scan", "frame.observed", "frame:4")])
    con = db.open_db(path)
    try:
        assert queries.last_hand_gesture(con) == {
            "ts": ts, "actor": "user:local", "verbs": {"note.cleared": 1, "note.set": 2}, "n": 3}
    finally:
        con.close()
    _zdarzenia(path, [("2026-10-06T10:56:50+00:00", "user", "camera.pixel_user_set", "camera:1")])
    con = db.open_db(path)
    try:
        g = queries.last_hand_gesture(con)
        assert (g["actor"], g["verbs"], g["n"]) == ("user", {"camera.pixel_user_set": 1}, 1)
    finally:
        con.close()


# ---------------------------------------------------------------- zdania dziennika

def test_zdanie_dziennika_jeden_czasownik_kilka_i_nieznany():
    """Znany czasownik ma własne zdanie; gest kilku czasowników i czasownik bez zdania mówią
    zdaniem ogólnym z PEŁNĄ liczbą zmian. Rok tylko spoza roku bieżącego."""
    ts = "2026-10-04T12:00:00+00:00"
    gest = {"ts": ts, "actor": "user:local", "verbs": {"location.renamed": 15}, "n": 15}
    assert home_mod.zdanie_dziennika(gest, DOM_NOW) == "Ostatnio (04.10): 15 plików przemianowano"
    mieszany = {"ts": ts, "actor": "user:local", "verbs": {"note.cleared": 1, "note.set": 2}, "n": 3}
    assert home_mod.zdanie_dziennika(mieszany, DOM_NOW) == "Ostatnio (04.10): 3 zmiany"
    nieznany = {"ts": ts, "actor": "user:local", "verbs": {"stack_versions.kept": 5}, "n": 5}
    assert home_mod.zdanie_gestu(nieznany) == "5 zmian"
    stary = dict(gest, ts="2025-12-20T12:00:00+00:00")
    assert home_mod.zdanie_dziennika(stary, DOM_NOW) == "Ostatnio (20.12.2025): 15 plików przemianowano"
    i18n.set_lang("en")
    assert home_mod.zdanie_dziennika(gest, DOM_NOW) == "Last (10/04): 15 files renamed"
    assert home_mod.zdanie_dziennika(mieszany, DOM_NOW) == "Last (10/04): 3 changes"


def test_kazdy_czasownik_z_mapy_ma_zdanie_PL_i_EN():
    """Klucze zdań gestu jadą mapą, więc kolektor literałów bramki i18n ich nie widzi - parytet
    pilnowany tu: komplet form obu języków i liczba w każdej formie (przypadki 1, 2-4, 5, 12-14, 22)."""
    braki = [k for k in [*home_mod._ZDANIA_GESTU.values(), "home.gest.many"] if k not in CATALOG]
    assert not braki, braki
    for klucz in [*home_mod._ZDANIA_GESTU.values(), "home.gest.many"]:
        assert set(CATALOG[klucz]["pl"]) == {"one", "few", "many"}, klucz
        assert set(CATALOG[klucz]["en"]) == {"one", "other"}, klucz
        for jezyk in ("pl", "en"):
            i18n.set_lang(jezyk)
            for n in (1, 2, 4, 5, 12, 14, 22):
                assert str(n) in i18n.t_plural(klucz, n), (klucz, jezyk, n)
    i18n.set_lang("pl")
    assert i18n.t_plural("home.gest.object_assigned", 22) == "22 klatkom nadano obiekt"
    assert i18n.t_plural("home.gest.location_renamed", 12) == "12 plików przemianowano"
    assert i18n.t_plural("home.gest.location_renamed", 1) == "1 plik przemianowano"


# ---------------------------------------------------------------- HomeView: teczki

def test_teczki_do_osiemnastu_kart_wg_godzin_i_stopka_do_Znajdz(qapp, tmp_path):
    """Do osiemnastu teczek o największej liczbie godzin, w kolejności `release_readiness`; reszta
    to stopka „… i N kolejnych - szukaj w Znajdź", której klik prowadzi do Znajdź. Klik karty niesie
    obiekt tej karty."""
    con = _baza_domu(str(tmp_path / "d.db"), _obiekty(20), extra=False)
    h = HomeView(con, now_fn=lambda: DOM_NOW, poza_watkiem=False)
    try:
        h.resize(1400, 1600)                      # pion na wszystkie sześć rzędów
        h.show()
        QApplication.processEvents()
        assert [k.accessibleName() for k in h.karty] == [f"OBJ{i:02d}" for i in range(1, 19)]
        assert _widoczne(h) == [f"OBJ{i:02d}" for i in range(1, 19)]
        assert not h.btn_teczki_wiecej.isHidden()
        assert h.btn_teczki_wiecej.text() == "… i 2 kolejne - szukaj w Znajdź"
        assert h.teczki_status.isHidden()
        znajdz, teczki = [], []
        h.znajdz.connect(lambda: znajdz.append(True))
        h.teczka.connect(lambda oid, canon: teczki.append((oid, canon)))
        h.btn_teczki_wiecej.click()
        h.karty[1].click()
        assert znajdz == [True] and teczki == [(2, "OBJ02")]
        assert h.co_mam.text() == ("Co mam: 20 obiektów · 20 lightów · "
                                   f"{sum(100.0 * (40 - i) for i in range(1, 21)) / 3600:.1f} h"
                                   " · 1 noc · ostatnia noc 2024-03-01")
    finally:
        h.close()
        con.close()


def test_teczki_rzedy_schodza_z_wysokoscia_okna_i_wracaja(qapp, tmp_path):
    """Rzędów teczek tyle, ile mieści pion Domu: niższe okno chowa dolne rzędy (stopka liczy je
    razem z teczkami bez kart), nie dostaje paska przewijania; najniższe zostawia jeden rząd;
    powrót do wysokiego okna odsłania wszystko z powrotem - te same karty, bez przebudowy."""
    con = _baza_domu(str(tmp_path / "d.db"), _obiekty(20), extra=False)
    h = HomeView(con, now_fn=lambda: DOM_NOW, poza_watkiem=False)
    try:
        h.resize(1400, 1600)
        h.show()
        QApplication.processEvents()
        karty = list(h.karty)
        assert len(_widoczne(h)) == 18
        h.resize(1400, _wysokosc_na_rzedy(h, 3))
        QApplication.processEvents()
        assert _widoczne(h) == [f"OBJ{i:02d}" for i in range(1, 10)]
        assert h.btn_teczki_wiecej.text() == "… i 11 kolejnych - szukaj w Znajdź"
        assert _bez_przewijania(h)
        h.resize(1400, 10)                        # niżej niż jeden rząd - jeden rząd zostaje
        QApplication.processEvents()
        assert _widoczne(h) == ["OBJ01", "OBJ02", "OBJ03"]
        assert h.btn_teczki_wiecej.text() == "… i 17 kolejnych - szukaj w Znajdź"
        h.resize(1400, 1600)
        QApplication.processEvents()
        assert len(_widoczne(h)) == 18 and h.karty == karty
        assert h.btn_teczki_wiecej.text() == "… i 2 kolejne - szukaj w Znajdź"
        assert _bez_przewijania(h)
    finally:
        h.close()
        con.close()


def test_teczki_waskie_okno_liczy_zawiniety_tekst(qapp, tmp_path):
    """Reszta ekranu liczona dla BIEŻĄCEJ szerokości: w wąskim oknie „Co mam" zawija się na kilka
    linii i zabiera pion kartom - rzędów ma być tyle, żeby Dom dalej nie przewijał, także gdy
    zmieniła się sama szerokość (recenzja Z1)."""
    con = _baza_domu(str(tmp_path / "d.db"), _obiekty(20), extra=False)
    h = HomeView(con, now_fn=lambda: DOM_NOW, poza_watkiem=False)
    try:
        h.resize(1400, 1600)
        h.show()
        QApplication.processEvents()
        h.resize(1400, _wysokosc_na_rzedy(h, 4, luz=2))   # cztery rzędy na styk
        QApplication.processEvents()
        assert len(_widoczne(h)) == 12 and _bez_przewijania(h)
        szeroko = h._wysokosc_poza_teczkami()
        # Pierwsza szerokość, przy której „Co mam" się zawija (metryki czcionki offscreen nie są
        # stałą). Poniżej podłogi okna kafle i karty nie zwężają się dalej, więc dochodzi pasek
        # poziomy - rachunek ma go odjąć od pionu, a pionowego paska dalej nie ma.
        next(w for w in (1000, 860, 760, 680, 600, 540) if _reszta_przy_szerokosci(h, w) > szeroko)
        assert len(_widoczne(h)) < 12 and _bez_przewijania(h)
        h.resize(1400, h.height())
        QApplication.processEvents()
        assert len(_widoczne(h)) == 12 and _bez_przewijania(h)
    finally:
        h.close()
        con.close()


def test_teczki_komplet_bez_stopki_ma_pierwszenstwo(qapp, tmp_path):
    """Gdy każda teczka ma kartę (≤ 18), a komplet mieści się bez stopki, Dom pokazuje komplet:
    stopka doliczona z góry chowałaby ostatni rząd i mówiła „… i 3 kolejne" o kartach, które ukryła
    sama (recenzja Z2). O jeden rząd niżej stopka wraca z prawdziwą liczbą."""
    con = _baza_domu(str(tmp_path / "d.db"), _obiekty(18), extra=False)
    h = HomeView(con, now_fn=lambda: DOM_NOW, poza_watkiem=False)
    try:
        h.resize(1400, 1600)
        h.show()
        QApplication.processEvents()
        assert len(_widoczne(h)) == 18 and h.btn_teczki_wiecej.isHidden()
        h.resize(1400, _wysokosc_na_rzedy(h, 6, ze_stopka=False))
        QApplication.processEvents()
        assert len(_widoczne(h)) == 18 and h.btn_teczki_wiecej.isHidden() and _bez_przewijania(h)
        h.resize(1400, _wysokosc_na_rzedy(h, 5))
        QApplication.processEvents()
        assert len(_widoczne(h)) == 15 and _bez_przewijania(h)
        assert h.btn_teczki_wiecej.text() == "… i 3 kolejne - szukaj w Znajdź"
    finally:
        h.close()
        con.close()


def test_teczki_status_i_blad_biegu_zabieraja_pion_starym_kartom(qapp, tmp_path):
    """Komunikat błędu biegu (i „Liczę gotowość…" w `_start`) stoi obok starych kart - rzędy liczą
    się od nowa, żeby Dom nie przewijał do następnego biegu (recenzja Z3)."""
    con = _baza_domu(str(tmp_path / "d.db"), _obiekty(20), extra=False)
    h = HomeView(con, now_fn=lambda: DOM_NOW, poza_watkiem=False)
    try:
        h.resize(1400, 1600)
        h.show()
        QApplication.processEvents()
        h.resize(1400, _wysokosc_na_rzedy(h, 3, luz=2))   # trzy rzędy na styk
        QApplication.processEvents()
        assert len(_widoczne(h)) == 9 and h.teczki_status.isHidden()
        h._on_teczki_failed(h._gen, "boom")
        QApplication.processEvents()
        assert not h.teczki_status.isHidden() and "boom" in h.teczki_status.text()
        assert len(_widoczne(h)) == 6 and _bez_przewijania(h)
        assert h.btn_teczki_wiecej.text() == "… i 14 kolejnych - szukaj w Znajdź"
    finally:
        h.close()
        con.close()


def test_karta_teczki_kropka_rozmiar_kalibracja_i_przeliczenie_osobno(qapp, tmp_path):
    """Karta: kropka stanu z ROLĄ motywu (nie literałem), „h · nocy · zestawów", „flat X % · dark
    Y %" (surowe flaty dopisane, gdy są), a lighty czekające tylko na przeliczenie w Dostawie -
    osobnym zdaniem, nie schowane w procencie flatu."""
    con = _baza_domu(str(tmp_path / "d.db"), _TRZY, extra=False)
    h = HomeView(con, poza_watkiem=False)
    try:
        wiersz = {"object_id": 7, "canon": "NGC6888", "lights": 40, "hours": 44.9, "nights": 12,
                  "zestawy": 2, "n_master_flat": 10, "n_master_dark": 40, "n_raw_flat": 20,
                  "n_pending": 5, "pct_master_flat": 25, "pct_master_dark": 100,
                  "pct_raw_flat": 50, "pct_pending": 12, "last_night": "2026-08-08",
                  "stan": "amber"}
        h._render_teczki([wiersz, dict(wiersz, object_id=8, canon="M42", n_raw_flat=0,
                                       n_pending=0, stan="green")])
        from PySide6.QtWidgets import QLabel
        napisy = [lbl.text() for lbl in h.karty[0].findChildren(QLabel)]
        assert napisy == ["●", "NGC6888", "44.9 h · 12 nocy · 2 zestawy",
                          "flat 25 % (+ surowe 50 %) · dark 100 %",
                          "5 lightów do przeliczenia w Dostawie"]
        kropka = h.karty[0].findChildren(QLabel)[0]
        assert kropka.property("role") == "warn"
        assert h.karty[1].findChildren(QLabel)[0].property("role") == "ok"
        assert [lbl.text() for lbl in h.karty[1].findChildren(QLabel)][3] == "flat 25 % · dark 100 %"
        assert len(h.karty[1].findChildren(QLabel)) == 4, "bez przeliczenia - bez zdania"
        assert all(lbl.testAttribute(Qt.WA_TransparentForMouseEvents)
                   for lbl in h.karty[0].findChildren(QLabel)), "klik trafia w kartę, nie w etykietę"
    finally:
        h.close()
        con.close()


def test_karta_teczki_ma_wysokosc_swojego_ukladu(qapp, tmp_path):
    """Karta to przycisk z WŁASNYM układem etykiet - `QPushButton` liczy podpowiedź rozmiaru z pustego
    napisu (24 px), a układ potrzebuje kilku linii (wizytator natywnie: 24 px wobec 68 px, tekst
    ucięty). Karta oddaje podpowiedzi układu, więc w oknie stoi co najmniej na jego wysokość - także
    karta z czwartą linią („do przeliczenia")."""
    path = str(tmp_path / "d.db")
    _baza_domu(path, _TRZY).close()
    win = _pokazane(MainWindow(path))
    try:
        h = win.home_view
        wiersz = {"object_id": 7, "canon": "NGC6888", "lights": 40, "hours": 44.9, "nights": 12,
                  "zestawy": 2, "n_master_flat": 10, "n_master_dark": 40, "n_raw_flat": 20,
                  "n_pending": 5, "pct_master_flat": 25, "pct_master_dark": 100,
                  "pct_raw_flat": 50, "pct_pending": 12, "last_night": "2026-08-08",
                  "stan": "amber"}
        h._render_teczki([wiersz, dict(wiersz, object_id=8, canon="M42", n_pending=0)])
        QApplication.processEvents()
        QApplication.processEvents()
        for karta in h.karty:
            potrzeba = karta.layout().sizeHint().height()
            assert karta.height() >= potrzeba, (karta.accessibleName(), karta.height(), potrzeba)
            assert karta.minimumSizeHint().height() >= karta.layout().minimumSize().height()
        assert h.karty[0].height() > 4 * karta.fontMetrics().height(), "cztery linie się mieszczą"
    finally:
        win.close()


def test_teczki_na_prawdziwym_watku_i_inwentarz_akcji_w_biegu(qapp, tmp_path):
    """Droga produkcyjna: teczki liczą się w wątku tła na WŁASNYM połączeniu (`con` okna nie
    przechodzi), ekran mówi „Liczę gotowość…" do wyniku. Inwentarz akcji czytających stan, który
    tło zmienia (lista kart): w trakcie biegu stare karty zostają i klik niesie obiekt SWOJEJ karty,
    a zamówienie w biegu nie zakłada drugiego wątku - rachunek rusza jeszcze raz po sprzątnięciu.
    Wynik doręczony po `zatrzymaj_pola` trafia do kosza (generacja)."""
    con = _baza_domu(str(tmp_path / "d.db"), _TRZY)
    h = HomeView(con, poza_watkiem=True)
    try:
        assert h._thread is not None, "rachunek poszedł w tło"
        assert h.teczki_status.text() == "Liczę gotowość…" and h.karty == []
        _czekaj_na_watek(h)
        assert [k.accessibleName() for k in h.karty] == ["Wiekszy", "Sredni", "Mniejszy"]
        assert h.teczki_status.isHidden()

        h.odswiez_teczki()
        watek = h._thread
        assert watek is not None and h.teczki_status.text() == "Liczę gotowość…"
        teczki = []
        h.teczka.connect(lambda oid, canon: teczki.append(canon))
        h.karty[0].click()                               # stara karta w biegu - jej własny obiekt
        assert teczki == ["Wiekszy"]
        gen = h._gen
        h.odswiez_teczki()                               # zamówienie w biegu: bez drugiego wątku
        assert h._thread is watek and h._gen == gen + 1
        _czekaj_na_watek(h)
        if h._pokazana_gen != h._gen:                    # ponowny rachunek ruszył w sprzątnięciu
            _czekaj_na_watek(h)
        assert h._pokazana_gen == h._gen
        assert [k.accessibleName() for k in h.karty] == ["Wiekszy", "Sredni", "Mniejszy"]

        stara = h._gen
        h.zatrzymaj_pola()
        h.zatrzymaj_pola()                               # idempotentne
        przed = list(h.karty)
        h._on_teczki(stara, [])                          # wynik sprzed zatrzymania
        assert h.karty == przed and h.teczki_status.isHidden()
        h.odswiez_teczki()                               # widok znika - nowego wątku nie zakłada
        assert h._thread is None
    finally:
        h.zatrzymaj_pola()
        h.close()
        con.close()


def test_teczki_w_trybie_inline_na_bazie_bez_sciezki(qapp):
    """`:memory:` nie ma ścieżki dla własnego połączenia workera - rachunek biegnie inline na
    żywym `con`, także gdy flaga mówi „w tle"."""
    con = db.open_db(":memory:")
    try:
        h = HomeView(con, poza_watkiem=True)
        assert h._thread is None
        assert h.teczki_status.text() == i18n.t("home.folders.empty")
        assert h.co_mam.text() == i18n.t("home.have.empty")
        assert h.ostatnio.isHidden(), "pusty dziennik - nic do powiedzenia"
        h.close()
    finally:
        con.close()


# ---------------------------------------------------------------- okno: start, sidebar, kafle

def test_start_na_Domu_i_sidebar_z_naglowkiem(qapp, tmp_path):
    """Start z otwartą bazą = Dom. Sidebar: Dom · Znajdź · „Więcej" (nagłówek bez flag - ani mysz,
    ani strzałki go nie wybiorą) · Dostawa · Zbiory klasyczne · Porządki (N) · Planer. Znajdź
    i Zbiory klasyczne to JEDNA strona stosu w dwóch prezentacjach."""
    win = _pokazane(MainWindow(_s8(tmp_path)))
    try:
        assert win.nav.currentRow() == NAV_DOM and win.stack.currentIndex() == STRONA_DOM
        assert win.stack.currentWidget() is win.home_view
        assert [win.nav.item(i).text() for i in range(win.nav.count())] == [
            "Dom", "Znajdź", "Więcej", "Dostawa", "Zbiory klasyczne", "Porządki (6)", "Planer"]
        assert win.nav.item(NAV_WIECEJ).flags() == Qt.NoItemFlags
        win.show_find()
        assert win.stack.currentWidget() is win.znajdz_view
        assert win.znajdz_view.prezentacja == "znajdz" and win.nav.currentRow() == NAV_ZNAJDZ
        win.show_classic()
        assert win.stack.currentWidget() is win.znajdz_view
        assert win.znajdz_view.prezentacja == "klasyczna" and win.nav.currentRow() == NAV_ZBIORY
        assert win.znajdz_view.frames_view is win.grid_view, "jeden grid, nie dwa"
        # nagłówek: klik myszą nie zmienia miejsca
        win.show_find()
        rect = win.nav.visualItemRect(win.nav.item(NAV_WIECEJ))
        QTest.mouseClick(win.nav.viewport(), Qt.LeftButton, pos=rect.center())
        assert win.nav.currentRow() == NAV_ZNAJDZ and win.stack.currentIndex() == STRONA_ZBIORY
    finally:
        win.close()


def test_klawiatura_w_sidebarze_przeskakuje_naglowek_i_nie_grzeznie_w_Znajdz(qapp, tmp_path):
    """Strzałki w sidebarze omijają nagłówek „Więcej" i PRZECHODZĄ przez Znajdź: wejście strzałką
    przełącza stronę, ale fokus zostaje w liście (inaczej następna strzałka trafiałaby w pole
    zapytania i przeglądanie sidebara kończyłoby się na Znajdź). Enter na wierszu Znajdź = wejście
    do pracy: fokus w polu. Prawdziwe `QTest.keyClick` przy widżecie, który ma fokus."""
    win = _pokazane(MainWindow(_s8(tmp_path)))
    try:
        win.nav.setFocus(Qt.OtherFocusReason)
        QApplication.processEvents()
        assert win.nav.hasFocus() and win.nav.currentRow() == NAV_DOM
        for klawisz, wiersz, strona in ((Qt.Key_Down, NAV_ZNAJDZ, STRONA_ZBIORY),
                                        (Qt.Key_Down, NAV_DOSTAWA, STRONA_DOSTAWA),
                                        (Qt.Key_Down, NAV_ZBIORY, STRONA_ZBIORY),
                                        (Qt.Key_Up, NAV_DOSTAWA, STRONA_DOSTAWA),
                                        (Qt.Key_Up, NAV_ZNAJDZ, STRONA_ZBIORY)):
            QTest.keyClick(win.nav, klawisz)
            QApplication.processEvents()
            assert win.nav.currentRow() == wiersz and win.stack.currentIndex() == strona
            assert win.nav.hasFocus(), f"fokus uciekł z sidebara na wierszu {wiersz}"
        assert win.znajdz_view.prezentacja == "znajdz"
        QTest.keyClick(win.nav, Qt.Key_Return)
        QApplication.processEvents()
        assert QApplication.activeWindow() is win and win.znajdz_view.pole.hasFocus()
    finally:
        win.close()


def test_klik_w_wiersz_Znajdz_oddaje_fokus_polu(qapp, tmp_path):
    """Klik myszą w wiersz Znajdź = przyszedłem szukać: fokus w polu zapytania po obrocie pętli
    (Znajdź z sidebara to dalej „wpisz, Enter")."""
    win = _pokazane(MainWindow(_s8(tmp_path)))
    try:
        rect = win.nav.visualItemRect(win.nav.item(NAV_ZNAJDZ))
        QTest.mouseClick(win.nav.viewport(), Qt.LeftButton, pos=rect.center())
        QApplication.processEvents()
        assert win.nav.currentRow() == NAV_ZNAJDZ and win.stack.currentIndex() == STRONA_ZBIORY
        assert QApplication.activeWindow() is win and win.znajdz_view.pole.hasFocus()
    finally:
        win.close()


def test_kafle_prowadza_istniejacymi_drogami(qapp, tmp_path, monkeypatch):
    """Przyjmij → strona Dostawy (jedna interakcja); Znajdź → prezentacja Znajdź z fokusem w polu;
    Popraw → Porządki; Wydaj do WBPP → ISTNIEJĄCA droga gridu (okno teczek z odmową w drodze),
    bez zmiany strony."""
    okna = []

    class _OknoTeczek:
        def __init__(self, con, *, preselect=None, parent=None):
            okna.append(preselect)
            self.object_id = None

        def exec(self):
            return 0                                     # Anuluj

    monkeypatch.setattr(grid_mod, "ObjectPickDialog", _OknoTeczek)
    win = _pokazane(MainWindow(_s8(tmp_path)))
    try:
        win.activateWindow()
        h = win.home_view
        h.tile_przyjmij.click()
        assert win.stack.currentIndex() == STRONA_DOSTAWA and win.nav.currentRow() == NAV_DOSTAWA
        win._show_view(NAV_DOM)
        h.tile_znajdz.click()
        assert win.stack.currentIndex() == STRONA_ZBIORY and win.nav.currentRow() == NAV_ZNAJDZ
        assert win.znajdz_view.prezentacja == "znajdz"
        # Fokus PO obrocie pętli: „Znajdź = 2 interakcje" (wpisz, Enter) wymaga, żeby pole miało go
        # nadal, gdy człowiek zacznie pisać - a okno było aktywne.
        QApplication.processEvents()
        assert QApplication.activeWindow() is win, "wejście w Znajdź nie zdejmuje aktywacji okna"
        assert win.znajdz_view.pole.hasFocus(), "Znajdź z Domu = fokus w polu zapytania"
        win._show_view(NAV_DOM)
        h.tile_popraw.click()
        assert win.stack.currentIndex() == STRONA_PORZADKI and win.nav.currentRow() == NAV_PORZADKI
        win._show_view(NAV_DOM)
        h.tile_wydaj.click()
        assert okna == [None], "okno teczek otwarte drogą gridu"
        assert win.stack.currentIndex() == STRONA_DOM
    finally:
        win.close()


def test_popraw_N_to_ta_sama_liczba_co_plakietka(qapp, tmp_path):
    """Jeden sygnał stanu Porządków, dwa nośniki: plakietka sidebara i kafel Domu. Przy zerze oba
    gołe (bez „· 0" i bez „(0)")."""
    win = MainWindow(_s8(tmp_path))
    try:
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (6)"
        assert win.home_view.tile_popraw.text() == "Popraw · 6"
        win.tasks_view.counts_changed.emit(0)
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki"
        assert win.home_view.tile_popraw.text() == "Popraw"
        win.tasks_view.refresh_counts()
        assert win.home_view.tile_popraw.text() == "Popraw · 6"
    finally:
        win.close()


def test_klik_teczki_otwiera_Znajdz_z_facetem_obiektu(qapp, tmp_path):
    """Karta teczki → Znajdź z facetem tego obiektu przez publiczny seam gridu (`apply_object_facet`),
    ten sam, którym chodzi most planera."""
    path = str(tmp_path / "d.db")
    _baza_domu(path, _TRZY).close()
    win = MainWindow(path)
    try:
        karta = win.home_view.karty[1]
        assert karta.accessibleName() == "Sredni"
        karta.click()
        assert win.stack.currentIndex() == STRONA_ZBIORY and win.nav.currentRow() == NAV_ZNAJDZ
        assert win.grid_view._facet_state["object"]["in"] == [[3, "Sredni"]]
        assert len(win.grid_view._frame_ids) == 2
    finally:
        win.close()


def test_przelaczenie_prezentacji_z_wnetrza_strony_przesuwa_wiersz(qapp, tmp_path, monkeypatch):
    """Przycisk „Zbiory klasyczne" na pasku Znajdź przełącza prezentację z WNĘTRZA strony - sidebar
    ma pokazać właściwy wiersz, a `show_*` nie może pójść drugi raz (pętla przez `_on_nav_changed`)."""
    win = MainWindow(_s8(tmp_path))
    try:
        win.show_find()
        wolania = []
        zv = win.znajdz_view
        for nazwa in ("show_find", "show_classic"):
            oryginal = getattr(zv, nazwa)
            monkeypatch.setattr(zv, nazwa, lambda *a, n=nazwa, o=oryginal: (wolania.append(n), o(*a)))
        win.grid_view.classic_requested.emit()          # przycisk paska czasowników Znajdź
        assert win.nav.currentRow() == NAV_ZBIORY and win.stack.currentIndex() == STRONA_ZBIORY
        assert zv.prezentacja == "klasyczna"
        assert wolania == ["show_classic"], "jedno przełączenie - bez drugiego przez sidebar"
        zv.prezentacja_zmieniona.emit("znajdz")
        assert win.nav.currentRow() == NAV_ZNAJDZ
        zv.prezentacja_zmieniona.emit("znajdz")         # idempotentnie
        assert win.nav.currentRow() == NAV_ZNAJDZ
        assert wolania == ["show_classic"], "przesunięcie wiersza nie woła prezentacji"
    finally:
        win.close()


# ---------------------------------------------------------------- Ostatnio

def test_ostatnio_z_recepta_pierwszy_czlon_ta_sama_droga_i_zdjecie_z_obu(qapp, tmp_path, monkeypatch):
    """Dom pokazuje TĘ SAMĄ receptę, co pasek: przycisk niesie tekst PIERWSZEGO członu (bywa
    odsłonięciem celu, więc żadnego „Cofnij" na sztywno), dalsze człony stoją obok. Klik woła ten sam
    `_wykonaj_recepte`, z blokadą dwukliku wspólną z paskiem. Człon bez wykonawcy = przycisk
    wygaszony, zdanie zostaje. Pusta recepta zdejmuje ją z Domu i z paska."""
    win = _pokazane(MainWindow(_s8(tmp_path)))
    try:
        h = win.home_view
        assert h.ostatnio.isHidden()
        wykonane, wolania = [], []
        oryginal = win._wykonaj_recepte
        monkeypatch.setattr(win, "_wykonaj_recepte",
                            lambda **kw: (wolania.append(kw), oryginal(**kw)))
        recepta = Recepta([CzlonRecepty("odsłoni je: × Wyczyść zbiór", lambda: wykonane.append(1)),
                           CzlonRecepty("potem przywrócisz: Obiekt → Przywróć", None)])
        win.grid_view.status_recipe.emit(recepta)
        assert not h.ostatnio.isHidden() and not h.btn_recepta.isHidden()
        assert h.last_label.text() == "Ostatnio:"
        assert h.btn_recepta.text() == "odsłoni je: × Wyczyść zbiór"
        assert h.last_rest.text() == "potem przywrócisz: Obiekt → Przywróć"
        assert h.btn_recepta.isEnabled()
        assert win.recipe_label.isHidden(), "na Domu pasek recepty nie niesie"
        h.btn_recepta.click()
        assert wykonane == [1] and len(wolania) == 1
        assert not h.btn_recepta.isEnabled(), "blokada dwukliku"
        h.recepta_klik.emit()                            # drugi klik tego samego ruchu ręki
        assert wykonane == [1]
        win._odblokuj_recepte()
        assert h.btn_recepta.isEnabled()

        win.grid_view.status_recipe.emit(Recepta([CzlonRecepty("potem przywrócisz: Obiekt", None)]))
        assert not h.btn_recepta.isHidden() and not h.btn_recepta.isEnabled()
        assert h.btn_recepta.text() == "potem przywrócisz: Obiekt" and h.last_rest.isHidden()

        win.show_classic()
        win.grid_view.status_recipe.emit(recepta)
        assert not win.recipe_label.isHidden() and not h.btn_recepta.isHidden()
        win.grid_view.status_recipe.emit(Recepta([]))
        assert win.recipe_label.isHidden() and h.ostatnio.isHidden(), "zdjęta z obu"
    finally:
        win.close()


def test_ostatnio_bez_recepty_zdanie_z_dziennika_bez_przycisku(qapp, tmp_path):
    """Bez recepty w sesji Dom mówi zdaniem z dziennika i NIE daje przycisku - dziennik nie zna drogi
    powrotu. Gest zrobiony gdzie indziej stoi na Domu przy następnym wejściu; nieznany czasownik
    dostaje zdanie ogólne."""
    path = _s8(tmp_path)
    ts = "2026-10-04T12:00:00+00:00"
    _zdarzenia(path, [(ts, "user:local", "location.renamed", f"location:{i}") for i in range(15)])
    win = MainWindow(path, now_fn=lambda: DOM_NOW)
    try:
        h = win.home_view
        assert not h.ostatnio.isHidden() and h.btn_recepta.isHidden()
        assert h.last_label.text() == "Ostatnio (04.10): 15 plików przemianowano"
        _zdarzenia(path, [("2026-10-05T12:00:00+00:00", "user:local", "stack_versions.kept", "x:1"),
                          ("2026-10-05T12:00:00+00:00", "user:local", "stack_versions.kept", "x:2")])
        win._show_view(NAV_DOSTAWA)
        win._show_view(NAV_DOM)
        assert h.last_label.text() == "Ostatnio (05.10): 2 zmiany"
        assert h.btn_recepta.isHidden()
        win.grid_view.status_recipe.emit(Recepta([CzlonRecepty("cofniesz: Obiekt", lambda: None)]))
        # przy recepcie: najpierw CO zrobił gest, potem przycisk drogi powrotu
        assert h.last_label.text() == "Ostatnio (05.10): 2 zmiany ·"
        assert not h.btn_recepta.isHidden() and h.btn_recepta.text() == "cofniesz: Obiekt"
        win.grid_view.status_recipe.emit(Recepta([]))
        assert h.last_label.text() == "Ostatnio (05.10): 2 zmiany", "pusta recepta oddaje dziennik"
    finally:
        win.close()


def _zegar_rosnacy():
    """Zegar okna, który przesuwa się o sekundę na każde pytanie - gest i jego cofnięcie mają wtedy
    różne `ts`, jak w życiu (jeden `ts` skleiłby je w dzienniku w jeden gest)."""
    start = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    licznik = itertools.count()
    return lambda: (start + timedelta(seconds=next(licznik))).isoformat()


def _klik_wiersz(win, row):
    rect = win.nav.visualItemRect(win.nav.item(row))
    QTest.mouseClick(win.nav.viewport(), Qt.LeftButton, pos=rect.center())


@pytest.mark.parametrize("jezyk, przed, po", [
    ("pl", "Ostatnio (09.10): 3 klatkom zapisano uwagę ·", "Ostatnio (09.10): 3 klatkom usunięto uwagę"),
    ("en", "Last (10/09): note saved on 3 frames ·", "Last (10/09): note removed from 3 frames"),
])
def test_cofniecie_uwag_z_Domu_mowi_prawde_bez_wychodzenia(qapp, tmp_path, monkeypatch,
                                                           jezyk, przed, po):
    """Prawdziwa droga: gest „Uwagi…" w Zbiorach, wejście na Dom, „Cofnij uwagi" klikiem na Domu.
    Przy recepcie Dom mówi, CO zrobił gest (dziennik), i daje przycisk drogi powrotu na szerokość
    treści. Po cofnięciu recepta schodzi, a zdanie Domu jest od razu zdaniem o cofnięciu (`note.cleared`
    z powodem „cofnięcie") - nie o geście sprzed niego, bez wychodzenia z Domu.

    Falsyfikator: zdejmij ponowny odczyt dziennika z `HomeView.pokaz_recepte` → zdanie po cofnięciu
    dalej mówi „zapisano uwagę"."""
    from horreum.gui.note_dialog import NoteIntent

    class _OknoUwag:
        def __init__(self, *, current, frame_count, parent=None):
            self.intent = None

        def exec(self):
            self.intent = NoteIntent("set", "chmury")
            return 1

    i18n.set_lang(jezyk)
    monkeypatch.setattr(grid_mod, "NoteDialog", _OknoUwag)
    win = _pokazane(MainWindow(_s8(tmp_path), now_fn=_zegar_rosnacy()))
    try:
        g, h = win.grid_view, win.home_view
        win.show_classic()
        ids = sorted(g._frame_ids)[:3]
        g._przywroc_zaznaczenie(ids)
        g._on_notes()
        assert queries.notes_for(win.con, ids) == {fid: "chmury" for fid in ids}
        _klik_wiersz(win, NAV_DOM)
        QApplication.processEvents()
        assert win.stack.currentIndex() == STRONA_DOM
        assert h.last_label.text() == przed
        assert not h.btn_recepta.isHidden() and h.btn_recepta.isEnabled()
        assert h.btn_recepta.width() <= h.btn_recepta.sizeHint().width(), "przycisk na treść"
        h.btn_recepta.click()
        assert queries.notes_for(win.con, ids) == {}
        assert win.stack.currentIndex() == STRONA_DOM, "cofnięcie nie wyprowadza z Domu"
        assert h.last_label.text() == po
        assert h.btn_recepta.isHidden()
        assert win.statusBar().currentMessage().startswith(
            i18n.t("grid.notes.restored", changed=3).split(" · ")[0])
        ostatni = queries.last_hand_gesture(win.con)
        assert ostatni["verbs"] == {"note.cleared": 3}
        assert {r[0] for r in win.con.execute("SELECT reason FROM event WHERE ts = ?",
                                              (ostatni["ts"],))} == {"cofnięcie"}
    finally:
        win.close()


def test_strzalki_mijajace_Dom_nie_odczytuja_go_postoj_i_klik_tak(qapp, tmp_path, monkeypatch):
    """Odczyt Domu (~0,1 s na żywej bazie) nie idzie przy każdym MINIĘCIU wiersza strzałkami: czeka
    na postój, a gdy Dom zniknął przed jego końcem - nie idzie wcale. Klik i Enter na wierszu Dom
    odczytują od razu."""
    from horreum.gui.app import _DOM_POSTOJ_MS
    win = _pokazane(MainWindow(_s8(tmp_path)))
    try:
        odczyty = []
        oryginal = win.home_view.odswiez
        monkeypatch.setattr(win.home_view, "odswiez", lambda: (odczyty.append(1), oryginal()))
        win.nav.setFocus(Qt.OtherFocusReason)
        QApplication.processEvents()
        assert win.nav.hasFocus() and win.nav.currentRow() == NAV_DOM
        QTest.keyClick(win.nav, Qt.Key_Down)             # Znajdź
        QTest.keyClick(win.nav, Qt.Key_Up)               # Dom - tylko mijany
        QTest.keyClick(win.nav, Qt.Key_Down)             # Znajdź
        QTest.qWait(_DOM_POSTOJ_MS * 3)
        assert odczyty == [], "minięty Dom nie płaci odczytu"
        QTest.keyClick(win.nav, Qt.Key_Up)               # Dom - postój
        assert odczyty == []
        QTest.qWait(_DOM_POSTOJ_MS * 3)
        assert odczyty == [1]
        QTest.keyClick(win.nav, Qt.Key_Return)
        assert odczyty == [1, 1], "Enter na Domu odczytuje od razu"
        _klik_wiersz(win, NAV_DOM)
        assert odczyty == [1, 1, 1], "klik na Domu odczytuje od razu"
        QTest.qWait(_DOM_POSTOJ_MS * 3)
        assert odczyty == [1, 1, 1], "klik zatrzymał zegar postoju"
    finally:
        win.close()


def test_start_okna_liczy_Dom_raz(qapp, tmp_path, monkeypatch):
    """Montaż nie zamawia drugiego odczytu i drugiego rachunku teczek tuż po konstruktorze Domu."""
    odczyty, teczki = [], []
    for nazwa, lista in (("odswiez", odczyty), ("odswiez_teczki", teczki)):
        oryginal = getattr(HomeView, nazwa)
        monkeypatch.setattr(HomeView, nazwa,
                            lambda self, o=oryginal, l=lista: (l.append(1), o(self)))
    win = MainWindow(_s8(tmp_path))
    try:
        assert (odczyty, teczki) == ([1], [1])
        assert win.nav.currentRow() == NAV_DOM and win.stack.currentIndex() == STRONA_DOM
    finally:
        win.close()


def test_teczki_przy_wejsciu_na_Dom_widza_obiekt_nadany_poza_gridem(qapp, tmp_path):
    """Nadanie obiektu w Porządkach przenosi klatki między teczkami, a oś obiektu Porządków nie ma
    sygnału zmiany - teczki liczą się więc od nowa przy KAŻDYM wejściu na Dom (w tle, z generacją).
    Zmiana spoza gridu symulowana zapisem z drugiego połączenia."""
    path = str(tmp_path / "d.db")
    _baza_domu(path, _TRZY, extra=False).close()
    win = MainWindow(path)
    try:
        h = win.home_view
        assert [k.accessibleName() for k in h.karty] == ["Wiekszy", "Sredni", "Mniejszy"]
        con = db.open_db(path)
        con.execute("UPDATE frame SET object_id = 3 WHERE object_id = 1")   # Mniejszy → Sredni
        con.commit()
        con.close()
        win._show_view(NAV_PORZADKI)
        win._show_view(NAV_DOM)
        assert [k.accessibleName() for k in h.karty] == ["Wiekszy", "Sredni"]
        assert h.co_mam.text().startswith("Co mam: 2 obiekty · 6 lightów")
    finally:
        win.close()


# ---------------------------------------------------------------- Więcej…

def test_menu_wiecej_prowadzi_do_istniejacych_drog(qapp, tmp_path):
    """Każda pozycja „Więcej…" → istniejąca droga. Nazwy plików i makra otwierają panel paska zbioru
    KLIKIEM jego przycisku, tylko gdy panel jest zamknięty (drugi wybór nie chowa panelu)."""
    win = _pokazane(MainWindow(_s8(tmp_path)))
    try:
        win.activateWindow()
        h, g = win.home_view, win.grid_view
        akcje = h.akcje_wiecej
        assert [a.text() for a in h.btn_wiecej.menu().actions()] == [
            "Planer", "Mapa stanowisk", "Nazwy plików…", "Makra nagłówków…", "Perspektywy",
            "Tryb zaawansowany dostawy", "Zbiory klasyczne"]
        akcje[home_mod.WIECEJ_PLANER].trigger()
        assert win.stack.currentIndex() == STRONA_PLANER and win.nav.currentRow() == NAV_PLANER
        akcje[home_mod.WIECEJ_STANOWISKA].trigger()
        assert win.stack.currentIndex() == STRONA_PORZADKI
        assert win.tasks_view.pages.currentIndex() == tasks_mod._PAGE_OBSERVATORY
        akcje[home_mod.WIECEJ_NAZWY].trigger()
        assert win.nav.currentRow() == NAV_ZBIORY and win.znajdz_view.prezentacja == "klasyczna"
        assert not g.panel_stack.isHidden() and g.panel_stack.currentWidget() is g.rename_bar
        akcje[home_mod.WIECEJ_NAZWY].trigger()
        assert not g.panel_stack.isHidden() and g.sel_bar.btn_rename.isChecked(), "nie schowany"
        akcje[home_mod.WIECEJ_MAKRA].trigger()
        assert g.panel_stack.currentWidget() is g.macro_bar and g.sel_bar.btn_macro.isChecked()
        win._show_view(NAV_DOM)
        akcje[home_mod.WIECEJ_PERSPEKTYWY].trigger()
        QApplication.processEvents()
        assert win.nav.currentRow() == NAV_ZBIORY and g.combo_persp.hasFocus()
        akcje[home_mod.WIECEJ_DOSTAWA].trigger()
        assert win.stack.currentIndex() == STRONA_DOSTAWA and win.nav.currentRow() == NAV_DOSTAWA
        akcje[home_mod.WIECEJ_KLASYCZNE].trigger()
        assert win.nav.currentRow() == NAV_ZBIORY and win.znajdz_view.prezentacja == "klasyczna"
    finally:
        win.close()


# ---------------------------------------------------------------- przejścia przy zajętości

@pytest.fixture
def okno_ze_stagingiem(qapp, tmp_path):
    """Okno nad bazą z JEDNYM realnym plikiem FITS i makrem w stagingu (1 oczekująca zmiana)."""
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    p = tmp_path / "wb.fits"
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    hdu.header["TELESCOP"] = "RC8"
    hdu.header["IMAGETYP"] = "Light"
    hdu.writeto(str(p), overwrite=True)
    path = str(tmp_path / "wb.db")
    con = db.open_db(path)
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
    con.close()
    win = _pokazane(MainWindow(path))
    win.show_classic()
    g = win.grid_view
    g.sel_bar.btn_macro.click()
    g.macro_bar.asg_kw.setCurrentText("TELESCOP")
    g.macro_bar.asg_op.setCurrentIndex(0)
    g.macro_bar.asg_expr.setText("EQ6")
    g.macro_bar._emit_stage()
    assert g._pending_count() == 1 and g.drawer._n == 1
    yield win
    win.close()


def _stan_zbioru(g):
    return (copy.deepcopy(g._facet_state), copy.deepcopy(g._filter_tree), list(g._frame_ids),
            g._run_id, g._pending_count(), g.drawer._n)


def test_przejscia_przy_biegu_Dostawy_i_otwartym_stagingu(okno_ze_stagingiem):
    """Dom ↔ Znajdź ↔ Zbiory klasyczne ↔ Dostawa w trakcie biegu Dostawy (`set_busy`) i przy
    otwartym stagingu: staging i stan zbioru przeżywają każde przejście (ten sam grid), akcje zapisu
    zostają wygaszone, nawigacja aktywna. Kafel Przyjmij w biegu prowadzi na Dostawę, nie do
    drugiego biegu; „Wydaj do WBPP" Domu gaśnie jak „Wydaj obiekt…" gridu. Po biegu akcje wracają
    wg liczby oczekujących."""
    win = okno_ze_stagingiem
    g, h = win.grid_view, win.home_view
    przed = _stan_zbioru(g)
    win._on_pipeline_running(True)
    try:
        assert not h.tile_wydaj.isEnabled() and not g.sel_bar.btn_obj.isEnabled()
        assert h.tile_wydaj.toolTip() == i18n.t("home.tile.release_busy")
        trasy = [lambda: win._show_view(NAV_DOM), lambda: win.show_find(),
                 lambda: win.show_classic(), lambda: win._show_view(NAV_DOSTAWA),
                 lambda: win._show_view(NAV_DOM), lambda: h.tile_znajdz.click(),
                 lambda: win._show_view(NAV_DOM), lambda: h.tile_przyjmij.click(),
                 lambda: win.show_classic()]
        for krok in trasy:
            krok()
            assert win.nav.isEnabled()
            assert _stan_zbioru(g) == przed
            assert not g.drawer.btn_commit.isEnabled() and not g.macro_bar.btn_stage.isEnabled()
        h.tile_przyjmij.click()
        assert win.stack.currentIndex() == STRONA_DOSTAWA
        assert win.pipeline_view._thread is None, "kafel nie startuje biegu"
    finally:
        win._on_pipeline_running(False)
    assert h.tile_wydaj.isEnabled()
    win.show_find()
    assert g._pending_count() == 1 and g.drawer.btn_commit.isEnabled()


def test_przejscia_klawiatura_przy_otwartym_stagingu(okno_ze_stagingiem):
    """To samo prawdziwymi klawiszami w sidebarze (fokus na liście): Zbiory klasyczne ↔ Dostawa
    ↔ Znajdź ↔ Dom - staging i zbiór przeżywają, „Zatwierdź" czynny (bez biegu)."""
    win = okno_ze_stagingiem
    g = win.grid_view
    przed = _stan_zbioru(g)
    win.activateWindow()
    win.nav.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    assert win.nav.hasFocus() and win.nav.currentRow() == NAV_ZBIORY
    for klawisz, wiersz in ((Qt.Key_Up, NAV_DOSTAWA), (Qt.Key_Up, NAV_ZNAJDZ),
                            (Qt.Key_Up, NAV_DOM), (Qt.Key_Down, NAV_ZNAJDZ),
                            (Qt.Key_Down, NAV_DOSTAWA), (Qt.Key_Down, NAV_ZBIORY)):
        QTest.keyClick(win.nav, klawisz)
        QApplication.processEvents()
        assert win.nav.currentRow() == wiersz and win.nav.hasFocus()
        assert _stan_zbioru(g) == przed
        assert g.drawer.btn_commit.isEnabled()


# ---------------------------------------------------------------- sprzątanie wątków

def test_zamkniecie_i_zmiana_bazy_zbieraja_watki_Domu_i_gridu(qapp, tmp_path, monkeypatch):
    """Grid nie stoi już wprost na stosie (siedzi w kontenerze strony zbiorów) - gospodarz zbiera
    jego wątki tła jawnie, obok `zatrzymaj_pola` Domu. Bez tego zamknięcie okna w biegu składu
    zbioru kasowałoby żywy `QThread`."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", True)
    zebrane = []
    for klasa in (FramesView, HomeView):
        oryginal = klasa.zatrzymaj_pola
        monkeypatch.setattr(klasa, "zatrzymaj_pola",
                            lambda self, o=oryginal, k=klasa.__name__: (zebrane.append(k), o(self)))
    path = str(tmp_path / "d.db")
    _baza_domu(path, _TRZY).close()
    win = MainWindow(path)
    stary_dom = win.home_view
    win._open_path(_s8(tmp_path, "b.db"))
    assert {"FramesView", "HomeView"} <= set(zebrane)
    assert stary_dom._thread is None and win.home_view is not stary_dom
    zebrane.clear()
    win.close()
    assert {"FramesView", "HomeView"} <= set(zebrane)
    assert win.home_view._thread is None


# ---------------------------------------------------------------- PL/EN

def test_Dom_i_sidebar_po_angielsku(qapp, tmp_path):
    i18n.set_lang("en")
    path = str(tmp_path / "d.db")
    _baza_domu(path, _TRZY).close()
    win = MainWindow(path)
    try:
        etykiety = [win.nav.item(i).text() for i in range(win.nav.count())]
        assert etykiety[:5] == ["Home", "Find", "More", "Intake", "Classic collections"]
        assert etykiety[6] == "Planner" and etykiety[5].startswith("Housekeeping (")
        n = etykiety[5][len("Housekeeping ("):-1]        # liczba zadań tej bazy - z plakietki
        h = win.home_view
        assert [t.text() for t in (h.tile_przyjmij, h.tile_znajdz, h.tile_wydaj, h.tile_popraw)] == [
            "Receive", "Find", "Release to WBPP", f"Fix · {n}"]
        assert h.co_mam.text() == ("What I have: 3 objects · 8 lights · 3.3 h · 3 nights · "
                                   "last night 2024-03-05")
        assert h.btn_wiecej.text() == "More…"
        assert [k.accessibleName() for k in h.karty] == ["Wiekszy", "Sredni", "Mniejszy"]
    finally:
        win.close()
