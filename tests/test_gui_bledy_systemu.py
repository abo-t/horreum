"""Okna mówią błędem systemu KLASĄ w języku UI, a surowy tekst systemu stoi pod kursorem (AR-184,
AR-185, AR-183): awaria całej operacji pisarza (sygnał z trzecim argumentem, cztery odbiorcy),
kopia wiodąca, okno wydania, okno żniw, okno zmiany obiektu (plan i lista pominięć).

Co pilnujemy: zdanie w języku UI bez komunikatu systemu (ten jest w języku systemu), podpowiedź =
wiersz „Szczegół systemu: …” bez `repr` ścieżki, a NASTĘPNE zdanie tego samego pola podpowiedź
zdejmuje (pole błędu `EtykietaBledu`, raport wydania, notki żniw) - szczegół jednej awarii nie stoi pod
innym zdaniem. Szuflada Zbiorów nie gubi zdania błędu przy oczekujących zmianach. Ścieżki
syntetyczne (`X:\\L\\…`) i pliki w `tmp_path`; QSettings izolowane (conftest)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # przed importem Qt (klasa AR-170)

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from horreum import db, harvest, object_change, projection
from horreum.gui import i18n, queries
from horreum.gui.wb_worker import EtykietaBledu, WritebackWorker, wiersz_systemu
from horreum.item_reasons import blad_systemu

from test_gui_app_object import sciezka_karty  # noqa: F401 - fikstura okna „Zatwierdź ze ścieżki…”

NOW ="2026-10-16T00:00:00+00:00"
_POLSKIE = set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
_KOMUNIKAT = "Odmowa dostępu."
_SUROWY = rf"PermissionError: [WinError 5] {_KOMUNIKAT}: 'X:\L\a.fits'"   # bez `repr` ścieżki


def _odmowa(*_a, **_k):
    raise OSError(None, _KOMUNIKAT, r"X:\L\a.fits", 5)


def _tip():
    return i18n.t("wb.os_detail_tip", detail=_SUROWY)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def jezyk():
    yield i18n.set_lang
    i18n.set_lang("pl")


# ============================================================ AR-185: sygnał i pole błędu


def test_awaria_calej_operacji_niesie_szczegol_trzecim_argumentem(tmp_path, monkeypatch):
    """`WritebackWorker.run`: wyjątek klasy błędu systemu → `(op, zdanie UI, wiersz szczegółu)`;
    wyjątek spoza klas → podpowiedź pusta (nic nie zmyślamy). Falsyfikator: emisja bez podpowiedzi."""
    sciezka = str(tmp_path / "w.db")
    db.open_db(sciezka).close()
    bledy = []
    for wyjatek in (OSError(None, _KOMUNIKAT, r"X:\L\a.fits", 5), RuntimeError("w połowie")):
        def _pada(c, t, now, pr, sc, wyjatek=wyjatek):
            raise wyjatek
        monkeypatch.setitem(WritebackWorker._OPS, "commit", _pada)
        w = WritebackWorker(sciezka, "commit", "R", now_fn=lambda: NOW)
        w.failed.connect(lambda op, msg, tip: bledy.append((op, msg, tip)))
        w.run()
    assert bledy == [("commit", i18n.t("objchg.item.os_denied", os_code="WinError 5"), _tip()),
                     ("commit", "RuntimeError: w połowie", "")]


def test_etykieta_bledu_zdejmuje_podpowiedz_z_nowym_zdaniem(qapp):
    """Zwykły `QLabel` trzyma podpowiedź po `clear()` i po nowym `setText` (zmierzone, PySide6 6.9),
    więc szczegół jednej awarii stałby pod zdaniem walidacji. Podpowiedź pola niesie samo nowe zdanie
    (protokół AR-204: zdanie + szczegół, szczegół należy do zdania). Falsyfikator: bez nadpisanego
    `clear`."""
    pole = EtykietaBledu("")
    for zmiana, zdanie in ((lambda: pole.setText("inne zdanie"), "inne zdanie"), (pole.clear, "")):
        pole.setText("awaria")
        pole.setToolTip("szczegół")
        zmiana()
        assert pole.toolTip() == zdanie and pole.szczegol() == ""


def _klik(przycisk):
    """Prawdziwy klik myszą w środek przycisku (okno pokazane)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    assert przycisk.isVisible() and przycisk.isEnabled(), przycisk.text()
    QTest.mouseClick(przycisk, Qt.LeftButton)


@pytest.mark.parametrize("ktore", ["naprawa", "sciezka"])
@pytest.mark.parametrize("lang", ["pl", "en"])
def test_okna_kart_po_awarii_operacji_szczegol_w_podpowiedzi(qapp, tmp_path, jezyk, lang, ktore,
                                                             monkeypatch, request):
    """Oba okna kart („Napraw nagłówek…”, „Zatwierdź ze ścieżki…”) przez PRZYCISK zapisu i ich
    produkcyjne podpięcie uchwytu: awaria całej operacji mówi klasą w języku UI, szczegół systemu pod
    kursorem pola błędu, a następne zdanie okna (`_fail`/`setText` - walidacja, „brak gospodarza”) go
    zdejmuje. Falsyfikator: `_on_failed` bez szczegółu, pole błędu jako zwykły `QLabel` albo
    odbiorca porażki podpięty z dwoma parametrami (`WritebackRunner.start` odmawia od razu)."""
    jezyk(lang)
    if ktore == "naprawa":
        from test_gui_object_change import _lighty, _okno_naprawy
        con = db.open_db(str(tmp_path / "k.db"))
        _lighty(tmp_path / "ASTRO_", con, "NGC7635", 1, baza=7)
        dlg = _okno_naprawy(con)
        przycisk = dlg.save_btn
    else:
        from test_gui_app_object import _okno_sciezki
        v, con, _pliki, _fid = request.getfixturevalue("sciezka_karty")
        dlg = _okno_sciezki(v, con)
        przycisk = dlg.confirm_btn
    monkeypatch.setitem(WritebackWorker._OPS, "commit_inplace", _odmowa)
    assert isinstance(dlg.error, EtykietaBledu)
    dlg.show()
    _klik(przycisk)
    zdanie = dlg.error.text()
    assert i18n.t("objchg.item.os_denied", os_code="WinError 5") in zdanie, zdanie
    assert dlg.error.szczegol() == _tip()                              # protokół pola (AR-204)
    assert dlg.error.toolTip() == zdanie + "\n" + _tip(), dlg.error.toolTip()
    if lang == "en":
        assert not set(zdanie) & _POLSKIE, zdanie
    dlg.error.setText(i18n.t("repair.err.no_host"))
    assert dlg.error.toolTip() == i18n.t("repair.err.no_host")      # samo nowe zdanie (AR-204)
    dlg.reject()
    if ktore == "naprawa":
        con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_szuflada_po_awarii_mowi_blad_i_szczegol_mimo_oczekujacych(qapp, tmp_path, jezyk, lang,
                                                                    monkeypatch):
    """Wyjątek całej operacji commitu (klik „Zatwierdź” szuflady), gdy staging ma pozycje: dawniej
    `_refresh_drawer` po zdaniu błędu czyścił je w tej samej chwili (zmierzone: pusty wynik
    szuflady). Teraz szuflada mówi błąd, a pod kursorem ma szczegół systemu. Falsyfikator: zdanie
    błędu przed `_refresh_drawer` bez ponowienia → pusty wynik."""
    from test_gui_powody_pisarza import _widok_nad
    jezyk(lang)
    view, con, _p = _widok_nad(qapp, tmp_path)
    view.show()
    bar = view.macro_bar
    bar.asg_kw.setCurrentText("TELESCOP")
    bar.asg_op.setCurrentIndex(0)
    bar.asg_expr.setText("EQ6")
    bar._emit_stage()
    assert view._pending_count() == 1
    monkeypatch.setitem(WritebackWorker._OPS, "commit", _odmowa)
    _klik(view.drawer.btn_commit)
    assert view._pending_count() == 1                         # staging przeżył awarię
    tekst = view.drawer.result.text()
    assert tekst == i18n.t("grid.wb.error", msg=i18n.t("objchg.item.os_denied", os_code="WinError 5"))
    assert view.drawer.result.toolTip() == tekst + "\n" + _tip()
    view.close()
    con.close()


@pytest.mark.parametrize("lang, oczek", [
    ("pl", ["1 zmiana oczekuje", "2 zmiany oczekują", "5 zmian oczekuje", "12 zmian oczekuje",
            "22 zmiany oczekują"]),
    ("en", ["1 change pending", "2 changes pending", "5 changes pending", "12 changes pending",
            "22 changes pending"])])
def test_licznik_szuflady_odmienia_liczbe(qapp, jezyk, lang, oczek):
    """„1 zmian oczekuje” stało przy każdym pojedynczym stagingu. Odmiana 1/2/5/12/22 w etykiecie
    szuflady (domyślny tekst `set_count`). Falsyfikator: `i18n.t` zamiast `t_plural`."""
    from horreum.gui.grid_selection import StagingDrawer
    jezyk(lang)
    szuflada = StagingDrawer()
    wynik = []
    for n in (1, 2, 5, 12, 22):
        szuflada.set_count(n)
        wynik.append(szuflada.label.text())
    assert wynik == oczek


@pytest.mark.parametrize("lang, oczek", [
    ("pl", ["1 zmiana nazwy oczekuje", "2 zmiany nazw oczekują", "5 zmian nazw oczekuje",
            "12 zmian nazw oczekuje", "22 zmiany nazw oczekują"]),
    ("en", ["1 name change pending", "2 name changes pending", "5 name changes pending",
            "12 name changes pending", "22 name changes pending"])])
def test_licznik_szuflady_nazw_odmienia_liczbe_u_obu_wolajacych(qapp, tmp_path, jezyk, lang, oczek,
                                                                monkeypatch):
    """Szuflada klingi Nazw: „1 zmian nazw oczekuje” - ten sam błąd liczebnika. Obaj wołający -
    odświeżenie szuflady i ogon przerwanego commitu Nazw - mówią odmienioną frazą.
    Falsyfikator: `i18n.t` zamiast `t_plural` u któregoś z nich."""
    from horreum import writeback
    from test_gui_powody_pisarza import _widok_nad
    jezyk(lang)
    view, con, _p = _widok_nad(qapp, tmp_path)
    for kto in ("_refresh_drawer", "_after_commit_rename"):
        wynik = []
        for n in (1, 2, 5, 12, 22):
            monkeypatch.setattr(view, "_rename_pending_count", lambda n=n: n)
            if kto == "_refresh_drawer":
                view._refresh_drawer()
            else:
                monkeypatch.setattr(view, "_refresh_drawer", lambda: None)
                view._after_commit_rename("commit_rename", writeback.CommitResult("r", None, [], [], [], []))
            wynik.append(view.drawer.label.text())
        assert wynik == oczek, (kto, wynik)
    view.close()
    con.close()


# ============================================================ okno zmiany obiektu (AR-185, AR-183, AR-184)


def _okno_uzgodnij(con, monkeypatch, **kw):
    from horreum import resolver
    from horreum.gui.object_change_dialog import ObjectChangeDialog
    ids = [r[0] for r in con.execute("SELECT id FROM frame")]
    monkeypatch.setattr(resolver, "library_root_from_db", lambda c: kw.pop("korzen", None))
    return ObjectChangeDialog(con, frame_ids=ids, target=kw.pop("target", None), now_fn=lambda: NOW,
                              db_path=queries.db_path_of(con), off_thread=False)


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_zmiana_obiektu_awaria_operacji_i_planu_szczegol_w_podpowiedzi(qapp, tmp_path, jezyk, lang,
                                                                       monkeypatch):
    """Okno zmiany obiektu: wyjątek planu (`PlanWorker`, zerwany udział) i wyjątek całej operacji
    zapisu (klik akcji okna, produkcyjne podpięcie uchwytu) mówią klasą w języku UI, szczegół
    systemu - pod kursorem pola błędu; ponowne policzenie planu zdejmuje go razem ze zdaniem.
    Falsyfikator: `_on_plan_failed` z `czytelny_powod(msg)` na `PowodPozycji` → polskie zdanie klasy
    w EN, bez podpowiedzi; `_on_failed` bez podpowiedzi."""
    from horreum.gui import object_change_dialog as ocd
    from test_gui_object_change import _lighty
    jezyk(lang)
    con = db.open_db(str(tmp_path / "o.db"))
    root = tmp_path / "ASTRO_"
    _lighty(root, con, "NGC7635", 1, baza=3)

    def zerwany(*_a, **_k):
        raise OSError(None, "Nazwa sieciowa jest już niedostępna", r"X:\L", 64)
    with monkeypatch.context() as m:
        m.setattr(ocd, "policz_plan", zerwany)
        dlg = _okno_uzgodnij(con, monkeypatch)
    zdanie = dlg.error.text()
    assert zdanie == i18n.t("objchg.err.plan", msg=i18n.t("objchg.item.os_share_lost",
                                                         os_code="WinError 64")), zdanie
    assert dlg.error.toolTip() == zdanie + "\n" + i18n.t(   # protokół `EtykietaBledu.ustaw`
        "wb.os_detail_tip", detail=r"OSError: [WinError 64] Nazwa sieciowa jest już niedostępna: 'X:\L'")
    dlg._licz_plan()                                    # „Policz plan ponownie” - pole błędu od nowa
    assert dlg.error.toolTip() == ""
    dlg.reject()
    zmiana = _okno_uzgodnij(con, monkeypatch, korzen=str(root),
                            target=queries.object_target(con, "NGC7635"))
    zmiana._runner.async_ok = False
    monkeypatch.setitem(WritebackWorker._OPS, "object_change", _odmowa)
    zmiana.show()
    _klik(zmiana.action_btn)
    assert i18n.t("objchg.item.os_denied", os_code="WinError 5") in zmiana.error.text()
    assert zmiana.error.toolTip() == zmiana.error.text() + "\n" + _tip()
    if lang == "en":
        assert not set(zmiana.error.text()) & _POLSKIE, zmiana.error.text()
    zmiana.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_planer_zerwany_udzial_w_oknie_jezyk_UI_i_szczegol(qapp, tmp_path, jezyk, lang, monkeypatch):
    """AR-183 w oknie: katalog celu na zerwanym udziale (53 - `FileNotFoundError`) stoi na liście
    pominięć zdaniem „udział sieciowy albo dysk nie odpowiada”, nie „katalog nie istnieje”; pod
    kursorem grupy - surowy tekst systemu. Falsyfikator: podpowiedź grupy = samo zdanie."""
    from horreum.gui.object_change_dialog import tekst_pominiecia
    from test_gui_object_change import _lighty
    jezyk(lang)
    con = db.open_db(str(tmp_path / "u.db"))
    root = tmp_path / "ASTRO_"
    _lighty(root, con, "NGC7635", 1, baza=4)
    os.makedirs(root / "LIGHTS" / "NGC5" / "RC8_2600MC")
    oryg = object_change.plan_object_change

    def listdir(katalog):
        if "NGC5" in katalog:
            raise OSError(None, "Nie można odnaleźć ścieżki sieciowej", katalog, 53)
        return os.listdir(katalog)
    monkeypatch.setattr(object_change, "plan_object_change",
                        lambda rows, **kw: oryg(rows, listdir=listdir, **kw))
    dlg = _okno_uzgodnij(con, monkeypatch, korzen=str(root),
                         target=queries.object_target(con, "NGC5"))
    grupy = [dlg.skipped_tree.topLevelItem(i) for i in range(dlg.skipped_tree.topLevelItemCount())]
    kody = [s.code for s in dlg._plan.skipped]
    assert kody == ["dir_share_lost"], kody
    s = dlg._plan.skipped[0]
    zdanie = tekst_pominiecia(s.code, s.params, s.reason)
    assert zdanie == i18n.t("objchg.skip.dir_share_lost", os_code="WinError 53", dir=dict(s.params)["dir"])
    (g,) = grupy
    assert g.text(0) == zdanie
    assert g.toolTip(0).startswith(zdanie + "\n" + i18n.t(
        "wb.os_detail_tip", detail="FileNotFoundError: [WinError 53] Nie można odnaleźć ścieżki sieciowej"))
    if lang == "en":
        assert not set(zdanie) & _POLSKIE, zdanie
    dlg.reject()
    con.close()


# ============================================================ okna wydania i żniw (AR-184)


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_okno_wydania_awaria_klasa_i_szczegol_a_nastepny_raport_go_zdejmuje(qapp, tmp_path, ustawienia,
                                                                         jezyk, lang, monkeypatch):
    """Okno wydania: wyjątek spoza kroków wydania (nieoczekiwany błąd systemu w `apply` - kroki
    korzenia, sondy i manifestu oddają wynik z powodem, AR-197) mówi klasą w języku UI, szczegół
    systemu pod kursorem raportu; następny raport go zdejmuje. Falsyfikator:
    `_show_report` bez zerowania podpowiedzi."""
    from horreum.gui import projection_dialog as pd_mod
    from test_gui_projection import _dlg, _seed_files, _target
    jezyk(lang)
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "w.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    monkeypatch.setattr(projection, "apply", _odmowa)
    dlg._on_apply()
    raport = dlg.report.toPlainText()
    assert i18n.t("objchg.item.os_denied", os_code="WinError 5") in raport, raport
    assert dlg.report.toolTip() == _tip()
    if lang == "en":
        assert _KOMUNIKAT not in raport
    dlg._show_report("następny raport")
    assert dlg.report.toolTip() == ""
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_zniwa_tabela_notki_i_pasek_klasa_w_jezyku_UI_szczegol_w_podpowiedzi(qapp, tmp_path, ustawienia,
                                                                          jezyk, lang, monkeypatch):
    """Okno żniw: pozycja `error` (kopia klingą padła błędem systemu) - komórka „Powód” mówi klasą
    w języku UI, podpowiedź komórki niesie surowy tekst; wyjątek całej operacji - notka i zdanie
    paska klasą, szczegół pod kursorem notki; następna notka go zdejmuje. Falsyfikator:
    `reason_text` bez `tekst_powodu` albo `_on_apply_failed` z surowym `msg`."""
    import dataclasses
    from horreum.gui.harvest_dialog import COL_REASON
    from test_gui_harvest import _baza, _czytnik, _dlg, _flat_cls, _wyjscie
    jezyk(lang)
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    klasa = i18n.t("objchg.item.os_denied", os_code="WinError 5")
    pozycja = dataclasses.replace(dlg._plan.items[0], status="error",
                                  detail=blad_systemu(OSError(None, _KOMUNIKAT, r"X:\L\a.fits", 5)))
    dlg._fill([pozycja])
    komorka = dlg.table.item(0, COL_REASON)
    assert komorka.text() == klasa and komorka.toolTip() == klasa + "\n" + _tip()
    monkeypatch.setattr(harvest, "apply", _odmowa)
    dlg._on_apply()
    assert dlg.notice.text() == i18n.t("harvest.apply_error", msg=klasa, made="")
    assert dlg.notice.toolTip() == dlg.notice.text() + "\n" + _tip()
    assert klasa in dlg.summary and _KOMUNIKAT not in dlg.summary, dlg.summary
    dlg._show_notice("następna notka")
    assert dlg.notice.toolTip() == "następna notka"
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_zniwa_siedziba_nieczytelna_zdanie_w_jezyku_UI(jezyk, lang):
    """Pozycja planu `seat_unreadable` (siedziba na zerwanym udziale): kolumna „Powód” mówi zdaniem
    katalogu i klasą błędu w języku UI - bez komunikatu systemu i bez surowego tokenu."""
    from types import SimpleNamespace
    from horreum.gui.harvest_dialog import reason_text
    jezyk(lang)
    powod = blad_systemu(OSError(None, "Nie można odnaleźć ścieżki sieciowej", r"X:\A\CALIBRATION", 53))
    it = SimpleNamespace(reason="seat_unreadable", reason_n=None, detail=powod, kind="master_flat",
                         status="review", exists_path=None)
    tekst = reason_text(it)
    assert tekst == (i18n.t("harvest.reason.seat_unreadable") + ": "
                     + i18n.t("objchg.item.os_share_lost", os_code="WinError 53")), tekst
    if lang == "en":
        assert not set(tekst) & _POLSKIE, tekst


def test_wiersz_systemu_tylko_dla_klasy():
    """Pomocnik podpowiedzi: wiersz wyłącznie przy błędzie systemu klasą; tekst spoza klas i brak
    powodu - pusty (bez zmyślonego szczegółu)."""
    assert wiersz_systemu(blad_systemu(OSError(None, _KOMUNIKAT, r"X:\L\a.fits", 5))) == _tip()
    assert wiersz_systemu(blad_systemu(OSError(None, "zajęty", r"X:\L\a.fits", 32))) == ""
    assert wiersz_systemu(None) == "" and wiersz_systemu("OSError: x") == ""


# ============================================================ tura naprawcza bramki kodu


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_szuflada_awaria_cofniecia_przy_zywym_Cofnij_zostawia_Zatwierdzono(qapp, tmp_path, jezyk, lang,
                                                                         monkeypatch):
    """Klik „Cofnij” po prawdziwym commicie, cofnięcie pada wyjątkiem całej operacji: etykieta szuflady
    zostaje „Zatwierdzono…” (dawne `set_count(0, …)` nadpisywało ją pustostanem), Zatwierdź/Odrzuć
    schowane (jedyną akcją jest „Cofnij”), wynik = zdanie błędu, podpowiedź = zdanie + szczegół
    systemu. Falsyfikator: `set_count` przed `_refresh_drawer` albo brak `set_commit_actions_visible`."""
    from test_gui_powody_pisarza import _widok_nad
    jezyk(lang)
    view, con, _p = _widok_nad(qapp, tmp_path)
    view.show()
    bar = view.macro_bar
    bar.asg_kw.setCurrentText("TELESCOP")
    bar.asg_op.setCurrentIndex(0)
    bar.asg_expr.setText("EQ6")
    bar._emit_stage()
    _klik(view.drawer.btn_commit)                             # prawdziwy commit - „Cofnij” żyje
    assert view._undo_mode == "macro"
    etykieta = i18n.t("grid.wb.committed_label", n=1, id=view._undo_commit_id)
    assert view.drawer.label.text() == etykieta
    monkeypatch.setitem(WritebackWorker._OPS, "undo", _odmowa)
    _klik(view._undo_btn)
    blad = i18n.t("grid.wb.error", msg=i18n.t("objchg.item.os_denied", os_code="WinError 5"))
    assert view.drawer.label.text() == etykieta
    assert view.drawer.btn_commit.isHidden() and view.drawer.btn_reject.isHidden()
    assert view._undo_btn.isVisible()
    assert view.drawer.result.text() == blad
    assert view.drawer.result.toolTip() == blad + "\n" + _tip()
    view.close()
    con.close()


def test_uchwyt_zapisu_odmawia_odbiorcy_porazki_ze_zla_arnoscia(qapp):
    """`WritebackRunner.start` sprawdza arność odbiorcy porażki od razu (EXPECT): odbiorca z dwoma
    parametrami zgubiłby szczegół systemu po cichu (PySide przycina argumenty sygnału). Falsyfikator:
    bez `inspect.signature(...).bind` start przechodzi."""
    from horreum.gui.wb_worker import WritebackRunner
    uchwyt = WritebackRunner("", now_fn=lambda: NOW)
    with pytest.raises(TypeError):
        uchwyt.start("commit", "R", on_progress=lambda *a: None, on_done=lambda *a: None,
                     on_failed=lambda op, msg: None)
    assert not uchwyt.is_busy


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_odmowa_klingi_z_kodem_uciekajaca_z_operacji_mowi_swoim_kodem(tmp_path, jezyk, lang,
                                                                     monkeypatch):
    """Odmowa klingi z kodem (`OdmowaZPowodem`) potrafi uciec z operacji uchwytu - gest kopii wiodącej
    liczy pochodne, a resolver woła `repo.upsert_object` bez handlera (`retired_via_xref`). Wykonawca
    mówi wtedy KODEM odmowy w języku UI, nie `OdmowaZPowodem: …` po polsku; podpowiedź pusta (to nie
    błąd systemu). Falsyfikator: `run` z samym `blad_systemu(exc)`."""
    from horreum.gui.wb_worker import tekst_powodu
    from horreum.item_reasons import OdmowaZPowodem, PowodPozycji
    jezyk(lang)
    sciezka = str(tmp_path / "w.db")
    db.open_db(sciezka).close()
    powod = PowodPozycji("obiekt 'M33' to nagrobek, a jego kanon prowadzi dziś przez parę katalogową "
                         "do 'NGC598' - nagrobka nie wskrzeszam, celem jest 'NGC598'", "retired_via_xref",
                         canon="M33", target="NGC598")

    def pada(*_a):
        raise OdmowaZPowodem(powod)
    monkeypatch.setitem(WritebackWorker._OPS, "lead_copy", pada)
    bledy = []
    w = WritebackWorker(sciezka, "lead_copy", 1, now_fn=lambda: NOW)
    w.failed.connect(lambda op, msg, tip: bledy.append((msg, tip)))
    w.run()
    assert bledy == [(tekst_powodu(powod), "")]
    if lang == "en":
        assert not set(bledy[0][0]) & _POLSKIE, bledy


def _czekaj(warunek, ms=10000):
    """Pętla zdarzeń kręci się do warunku (wątek tła) - `processEvents` + `sleep`, nie `qWait`."""
    import time
    for _ in range(ms // 10):
        QApplication.processEvents()
        if warunek():
            return True
        time.sleep(0.01)
    return warunek()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_sloty_okien_wydania_i_zniw_mowia_klasa_i_szczegol(qapp, tmp_path, ustawienia, jezyk, lang,
                                                          monkeypatch):
    """Sloty porażki workerów okien z błędem klasą: sonda okna wydania, sonda żniw i lista wydań
    (PRAWDZIWY wątek tła - połączenie kolejkowane); bieg żniw - test wyżej. Każdy mówi zdaniem klasy
    w języku UI, szczegół systemu w podpowiedzi. Falsyfikator: slot bez `tekst_powodu` - w EN polskie
    zdanie klasy; `Signal(str)` zamiast `object` - kod gubi się w drodze przez wątek."""
    from horreum.gui import projection_dialog as pd_mod
    from test_gui_harvest import _baza, _czytnik, _dlg as _dlg_zniw, _flat_cls, _wyjscie
    from test_gui_projection import _dlg as _dlg_wydania, _seed_files, _target
    jezyk(lang)
    klasa = i18n.t("objchg.item.os_denied", os_code="WinError 5")
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con_w = db.open_db(str(tmp_path / "w.db"))
    ids = _seed_files(con_w, tmp_path, 1)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    with monkeypatch.context() as m:
        m.setattr(projection, "apply", _odmowa)
        wydanie = _dlg_wydania(con_w, ids)
    assert wydanie.report.toPlainText().startswith(i18n.t("proj.dry_failed", msg=klasa)), \
        wydanie.report.toPlainText()
    assert wydanie.report.toolTip() == _tip()
    wydanie.reject()
    con_w.close()
    (tmp_path / "z").mkdir()
    con, _profile, _flats = _baza(tmp_path / "z")
    out = _wyjscie(tmp_path / "z", {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    zniwa = _dlg_zniw(con, tmp_path / "z" / "ARCH")
    with monkeypatch.context() as m:
        m.setattr(harvest, "plan", _odmowa)
        zniwa._set_output(str(out))
    assert zniwa.notice.text() == i18n.t("harvest.dry_failed", msg=klasa), zniwa.notice.text()
    assert zniwa.notice.toolTip() == zniwa.notice.text() + "\n" + _tip()
    zniwa.reject()
    karta = tmp_path / "z" / "_WBPP"
    karta.mkdir()
    monkeypatch.setattr(harvest, "releases", _odmowa)
    lista = _dlg_zniw(con, tmp_path / "z" / "ARCH", release_roots=(str(karta),), off_thread=True)
    oczek = i18n.t("harvest.rel.failed", msg=klasa)
    assert _czekaj(lambda: lista.rel_notice.text() == oczek), lista.rel_notice.text()
    assert lista.rel_notice.toolTip() == oczek + "\n" + _tip()
    assert _czekaj(lambda: lista._rel_thread is None)
    lista.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_planer_brak_miejsca_w_oknie_zdanie_klasy_w_jezyku_UI_i_szczegol(jezyk, lang):
    """Brak miejsca przy odczycie katalogu celu (112, 39, errno ENOSPC): zdanie klasy w języku UI
    z numerem (dawniej polskie zdanie klasy wpadało w `{detail}` zdania „nieczytelny” - w UI EN po
    polsku, a surowa diagnoza ginęła), surowy tekst systemu w podpowiedzi grupy. Falsyfikator: gałąź
    reszty `_Dysk.wpisy` z `str(tekst)` dla klasy `os_no_space`."""
    import errno
    from horreum.gui.object_change_dialog import podpowiedz_pominiecia, tekst_pominiecia
    jezyk(lang)
    katalog = r"X:\L\NGC1\cam"
    for exc, os_code in ((OSError(None, "Za mało miejsca na dysku.", katalog, 112), "WinError 112"),
                         (OSError(None, "Dysk jest pełny.", katalog, 39), "WinError 39"),
                         (OSError(errno.ENOSPC, "No space left on device"), "Errno 28")):
        def listdir(_k, exc=exc):
            raise exc
        with pytest.raises(object_change._Odmowa) as odmowa:
            object_change._Dysk(os.path.isdir, listdir).wpisy(katalog)
        zdanie_pl, kod, params = odmowa.value.wpis
        tekst = tekst_pominiecia(kod, params, zdanie_pl)
        assert kod == "dir_no_space" and tekst == i18n.t("objchg.skip.dir_no_space", os_code=os_code,
                                                         dir=katalog), tekst
        if lang == "en":
            assert not set(tekst) & _POLSKIE, tekst
        else:
            assert tekst == zdanie_pl
        surowy = f"{type(exc).__name__}: {exc}".replace("\\\\", "\\")
        assert podpowiedz_pominiecia(kod, params, tekst) == tekst + "\n" + i18n.t("wb.os_detail_tip",
                                                                                  detail=surowy)


def test_powod_zniw_bez_kodu_przechodzi_przez_czytelny_powod(jezyk):
    """`reason_text`: dane bez kodu idą przez `czytelny_powod` - ścieżka w zapisie `repr` traci
    podwojone ukośniki, reszta znak w znak (docstring mówi prawdę o tej drodze)."""
    from types import SimpleNamespace
    from horreum.gui.harvest_dialog import reason_text
    jezyk("pl")
    it = SimpleNamespace(reason=None, reason_n=None, detail=r"cel istnieje 'X:\\a'", kind="master_flat",
                         status="conflict", exists_path=None)
    assert reason_text(it) == r"cel istnieje 'X:\a'"


def test_okno_zniw_sufit_z_ekranu_rodzica(qapp, tmp_path, monkeypatch):
    """Sufit szerokości i wysokości okna żniw liczy się z ekranu RODZICA (tam `QDialog.showEvent`
    stawia okno), nie z ekranu własnego niepokazanego okna - na dwóch monitorach okno nad małym
    ekranem rosło pod ekran duży i wychodziło poza swój. Falsyfikator: `self.screen()` w
    `_grow_to_table`/`_fit_height`."""
    import dataclasses
    from types import SimpleNamespace
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QWidget
    from horreum.gui import harvest_dialog as hd_mod
    from test_gui_harvest import _baza, _czytnik, _dlg, _flat_cls, _wyjscie
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    maly = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1100, 700))
    duzy = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 3800, 2100))
    rodzic = QWidget()
    rodzic.screen = lambda: maly
    dlg = _dlg(con, tmp_path / "ARCH", parent=rodzic)
    dlg.screen = lambda: duzy
    dlg._set_output(str(out))
    dlugi = dataclasses.replace(dlg._plan.items[0], status="conflict", detail="x" * 600)
    dlg._fill([dlugi])
    assert dlg.width() <= int(1100 * hd_mod._SCREEN_SHARE), dlg.width()
    dlg._fit_height()
    assert dlg.height() <= 700, dlg.height()
    dlg.reject()
    con.close()


# Parametry `msg=`/`err=`/`e=`/`exc=`/`error=` zdań GUI bez opakowania powodu (rozszerzenie zapadki
# AR-167 z `test_gui_powody_pisarza.py` na parametry tekstu błędu; `exc`/`error` - AR-210) - znane
# wyjątki z kategorią. Nowy surowy przypadek = czerwień; naprawiony musi zejść z listy.
_ODMOWA_OSI = "odmowa klingi osi albo okna (`ValueError`) - nie błąd systemu plików"
_ZNANE_SUROWE_MSG = {
    ("app.py", "TelescopeAxisView._on_item_changed", "e", "e"): _ODMOWA_OSI,
    ("app.py", "TelescopeAxisView._on_optics_edited", "e", "e"): _ODMOWA_OSI,
    ("app.py", "TelescopeAxisView._on_restore_optics", "e", "e"): _ODMOWA_OSI,
    ("app.py", "TelescopeAxisView._on_approve", "e", "e"): _ODMOWA_OSI,
    ("app.py", "TelescopeAxisView._on_merge", "e", "e"): _ODMOWA_OSI,
    ("app.py", "TelescopeAxisView._on_unmerge", "e", "e"): _ODMOWA_OSI,
    ("app.py", "ObservatoryAxisView._on_item_changed", "e", "e"): _ODMOWA_OSI,
    ("app.py", "ObservatoryAxisView._on_merge", "e", "e"): _ODMOWA_OSI,
    ("app.py", "ObservatoryAxisView._on_unmerge", "e", "e"): _ODMOWA_OSI,
    ("grid.py", "FramesView._on_wb_failed", "msg", "msg"):
        "zdanie z wykonawcy (`WritebackWorker.run` - `tekst_powodu`)",
    ("grid.py", "FramesView._on_pola_failed", "msg", "msg"):
        "zdanie z wykonawcy (`PolaWorker.run` - `tekst_powodu`)",
    ("grid.py", "FramesView._after_undo", "msg", "msg"): "zdanie z `ogon_cofniecia` (`tekst_powodu` wewnątrz)",
    ("grid.py", "FramesView._after_undo_rename", "msg", "msg"):
        "zdanie z `ogon_cofniecia` (`tekst_powodu` wewnątrz)",
    ("grid.py", "FramesView._on_transfer_facts", "err", "str(e)"): _ODMOWA_OSI,
    ("harvest_dialog.py", "HarvestDialog._on_apply_failed", "msg", "msg"): "zdanie po `tekst_powodu` w tej funkcji",
    ("harvest_dialog.py", "HarvestDialog._summary_fact", "msg", "self._last_error"): "zdanie z `_on_apply_failed`",
    ("harvest_dialog.py", "HarvestDialog._summary_tail", "msg", "self._last_error"): "zdanie z `_on_apply_failed`",
    ("observatory_dialog.py", "AssignObservatoryDialog._validate_and_accept", "e", "e"): _ODMOWA_OSI,
    ("pipeline.py", "PipelineView._pokaz_odmowe", "msg", "msg"): "worker Dostawy - poza drogami plików (rejestr)",
}


def _wolania_zdan_gui():
    """Każdy parametr wołania `i18n.t`/`t_plural` w modułach `horreum/gui` RAZEM z podkatalogami
    (`flows/`): `(plik, nazwa funkcji, parametr, węzeł wartości, opakowana?, nazwy z except)`. Plik
    względem `horreum/gui` (`flows/przyjmij.py`), nazwa funkcji kwalifikowana łańcuchem klas i funkcji
    nad wołaniem (`TelescopeAxisView._on_item_changed`) - metody o tej samej nazwie w dwóch klasach to
    dwa klucze, nie jeden. Opakowana = wołanie `tekst_powodu`/`czytelny_powod`/`t`/`t_plural`. Nazwy
    z except = nazwy związane przez `except ... as <nazwa>` w najbliższej obejmującej funkcji."""
    import ast
    from pathlib import Path
    import horreum.gui as gui
    opakowania = {"tekst_powodu", "czytelny_powod", "t", "t_plural"}
    korzen = Path(gui.__file__).parent
    for plik in sorted(korzen.rglob("*.py")):
        drzewo = ast.parse(plik.read_text(encoding="utf-8"))
        rodzic = {d: n for n in ast.walk(drzewo) for d in ast.iter_child_nodes(n)}

        def _przodkowie(w):
            while w in rodzic:
                w = rodzic[w]
                if isinstance(w, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    yield w

        def _funkcja(w):
            return next((p for p in _przodkowie(w) if not isinstance(p, ast.ClassDef)), None)
        z_wyjatku = {}
        for h in ast.walk(drzewo):
            if isinstance(h, ast.ExceptHandler) and h.name:
                z_wyjatku.setdefault(_funkcja(h), set()).add(h.name)
        for w in ast.walk(drzewo):
            if not (isinstance(w, ast.Call) and isinstance(w.func, ast.Attribute)
                    and w.func.attr in ("t", "t_plural") and isinstance(w.func.value, ast.Name)
                    and w.func.value.id == "i18n"):
                continue
            nazwa = ".".join(reversed([p.name for p in _przodkowie(w)])) or None
            for k in w.keywords:
                v = k.value
                opakowana = isinstance(v, ast.Call) and (
                    v.func.attr if isinstance(v.func, ast.Attribute) else getattr(v.func, "id", None)) in opakowania
                yield (plik.relative_to(korzen).as_posix(), nazwa, k.arg, v, opakowana,
                       z_wyjatku.get(_funkcja(w), set()))


def test_zapadka_msg_err_e_w_zdaniach_GUI():
    """Rozszerzenie zapadki AR-167: parametr `msg=`/`err=`/`e=`/`exc=`/`error=` zdania GUI mówi przez
    `tekst_powodu`/`czytelny_powod` albo zdaniem katalogu - wyjątki z listy z kategorią. Nowe surowe
    miejsce = czerwień, naprawione musi zejść z listy. `exc`/`error` od AR-210: `grid.macro.error`
    brał `exc=exc` poza krotką. Falsyfikatory: `_on_dry_failed` okna żniw z `msg=msg` zamiast
    `tekst_powodu(msg)`, `grid._run` z `exc=exc` → nowy wpis spoza listy. Granica skanu: wyłącznie
    parametry wołań `i18n.t`/`t_plural` w `horreum/gui` z podkatalogami (`_wolania_zdan_gui`, wspólny
    z bliźniakiem po pochodzeniu wartości niżej); klucz = plik, `Klasa.metoda`, parametr, wartość."""
    import ast
    znalezione = {(plik, nazwa, arg, ast.unparse(v)) for plik, nazwa, arg, v, opakowana, _w in _wolania_zdan_gui()
                  if arg in ("msg", "err", "e", "exc", "error") and not opakowana}
    nowe, stare = znalezione - set(_ZNANE_SUROWE_MSG), set(_ZNANE_SUROWE_MSG) - znalezione
    assert not nowe, f"surowy tekst błędu w zdaniu GUI: {sorted(nowe)}"
    assert not stare, f"wyjątek już naprawiony - zdejmij z listy: {sorted(stare)}"


# ============================ AR-210: zapadka tekstu wyjątku po POCHODZENIU wartości

# Parametry z wartością z `except ... as <nazwa>`, które nie są tekstem wyjątku - jawnie, z kategorią.
_ZNANE_Z_WYJATKU = {
    ("app.py", "MainWindow._open_path", "found", "exc.found"): "numer wersji schematu z `db.SchemaTooNew` - liczba",
}


def test_zapadka_tekstu_wyjatku_po_pochodzeniu_w_zdaniach_GUI():
    """AR-210, bliźniak zapadek po NAZWIE parametru (`msg`/`err`/`e`/`exc`/`error` wyżej, `reason`/
    `reasons` - AR-167, `test_gui_powody_pisarza.py`): parametr DOWOLNEJ nazwy, którego wartość używa
    WPROST nazwy związanej przez `except ... as <nazwa>` tej funkcji (`e`, `str(e)`, `exc.found`), mówi
    przez `tekst_powodu`/`czytelny_powod` albo zdaniem katalogu - nazwa parametru spoza krotek nie chowa
    surowego tekstu wyjątku. Wyjątki: listy obu zapadek po nazwie (te same miejsca, kategoria tam; klucz
    zapadki AR-167 nie zna klasy - porównanie po samej metodzie) i `_ZNANE_Z_WYJATKU` (wartość nie jest
    tekstem); wpis własnej listy, którego już nie ma, schodzi z niej.

    Granice skanu (świadome): (1) wyłącznie parametry wołań `i18n.t`/`t_plural` - funkcje-zdania spoza
    katalogu (np. `_set_summary(error=…)` okna żniw) i ujścia bez katalogu (`QMessageBox.warning(...,
    str(e))`, `setText(str(e))` - kategoria `_ODMOWA_OSI`) są poza skanem; (2) wyłącznie bezpośrednie
    użycie nazwy z `except` - tekst przepisany najpierw do zmiennej pośredniej (`powod = str(e)`) jest
    poza skanem. Falsyfikator: `i18n.t(..., szczegol=str(exc))` w `except` → nowy wpis spoza list."""
    import ast
    from test_gui_powody_pisarza import _ZNANE_SUROWE
    znalezione = {(plik, nazwa, arg, ast.unparse(v)) for plik, nazwa, arg, v, opakowana, wyj in _wolania_zdan_gui()
                  if not opakowana and {n.id for n in ast.walk(v) if isinstance(n, ast.Name)} & wyj}
    znane_ar167 = set(_ZNANE_SUROWE)
    nowe = {z for z in znalezione - set(_ZNANE_SUROWE_MSG) - set(_ZNANE_Z_WYJATKU)
            if (z[0], (z[1] or "").rsplit(".", 1)[-1], z[2], z[3]) not in znane_ar167}
    stare = set(_ZNANE_Z_WYJATKU) - znalezione
    assert not nowe, f"surowy tekst wyjątku w zdaniu GUI: {sorted(nowe)}"
    assert not stare, f"wyjątek już naprawiony - zdejmij z listy: {sorted(stare)}"


# ============================================================ AR-209, AR-214: jedna reguła wyjątku okna

_EXPECT_RDZENIA = "złamany inwariant rdzenia: wersja stosu bez oryginału"


def _rzut(rodzaj, tmp_path):
    """Wyjątek reprezentatywny drogi okna: goły EXPECT rdzenia (proza PL), wyjątek biblioteki
    (`json.JSONDecodeError`), `KeyError`, błąd systemu klasą (zerwany udział) i PRAWDZIWY błąd
    SQLite z kodem (CANTOPEN - baza w katalogu, którego nie ma)."""
    import json
    import sqlite3
    if rodzaj == "rdzen":
        raise ValueError(_EXPECT_RDZENIA)
    if rodzaj == "biblioteka":
        json.loads("{")
    if rodzaj == "klucz":
        raise KeyError("lights")
    if rodzaj == "system":
        raise OSError(None, "Nazwa sieciowa jest już niedostępna", r"X:\L", 64)
    if rodzaj == "zamkniete":                      # API bazy wbrew kontraktowi - błąd programu
        c = sqlite3.connect(":memory:")
        c.close()
        c.execute("SELECT 1")
    sqlite3.connect(str(tmp_path / "brak" / "x.db"))
    raise AssertionError(rodzaj)


def _szczegol_programu(rodzaj, tmp_path):
    """Wiersz szczegółu technicznego błędu programu: `Typ: opis` TEGO SAMEGO wyjątku co `_rzut`."""
    try:
        _rzut(rodzaj, tmp_path)
    except Exception as exc:                       # noqa: BLE001 - test zbiera dowolny wyjątek rzutu
        return i18n.t("objchg.st.detail_tip", detail=f"{type(exc).__name__}: {exc}")
    raise AssertionError(rodzaj)


def _oczekiwane(rodzaj):
    """`(zdanie powodu w języku UI, wiersz szczegółu)`; błąd programu - szczegół `None` (osobny
    test niżej)."""
    if rodzaj == "system":
        return (i18n.t("objchg.item.os_share_lost", os_code="WinError 64"), i18n.t(
            "wb.os_detail_tip", detail=r"OSError: [WinError 64] Nazwa sieciowa jest już niedostępna: 'X:\L'"))
    if rodzaj == "baza":
        return (i18n.t("objchg.item.db_unavailable", db_code="SQLITE_CANTOPEN"),
                i18n.t("wb.os_detail_tip", detail="OperationalError: unable to open database file"))
    return i18n.t("objchg.item.prog_error"), None


def _okno_planera(tmp_path, monkeypatch, _ustawienia, rzut):
    """Planer: rachunek nocy pada w rdzeniu (`targets.plan`) - nagłówek nocy i jego szczegół."""
    from horreum import targets
    from horreum.gui.planner import PlannerView
    from test_gui_planner import _seed
    con = _seed(str(tmp_path / "planer.db"))
    v = PlannerView(con, db_path=None)
    monkeypatch.setattr(targets, "plan", lambda *_a, **_k: rzut())
    v.replan()
    wynik = v.night_label.text(), v.night_label.szczegol()
    v.close()
    con.close()
    return wynik, lambda zdanie: zdanie


def _okno_sondy(tmp_path, monkeypatch, ustawienia, rzut):
    """Okno wydania: sonda DRY pada w planiście (`projection.plan`) - raport i jego podpowiedź."""
    from horreum.gui import projection_dialog as pd_mod
    from test_gui_projection import _dlg, _seed_files, _target
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "sonda.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    monkeypatch.setattr(projection, "plan", lambda *_a, **_k: rzut())
    dlg = _dlg(con, ids)
    wynik = dlg.report.toPlainText(), dlg.report.toolTip()
    dlg.reject()
    con.close()
    return wynik, lambda zdanie: i18n.t("proj.dry_failed", msg=zdanie)


def _okno_wydania(tmp_path, monkeypatch, ustawienia, rzut):
    """Okno wydania: klik „Utwórz” po udanej sondzie, `apply` pada wyjątkiem całej operacji."""
    from horreum.gui import projection_dialog as pd_mod
    from test_gui_projection import _dlg, _seed_files, _target
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con = db.open_db(str(tmp_path / "wydanie.db"))
    ids = _seed_files(con, tmp_path, 1)
    _target(ustawienia, tmp_path / "_WBPP" / "feed")
    dlg = _dlg(con, ids)
    monkeypatch.setattr(projection, "apply", lambda *_a, **_k: rzut())
    dlg.show()
    _klik(dlg.btn_apply)
    wynik = dlg.report.toPlainText(), dlg.report.toolTip()
    dlg.reject()
    con.close()
    return wynik, lambda zdanie: i18n.t("proj.apply_error", msg=zdanie, made="")


def _okno_manifestu(tmp_path, monkeypatch, ustawienia, rzut):
    """Okno wydania obiektu (AR-213): „Zapisz manifest” po sondzie z ofertą, zapis
    (`repair_manifest` z zapisem w `ManifestWorker`) pada wyjątkiem - raport i jego podpowiedź."""
    from horreum.gui import projection_dialog as pd_mod
    from test_gui_projection import _obiekt_wydania, _okno_rc8
    monkeypatch.setattr(pd_mod, "volume_serial", lambda p: "V")
    con, _ids = _obiekt_wydania(tmp_path)
    card = tmp_path / "_WBPP" / "karta"
    dlg = _okno_rc8(con, ustawienia, card)
    dlg.combo_zestaw.setCurrentIndex(2)
    _klik(dlg.btn_apply)
    (card / "OBJECTS" / "NGC_6992" / projection.MANIFEST_NAME).unlink()
    prawdziwa = projection.repair_manifest
    monkeypatch.setattr(projection, "repair_manifest",
                        lambda *a, **k: rzut() if k.get("do_write") else prawdziwa(*a, **k))
    _klik(dlg.btn_dry)
    assert dlg.btn_apply.text() == i18n.t("proj.obj.btn_write_manifest")
    _klik(dlg.btn_apply)
    wynik = dlg.report.toPlainText(), dlg.report.toolTip()
    dlg.reject()
    con.close()
    return wynik, lambda zdanie: i18n.t("proj.obj.manifest_error", msg=zdanie)


def _okno_zmiany(tmp_path, monkeypatch, _ustawienia, rzut):
    """Okno „Uzgodnij pliki…”: plan pada (`policz_plan`) - pole błędu i jego szczegół."""
    from horreum.gui import object_change_dialog as ocd
    from test_gui_object_change import _lighty
    con = db.open_db(str(tmp_path / "zmiana.db"))
    _lighty(tmp_path / "ASTRO_", con, "NGC7635", 1, baza=3)
    monkeypatch.setattr(ocd, "policz_plan", lambda *_a, **_k: rzut())
    dlg = _okno_uzgodnij(con, monkeypatch)
    wynik = dlg.error.text(), dlg.error.szczegol()
    dlg.reject()
    con.close()
    return wynik, lambda zdanie: i18n.t("objchg.err.plan", msg=zdanie)


_OKNA_WORKEROW = {"planer": _okno_planera, "sonda": _okno_sondy, "wydanie": _okno_wydania,
                  "manifest": _okno_manifestu, "zmiana": _okno_zmiany}


@pytest.mark.parametrize("lang", ["pl", "en"])
@pytest.mark.parametrize("rodzaj", ["rdzen", "biblioteka", "klucz", "zamkniete", "system", "baza"])
@pytest.mark.parametrize("okno", list(_OKNA_WORKEROW))
def test_cztery_workery_jedna_regula_wyjatku_okna(qapp, tmp_path, ustawienia, monkeypatch, jezyk,
                                                  okno, rodzaj, lang):
    """AR-209, AR-214: wyjątek workera planera, sondy i biegu wydania oraz planu zmiany obiektu
    mówi JEDNĄ regułą (`item_reasons.powod_okna`): błąd systemu i bazy - klasą w języku UI ze
    szczegółem pod kursorem; goły EXPECT rdzenia, wyjątek biblioteki i `KeyError` - zdaniem błędu
    programu w języku UI (nic po polsku w EN), a nie prozą rdzenia albo `Typ: opis` w zdaniu.
    Falsyfikator: gałąź `ValueError` planera z `str(exc)`, sonda z `powod_wyjatku(exc)`, plan
    zmiany obiektu z `blad_systemu(exc)` - zdanie niesie surowy tekst wyjątku."""
    jezyk(lang)
    (zdanie, szczegol), glowa = _OKNA_WORKEROW[okno](tmp_path, monkeypatch, ustawienia,
                                                      lambda: _rzut(rodzaj, tmp_path))
    powod, wiersz = _oczekiwane(rodzaj)
    assert zdanie.startswith(glowa(powod)), zdanie
    if wiersz is not None:
        assert szczegol == wiersz, szczegol
    if lang == "en":
        assert not set(zdanie.split("\n")[0]) & _POLSKIE, zdanie


@pytest.mark.parametrize("lang", ["pl", "en"])
@pytest.mark.parametrize("rodzaj", ["rdzen", "zamkniete"])
@pytest.mark.parametrize("okno", list(_OKNA_WORKEROW))
def test_cztery_workery_blad_programu_szczegol_techniczny_z_typem(qapp, tmp_path, ustawienia,
                                                                   monkeypatch, jezyk, okno, rodzaj,
                                                                   lang):
    """Błąd programu w czterech oknach - goły EXPECT rdzenia i API bazy wbrew kontraktowi
    (`sqlite3.ProgrammingError` na zamkniętym połączeniu - nie stan bazy): proza z typem wyjątku stoi
    WYŁĄCZNIE w szczególe technicznym pod kursorem (`objchg.st.detail_tip`), zdanie okna mówi błąd
    programu w języku UI. Falsyfikator: `prog_error` bez wiersza szczegółu; `ProgrammingError`
    klasą przez `blad_systemu` - angielski tekst SQLite w zdaniu."""
    jezyk(lang)
    (zdanie, szczegol), glowa = _OKNA_WORKEROW[okno](tmp_path, monkeypatch, ustawienia,
                                                      lambda: _rzut(rodzaj, tmp_path))
    assert zdanie.startswith(glowa(i18n.t("objchg.item.prog_error"))), zdanie
    assert szczegol == _szczegol_programu(rodzaj, tmp_path), szczegol
