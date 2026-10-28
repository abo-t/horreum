"""AR-362: jedna czysta reguła klasy cofnięcia (`writeback.klasa_backupu` nad `writeback.FaktyBackupu`) - tabela klas na
faktach ręcznych, implikacje klasy dla realnego cofnięcia backupu (`zakonczony` → „już cofnięte” bez zapisu pliku,
`otwarty` → `undo_open_op` bez zapisu), konsumenci reguły w jednym przebiegu (straż nowszego zapisu, wiersz Porządków)
i jedna migawka wsadu z prawdziwym kandydatem łańcucha przebiegu. AR-383: werdykt obiektu z karty „bez dowodu” i
„zostaje” dla każdego źródła z NAZWY w nagłówku. Granica AR-421 (wpis rejestru): łańcuch MIĘDZY przebiegami wymaga
trwałego dowodu następstwa domknięć cofnięć, którego baza nie ma - testy `xfail(strict=True)` na prawdziwym rdzeniu.

Prawdziwy pisarz na syntetycznych FITS w `tmp_path`; atrapy wyłącznie awarii."""
from __future__ import annotations

import pytest

from horreum import db, repo, resolver, writeback
from horreum.gui import queries
from horreum.resolve.objects import HEADER_NAME_SOURCES

from test_cofniecie_bez_dowodu import _bez_dowodu
from test_undo_kotwica_drogi import _baza as _baza_kotwicy, _droga_b
from test_undo_obiekt_karty import _scena as _scena_karty
from test_writeback_cofniecie_przebiegu import (NOW, PRZYPADKI_KLAS, _BarieraOdczytu, _baza, _klatki, _makro,
                                                _nakladka, _scena_klas, _tel)


def _f(**pola):
    """Fakty ręczne backupu (domyślnie: podmiana atomowa potwierdzona, baza opisuje wynik, bez śladów)."""
    domyslne = dict(id=2, commit_id=2, location_id=1, niepodmieniony=False, niepotwierdzony=False,
                    opisuje_wynik=True, faza_zapisu=None, faza_cofniecia=None, slad_wciagniety=False,
                    wynik_wlasny=False)
    domyslne.update(pola)
    return writeback.FaktyBackupu(**domyslne)


_STARSZY_COFNIETY = _f(id=1, commit_id=1, faza_zapisu="synced", faza_cofniecia="synced")
_STARSZY_WYNIK_WLASNY = _f(id=1, commit_id=1, slad_wciagniety=True, wynik_wlasny=True)
_STARSZY_SAM_SLAD = _f(id=1, commit_id=1, slad_wciagniety=True)

_TABELA = {
    "atomowy_potwierdzony": (_f(), (), "zatwierdzony"),
    "atomowy_niepotwierdzony": (_f(niepotwierdzony=True), (), "niepewny"),
    "niepodmieniony": (_f(niepodmieniony=True), (), "zakonczony"),
    "w_miejscu_zatwierdzony": (_f(faza_zapisu="synced"), (), "zatwierdzony"),
    "w_miejscu_cofniety": (_f(faza_zapisu="synced", faza_cofniecia="synced"), (), "zakonczony"),
    "wynik_wlasny": (_f(slad_wciagniety=True, wynik_wlasny=True), (), "zakonczony"),
    "slad_bez_pary_bez_starszego": (_f(slad_wciagniety=True), (), "zatwierdzony"),
    "zapis_otwarty": (_f(faza_zapisu="unverified"), (), "otwarty"),
    "przed_bajtem": (_f(faza_zapisu="writing"), (), "otwarty"),
    "cofniecie_otwarte": (_f(faza_zapisu="synced", faza_cofniecia="unverified"), (), "otwarty"),
    "dowod_przed_otwartym": (_f(faza_zapisu="unverified", faza_cofniecia="synced"), (), "zakonczony"),
    "odzyskany": (_f(faza_zapisu="recovered"), (), "poza"),
    "zwolniony": (_f(faza_zapisu="released"), (), "niepewny"),
    "lancuch_przez_cofniety_w_miejscu": (_f(slad_wciagniety=True), (_STARSZY_COFNIETY,), "zakonczony"),
    "lancuch_przez_wynik_wlasny": (_f(slad_wciagniety=True), (_STARSZY_WYNIK_WLASNY,), "zakonczony"),
    "lancuch_bez_wlasnego_sladu": (_f(), (_STARSZY_COFNIETY,), "zatwierdzony"),
    "lancuch_starszy_bez_dowodu": (_f(slad_wciagniety=True), (_STARSZY_SAM_SLAD,), "zatwierdzony"),
    "lancuch_przed_otwartym": (_f(faza_zapisu="unverified", slad_wciagniety=True), (_STARSZY_COFNIETY,),
                               "zakonczony"),
}


@pytest.mark.parametrize("fakty, starsze, oczek", list(_TABELA.values()), ids=list(_TABELA))
def test_klasa_backupu_tabela(fakty, starsze, oczek):
    """Czysta reguła na faktach ręcznych - każda klasa i łańcuch przebiegu: własne cofnięcie atomowe domknięte ORAZ
    starszy z dowodem WPROST (bez rekurencji - starszy z samym śladem nie domyka). Falsyfikatory: łańcuch bez
    własnego śladu; łańcuch po samym śladzie starszego; faza otwarta przed dowodem; `released` jak potwierdzony."""
    assert writeback.klasa_backupu(fakty, starsze) == oczek


def test_starsze_czytane_wylacznie_przy_kandydacie_lancucha():
    """Zasilacz pojedynczy czyta starsze backupy przebiegu leniwie: reguła sięga po nie tylko przy własnym śladzie
    wciągniętym bez dowodu wprost. Falsyfikator: `starsze` konsumowane zawsze (odczyt na każdy backup)."""
    def _nie_czytaj():
        raise AssertionError("starsze czytane bez kandydata łańcucha")
        yield  # pragma: no cover

    for fakty in (_f(), _f(niepodmieniony=True), _f(slad_wciagniety=True, wynik_wlasny=True), _f(faza_zapisu="writing")):
        writeback.klasa_backupu(fakty, _nie_czytaj())


def _bajty(tmp_path):
    return [(p.name, p.read_bytes()) for p in sorted(tmp_path.rglob("*.fits"))]


@pytest.mark.parametrize("przypadek", PRZYPADKI_KLAS)
def test_klasa_przewiduje_wynik_cofniecia_bez_zapisu(tmp_path, monkeypatch, przypadek):
    """Implikacje klasy dla realnego cofnięcia (pętla `_cofnij_backupy`, jeden backup): `zakonczony` ⇒ „już cofnięte”
    (`blocked` w `already`), `otwarty` ⇒ `failed` z kodem `undo_open_op`, w obu bez zmiany bajtu żadnego pliku; plik
    po odzysku (`poza`) bez powrotu wyniku ⇒ `undo_already_region`. Każdy backup tych klas każdego przypadku, klasa
    liczona od nowa przed każdym (rozliczenie „już cofnięte” pisze do bazy). Pozostałe klasy nie przewidują wyniku -
    rozstrzyga cofnięcie. Falsyfikator: wykonawca z własną interpretacją faz (otwarta operacja jako zamknięta)."""
    con = _scena_klas(tmp_path, monkeypatch, przypadek)
    sprawdzone = []
    try:
        while True:
            klasy = [(c, lo, k) for c, lo, k in writeback._klasy_przebiegu(con, "R")
                     if k in ("zakonczony", "otwarty", "poza") and (c, lo) not in sprawdzone]
            if not klasy:
                break
            cid, lid, k = klasy[0]
            sprawdzone.append((cid, lid))
            [b] = [b for b in writeback.backups_for_commit(con, cid) if int(b["location_id"]) == lid]
            przed = _bajty(tmp_path)
            u = writeback._cofnij_backupy(con, "R", [(cid, b)], now=NOW, progress=None, should_cancel=None)
            [fr] = u.restored + u.blocked + u.failed
            kod = getattr(fr.reason, "code", None)
            assert _bajty(tmp_path) == przed, (przypadek, cid, lid, k, fr.status, kod)
            if k == "zakonczony":
                assert fr.status == "blocked" and u.already == [fr], (przypadek, cid, lid, fr.status, kod)
            elif k == "otwarty":
                assert fr.status == "failed" and kod == "undo_open_op", (przypadek, cid, lid, fr.status, kod)
            else:
                assert przypadek == "jeden-odzyskany" and kod == "undo_already_region", (przypadek, kod)
    finally:
        con.close()


def test_straz_nowszego_i_porzadki_czytaja_lancuch_przebiegu(tmp_path):
    """Jeden przebieg, ta sama lokacja dwa razy (A → B → A, obie drogi atomowe), cofnięcie przebiegu: nowszy backup
    jest „już cofnięty” łańcuchem (wsad: zakres None), więc straż nowszego żywego zapisu starszego backupu go nie
    widzi, predykat zakończenia go uznaje, a wiersz Porządków „Dokończ cofnięcie” nie powstaje - ta sama reguła co
    wsad. Ponowne cofnięcie przebiegu nie zmienia pliku. Falsyfikator: straż i Porządki z samym dowodem wprost
    (dawne lustro: wiersz „Dokończ cofnięcie (commit 2)” obok szuflady, która mówi „nie ma czego cofać”)."""
    con, (p,) = _baza(tmp_path, 1)
    _makro(con, "R", "EQ6")
    writeback.commit(con, "R", now=NOW, inplace=False)
    _makro(con, "R", "RC8")
    writeback.commit(con, "R", now=NOW, inplace=False)
    try:
        assert writeback.undo_run(con, (1, 2), now=NOW).complete and _tel(p) == "RC8"
        [b1], [b2] = writeback.backups_for_commit(con, 1), writeback.backups_for_commit(con, 2)
        assert writeback.przebieg_do_cofniecia(con, "R") is None
        assert writeback._cofniecie_zakonczone(con, 2, b2)
        assert writeback._nowszy_zywy_zapis(con, b1) is None
        assert queries.niedokonczone_cofniecia_kart(con) == []
        po = p.read_bytes()
        assert writeback.undo_run(con, (1, 2), now=NOW).complete and p.read_bytes() == po
    finally:
        con.close()


def test_przerwane_ponowienie_po_lancuchu_nie_liczy_reszty(tmp_path):
    """Nakładka `aa` cofnięta w całości, ponowienie przerwane przed pierwszym backupem: reszta (`remaining`) liczy
    backupy BEZ dowodu zakończenia regułą klasy - nowszy backup L0 „już cofnięty” łańcuchem przebiegu to nie reszta,
    więc 0 i 0 nietkniętych. Falsyfikator: klasa nieprzetworzonego z samego dowodu wprost (reszta 1)."""
    con, _p = _nakladka(tmp_path, "aa")
    try:
        assert writeback.undo_run(con, (1, 2), now=NOW).complete
        u = writeback.undo_run(con, (1, 2), now=NOW, should_cancel=lambda: True)
        assert u.cancelled and u.remaining == 0 and u.untouched == 0, (u.remaining, u.untouched)
    finally:
        con.close()


def test_klasy_wsadowe_z_lancuchem_czytaja_jedna_migawke(tmp_path):
    """Kandydat łańcucha przebiegu w migawce: nakładka `aa` cofnięta w całości (nowszy backup L0 - „już cofnięty”
    łańcuchem przez wynik własny starszego). Drugie połączenie zapisuje L0 innym przebiegiem MIĘDZY odczytem operacji
    a odczytem śladów (bariera przed trzecim SELECT-em): klasy z migawki sprzed - trzy `zakonczony` - a po zapisie
    para śladu starszego pęka i łańcuch nowszego razem z nią. Falsyfikator: odczyt śladów poza transakcją odczytu
    (łańcuch rozstrzygnięty stanem po zapisie innego połączenia)."""
    con, pliki = _nakladka(tmp_path, "aa")
    f0 = _klatki(con)[0]
    assert writeback.undo_run(con, (1, 2), now=NOW).complete
    assert [k for *_x, k in writeback._klasy_przebiegu(con, "R")] == ["zakonczony"] * 3
    con2 = db.connect(str(tmp_path / "n.db"))

    def _zapis_innego_przebiegu():
        _makro(con2, "S", "EQ8", [f0])
        assert writeback.commit(con2, "S", now=NOW, inplace=False).applied
    try:
        bariera = _BarieraOdczytu(con, 3, _zapis_innego_przebiegu)
        assert [k for *_x, k in writeback._klasy_przebiegu(bariera, "R")] == ["zakonczony"] * 3
        assert not con.in_transaction and _tel(pliki[0]) == "EQ8"
        assert [k for *_x, k in writeback._klasy_przebiegu(con, "R")] == ["zatwierdzony", "zakonczony",
                                                                           "zatwierdzony"]
    finally:
        con2.close()
        con.close()


# ============================================================ granica: łańcuch między przebiegami (AR-421)

_GRANICA = ("AR-421: łańcuch między przebiegami wymaga trwałego dowodu następstwa domknięć cofnięć obu dróg "
            "(rodowód stanu lokacji - migracja, wpis rejestru); dziś klasa widzi łańcuch wyłącznie w przebiegu")


@pytest.mark.xfail(strict=True, reason=_GRANICA)
@pytest.mark.parametrize("drogi", ["aa", "ma"])
def test_aba_miedzy_przebiegami_ponowne_cofniecie_nie_przywraca_cofnietego_zapisu(tmp_path, drogi):
    """A → B → A między przebiegami (R1: RC8 → EQ6, R2: EQ6 → RC8 atomowo), cofnięcie C2, potem C1 - plik wraca do
    RC8. Ponowne cofnięcie C2 (szuflada po restarcie, CLI `header-fix --undo 2`) nie może przywrócić EQ6 - wyniku C1,
    który człowiek cofnął. Dziś przywraca (klasa C2 `zatwierdzony`, odcisk lokacji = `post_hash` C2)."""
    con, (p,) = _baza(tmp_path, 1)
    try:
        _makro(con, "R1", "EQ6")
        c1 = writeback.commit(con, "R1", now=NOW, inplace=drogi[0] == "m").commit_id
        _makro(con, "R2", "RC8")
        c2 = writeback.commit(con, "R2", now=NOW, inplace=False).commit_id
        assert writeback.undo(con, c2, now=NOW).complete and writeback.undo(con, c1, now=NOW).complete
        assert _tel(p) == "RC8"
        writeback.undo_run(con, (c2,), now=NOW)
        assert _tel(p) == "RC8"
    finally:
        con.close()


@pytest.mark.xfail(strict=True, reason=_GRANICA)
def test_dwa_przebiegi_cofniete_po_kolei_nie_zostawiaja_cofnij(tmp_path):
    """Dwa przebiegi atomowo na jednym pliku (R1: RC8 → EQ6, R2: EQ6 → EQ8), cofnięcie C2, potem C1 - plik sprzed
    obu. Zakres „Cofnij” R2 ma być pusty (szuflada po restarcie nie stawia „Cofnij” zapisu już cofniętego). Dziś
    R2 zostaje `zatwierdzony`, a klik odmawia `undo_header_changed`."""
    con, (p,) = _baza(tmp_path, 1)
    try:
        _makro(con, "R1", "EQ6")
        c1 = writeback.commit(con, "R1", now=NOW, inplace=False).commit_id
        _makro(con, "R2", "EQ8")
        c2 = writeback.commit(con, "R2", now=NOW, inplace=False).commit_id
        assert writeback.undo(con, c2, now=NOW).complete and writeback.undo(con, c1, now=NOW).complete
        assert _tel(p) == "RC8"
        assert writeback.przebieg_do_cofniecia(con, "R2") is None
    finally:
        con.close()


# ============================================================ AR-383: źródła obiektu z nazwy w nagłówku

# Wyliczone wprost (nie z samej stałej): wyrocznia niezależna od kodu - źródło wyjęte ze stałej zostaje w teście.
_Z_NAZWY = ["alias", "catalog_xref", "comet", "common_name", "curated", "solar"]


def test_zrodla_z_nazwy_naglowka_to_podzbior_osi():
    """Stała źródeł z nazwy w nagłówku = `header` + sześć szczebli nazwy, żyje w enumie osi i nie niesie źródeł ręki,
    geometrii, ścieżki ani bliźniaka."""
    assert HEADER_NAME_SOURCES == {"header", *_Z_NAZWY}
    assert HEADER_NAME_SOURCES <= repo.OBJECT_SOURCES
    assert not HEADER_NAME_SOURCES & {"user", "user_cleared", "review", "twin", "region", "path"}


@pytest.mark.parametrize("zrodlo", _Z_NAZWY + ["twin"])
def test_bez_dowodu_dla_kazdego_zrodla_z_nazwy_naglowka(tmp_path, zrodlo):
    """Dopisanie karty `OBJECT` bez dowodu pochodzenia, „Rozwiąż”, klatka przy obiekcie ze źródłem z nazwy w nagłówku
    (katalog, nazwa zwyczajowa, gramatyka kuratorska, Układ Słoneczny, kometa, alias): cofnięcie liczy ją jako
    „bez dowodu”, jak źródło `header`; bliźniak (`twin`) - nie dotyczy. Falsyfikator: werdykt tylko dla `header`."""
    s = _scena_karty(tmp_path, inplace=False)
    try:
        _bez_dowodu(s.con)
        resolver.run_resolver(s.con, NOW)
        oid = s.con.execute("SELECT object_id FROM frame WHERE id = ?", (s.fid,)).fetchone()[0]
        assert repo.assign_object(s.con, frame_id=s.fid, object_id=oid, object_source=zrodlo, now=NOW)
        u = writeback.undo(s.con, s.commit, now=NOW)
        assert u.complete and u.objects_unproven == (() if zrodlo == "twin" else (s.fid,)), u
    finally:
        s.con.close()


@pytest.mark.parametrize("zrodlo", _Z_NAZWY + ["twin"])
def test_zostaje_dla_kazdego_zrodla_z_nazwy_naglowka(tmp_path, monkeypatch, zrodlo):
    """„Rozwiąż” przed późnym rozliczeniem zapisu (przypisanie z karty wyprzedziło kotwicę - brak zdarzenia osi po niej),
    klatka przy obiekcie ze źródłem z nazwy w nagłówku: cofnięcie liczy ją jako „zostaje”, jak źródło `header`;
    bliźniak - nie dotyczy. Źródło klatki ustawione wprost w bazie testu (bez zdarzenia osi - inaczej kotwica miałaby
    zdarzenie po sobie). Falsyfikator: druga gałąź werdyktu tylko dla `header`."""
    con, p, loc = _baza_kotwicy(tmp_path)
    try:
        cid = _droga_b(con, p, loc, monkeypatch, rozwiaz_przed=True)
        with con:
            con.execute("UPDATE frame SET object_source = ? WHERE id = ?", (zrodlo, loc["frame_id"]))
        u = writeback.undo(con, cid, now=NOW)
        assert u.complete and u.objects_kept == (() if zrodlo == "twin" else (loc["frame_id"],)), u
    finally:
        con.close()
