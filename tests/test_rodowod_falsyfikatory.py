"""AR-421 (fala 31, krok 0): sceny-falsyfikatory reguły klasy cofnięcia z rodowodem stanu lokacji - łańcuch cofnięć
MIĘDZY przebiegami i powrót wyniku z zewnątrz. Sceny z sondy fali 30 (`fala30\\D2\\sonda_z1.py`: H1, H2, S2, S5, P2,
R11) i z recenzji planu fali 31 (`sol` Z1, `astra` A1) oraz scena kroku 0 (K2 - objazd z zewnątrz PRZED powrotem
wyniku) - nazwy i przewidywania: `brief/FALA31_plan.md` §2.3.

Trzy rodzaje testów:
  * warunki wstępne sceny - BEZ xfail: regresja samej sceny (gest nie przeszedł, plik w innym stanie) nie może zostać
    połknięta jako XFAIL testu celu;
  * cel sceny, którego dziś nie ma - `xfail(strict=True)` z ID `AR-421` (tor B fali 31 zdejmuje): macierz konsumentów
    reguły dla H1 i S2 (zakres szuflady, szuflada po restarcie, CLI `header-fix --undo` = `undo_run`, wiersz Porządków,
    straż nowszego zapisu, klasa nieprzetworzonego, recepta osi), cele P2, R11, H2mr, Z1, K2;
  * zachowanie HEAD, które fala ma utrzymać - zielone piny: H2m, H2a, S5 (wynik wrócił z zewnątrz - „Cofnij” działa),
    S2 `am`/`mm` (dowód wprost cofnięcia w miejscu), A1 bajtowo (łańcuch przebiegu po ponownym cofnięciu), oraz dwa
    konsumenty S2, które dziś mówią prawdę (Porządki, straż nowszego zapisu).

TELESCOP: RC8 = A (stan wyjściowy), EQ6 = B, EQ8 = C, ED120 = D. Prawdziwy pisarz na syntetycznych FITS w `tmp_path`,
bez atrap."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from astropy.io import fits

from horreum import db, scan, writeback
from horreum.gui import queries

from test_writeback_cofniecie_przebiegu import NOW, _baza, _makro, _tel

_REGULA = ("AR-421: klasa cofnięcia widzi łańcuch wyłącznie w przebiegu - łańcuch MIĘDZY przebiegami i powrót wyniku "
           "z zewnątrz rozstrzyga dopiero reguła z rodowodem stanu lokacji (`location_state`, fala 31 tor B)")
_N1 = ("AR-421 (zmiana świadoma N1, `brief/FALA31_plan.md` §2.3): wynik zapisu przywrócony z zewnątrz w JEDNYM przebiegu "
       "daje znów „Cofnij”, jak między przebiegami - dziś łańcuch przebiegu mówi „już cofnięte”")


def _skan(con, p):
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())


def _zapis(con, run_id, wartosc, *, inplace=False):
    _makro(con, run_id, wartosc)
    c = writeback.commit(con, run_id, now=NOW, inplace=inplace)
    assert c.applied, (run_id, wartosc)
    return c.commit_id


def _cofnij(con, commit_id, p, oczek):
    assert writeback.undo(con, commit_id, now=NOW).complete, commit_id
    assert _tel(p) == oczek, (commit_id, _tel(p), oczek)


def _z_zewnatrz(con, p, *, bajty=None, tel=None):
    """Zmiana pliku spoza Horreum (bajty z kopii albo nowa wartość TELESCOP) i skan, który ją wciąga."""
    if bajty is not None:
        p.write_bytes(bajty)
    else:
        fits.setval(str(p), "TELESCOP", value=tel)
    _skan(con, p)


def _scena(tmp_path, kod):
    """Baza i pliki sceny `kod` (asercje każdego gestu wewnątrz) - `SimpleNamespace(con, pliki, c1, c2, sciezka)`.

      * `H1x` - łańcuch między przebiegami: C1 A → B (R1, `x`: `m` w miejscu, `a` atomowo), C2 B → A (R2 atomowo),
        cofnięcie C2, potem C1;
      * `S2xy` - dwa przebiegi bez ABA: C1 A → B (`x`), C2 B → C (`y`), cofnięcie C2, potem C1;
      * `P2` - dwa pliki, A → B → A atomowo, cofnięcie R2 przerwane po pierwszym pliku, potem cofnięcie R1 (drugi plik
        odmawia `undo_newer_write`);
      * `R11` - `H1a`, potem C3 A → C (R3) i jego cofnięcie;
      * `H2x` - powrót z zewnątrz: C1 A → B (`x`) cofnięty, człowiek przywraca bajty B; C2 B → A (R2 atomowo) cofnięty,
        człowiek przywraca bajty A z wyniku C2; `H2mr` - to samo, C2 w TYM SAMYM przebiegu R1;
      * `S5` - C1 A → B w miejscu cofnięty, C2 A → C atomowo cofnięty, człowiek przywraca wynik C2;
      * `Z1` (`sol`) - C1 A → B, C2 B → A, cofnięcie C2, zmiana z zewnątrz B → C → B (dwa skany), cofnięcie C1;
      * `K2` (krok 0) - C1 A → B, C2 B → A, C3 A → C (trzy przebiegi), cofnięcie C3, C2, C1, z zewnątrz D, potem bajty
        wyniku C3, ponowne cofnięcie C3;
      * `A1` (`astra`, bajtowo) - jeden przebieg: C1 A → B, C2 B → A, C3 A → C, cofnięcie przebiegu, bajty wyniku C3
        z zewnątrz, ponowne cofnięcie C3."""
    n = 2 if kod == "P2" else 1
    con, pliki = _baza(tmp_path, n, "s")
    p = pliki[0]
    sc = SimpleNamespace(con=con, pliki=pliki, sciezka=str(tmp_path / "s.db"))
    if kod.startswith("S2"):
        sc.c1 = _zapis(con, "R1", "EQ6", inplace=kod[2] == "m")
        sc.c2 = _zapis(con, "R2", "EQ8", inplace=kod[3] == "m")
        _cofnij(con, sc.c2, p, "EQ6")
        _cofnij(con, sc.c1, p, "RC8")
    elif kod == "P2":
        sc.c1 = _zapis(con, "R1", "EQ6")
        sc.c2 = _zapis(con, "R2", "RC8")
        licz = []
        u = writeback.undo_run(con, (sc.c2,), now=NOW, should_cancel=lambda: licz.append(1) or len(licz) > 1)
        assert u.cancelled and [_tel(x) for x in pliki] == ["EQ6", "RC8"], [_tel(x) for x in pliki]
        u = writeback.undo_run(con, (sc.c1,), now=NOW)
        assert [_tel(x) for x in pliki] == ["RC8", "RC8"], [_tel(x) for x in pliki]
        assert [getattr(fr.reason, "code", None) for fr in u.blocked] == ["undo_newer_write"], u.blocked
    elif kod == "S5":
        sc.c1 = _zapis(con, "R1", "EQ6", inplace=True)
        _cofnij(con, sc.c1, p, "RC8")
        sc.c2 = _zapis(con, "R2", "EQ8")
        po_c2 = p.read_bytes()
        _cofnij(con, sc.c2, p, "RC8")
        _z_zewnatrz(con, p, bajty=po_c2)
    elif kod in ("Z1", "K2", "A1"):
        sc.c1 = _zapis(con, "R1" if kod != "A1" else "R", "EQ6")
        sc.c2 = _zapis(con, "R2" if kod != "A1" else "R", "RC8")
        if kod == "Z1":
            _cofnij(con, sc.c2, p, "EQ6")
            po_cofnieciu = p.read_bytes()
            _z_zewnatrz(con, p, tel="EQ8")
            _z_zewnatrz(con, p, bajty=po_cofnieciu)
            assert _tel(p) == "EQ6"
            _cofnij(con, sc.c1, p, "RC8")
        else:
            sc.c3 = _zapis(con, "R3" if kod == "K2" else "R", "EQ8")
            po_c3 = p.read_bytes()
            if kod == "K2":
                for c, oczek in ((sc.c3, "RC8"), (sc.c2, "EQ6"), (sc.c1, "RC8")):
                    _cofnij(con, c, p, oczek)
                _z_zewnatrz(con, p, tel="ED120")
            else:
                assert writeback.undo_run(con, (sc.c1, sc.c2, sc.c3), now=NOW).complete and _tel(p) == "RC8"
            _z_zewnatrz(con, p, bajty=po_c3)
            assert _tel(p) == "EQ8"
            _cofnij(con, sc.c3, p, "RC8")
    else:                                               # H1x, R11, H2x, H2mr
        sc.c1 = _zapis(con, "R1", "EQ6", inplace=kod[2] == "m")
        po_c1 = p.read_bytes()
        if kod.startswith("H2"):
            _cofnij(con, sc.c1, p, "RC8")
            _z_zewnatrz(con, p, bajty=po_c1)
        sc.c2 = _zapis(con, "R1" if kod == "H2mr" else "R2", "RC8")
        po_c2 = p.read_bytes()
        _cofnij(con, sc.c2, p, "EQ6")
        if kod.startswith("H2"):
            _z_zewnatrz(con, p, bajty=po_c2)
        else:
            _cofnij(con, sc.c1, p, "RC8")
        if kod == "R11":
            sc.c3 = _zapis(con, "R3", "EQ8")
            _cofnij(con, sc.c3, p, "RC8")
    return sc


# Stan TELESCOP plików po scenie - warunek wstępny każdego testu celu.
_PO_SCENIE = {"H1m": ["RC8"], "H1a": ["RC8"], "S2aa": ["RC8"], "S2ma": ["RC8"], "S2am": ["RC8"], "S2mm": ["RC8"],
              "P2": ["RC8", "RC8"], "R11": ["RC8"], "H2m": ["RC8"], "H2a": ["RC8"], "H2mr": ["RC8"], "S5": ["EQ8"],
              "Z1": ["RC8"], "K2": ["RC8"], "A1": ["RC8"]}


@pytest.mark.parametrize("kod", list(_PO_SCENIE))
def test_warunki_wstepne_sceny(tmp_path, kod):
    """Każdy gest sceny przechodzi na prawdziwym pisarzu i zostawia pliki w stanie, który zakłada test celu - bez
    xfail (regresja sceny nie chowa się w XFAIL celu)."""
    sc = _scena(tmp_path, kod)
    try:
        assert [_tel(p) for p in sc.pliki] == _PO_SCENIE[kod]
    finally:
        sc.con.close()


# ============================================================ macierz konsumentów reguły: H1 i S2


def _cofniecie_cli_nie_zmienia_pliku(sc):
    """CLI `header-fix --undo C2` (`cli.py` → `undo_run`) = klik szuflady: „już cofnięte”, plik bez zmiany bajtu."""
    przed = [p.read_bytes() for p in sc.pliki]
    u = writeback.undo_run(sc.con, (sc.c2,), now=NOW)
    return u.complete and not u.restored and bool(u.already) and [p.read_bytes() for p in sc.pliki] == przed


def _szuflada_po_restarcie(sc):
    """Szuflada po restarcie programu (nowe połączenie) nie stawia „Cofnij” zapisu już cofniętego."""
    sc.con.close()
    sc.con = db.connect(sc.sciezka)
    return queries.ostatni_zapis_szuflady(sc.con) is None


def _recepta_osi_martwa(sc):
    """`ObjectAxisView._zywy` (bez okna): recepta „Cofnij zapis (commit C2)” osi nie żyje."""
    pytest.importorskip("PySide6")
    from horreum.gui import app
    wpis = SimpleNamespace(klucz=("karty", sc.c2), tozsamosc=queries.przebieg_commitu(sc.con, sc.c2))
    return not app.ObjectAxisView._zywy(SimpleNamespace(con=sc.con), wpis)


def _zakres_pusty(sc):
    """Zakres „Cofnij” przebiegu C2 (szuflada, okna kart) nie ma czego cofać."""
    return writeback.przebieg_do_cofniecia(sc.con, queries.przebieg_commitu(sc.con, sc.c2)) is None


def _klasa_nieprzetworzonego(sc):
    [b2] = writeback.backups_for_commit(sc.con, sc.c2)
    return writeback._stan_nieprzetworzonego(sc.con, sc.c2, b2, writeback._granica_sladu(sc.con)) == "zakonczony"


def _straz_nowszego(sc):
    [b1] = writeback.backups_for_commit(sc.con, sc.c1)
    return writeback._nowszy_zywy_zapis(sc.con, b1) is None


KONSUMENCI = {
    "zakres_szuflady": _zakres_pusty,
    "szuflada_po_restarcie": _szuflada_po_restarcie,
    "cli_undo_run": _cofniecie_cli_nie_zmienia_pliku,
    "porzadki": lambda sc: queries.niedokonczone_cofniecia_kart(sc.con) == [],
    "straz_nowszego": _straz_nowszego,
    "nieprzetworzony": _klasa_nieprzetworzonego,
    "recepta_osi": _recepta_osi_martwa,
}
# Konsumenci, którzy na scenie S2 (dwa przebiegi bez ABA) mówią prawdę już dziś: lokacja nie opisuje wyniku C2, więc
# Porządki i straż nowszego zapisu go nie widzą (sonda fali 30) - piny, nie falsyfikatory.
_S2_DZIS = ("porzadki", "straz_nowszego")
_MACIERZ_XFAIL = ([(k, n) for k in ("H1m", "H1a") for n in KONSUMENCI]
                  + [(k, n) for k in ("S2aa", "S2ma") for n in KONSUMENCI if n not in _S2_DZIS])


@pytest.mark.xfail(strict=True, reason=_REGULA)
@pytest.mark.parametrize("kod, konsument", _MACIERZ_XFAIL)
def test_konsument_widzi_cofniecie_miedzy_przebiegami(tmp_path, kod, konsument):
    """H1 (A → B → A) i S2 (A → B → C) między przebiegami, cofnięcie C2, potem C1 - zapis C2 jest „już cofnięty” dla
    KAŻDEGO konsumenta reguły klasy. Dziś klasa C2 `zatwierdzony`: zakres i szuflada po restarcie stawiają „Cofnij”,
    CLI przy H1 przywraca EQ6 (wynik C1, który człowiek cofnął), przy S2 odmawia `undo_header_changed`."""
    sc = _scena(tmp_path, kod)
    try:
        assert KONSUMENCI[konsument](sc)
    finally:
        sc.con.close()


@pytest.mark.parametrize("kod", ["S2aa", "S2ma"])
@pytest.mark.parametrize("konsument", _S2_DZIS)
def test_konsument_s2_mowi_prawde_dzis(tmp_path, kod, konsument):
    """Pin HEAD: S2 bez ABA - Porządki i straż nowszego zapisu nie widzą C2 (odcisk lokacji ≠ wynik C2)."""
    sc = _scena(tmp_path, kod)
    try:
        assert KONSUMENCI[konsument](sc)
    finally:
        sc.con.close()


@pytest.mark.parametrize("kod", ["S2am", "S2mm"])
def test_cofniecie_w_miejscu_jest_dowodem_wprost(tmp_path, kod):
    """Pin HEAD: C2 cofnięty w miejscu (`undo` w `synced` - dowód zakończenia) - każdy konsument już dziś mówi „już
    cofnięte” (asymetria dróg zostaje: faza operacji w miejscu = dowód wprost)."""
    for konsument in KONSUMENCI:
        (tmp_path / konsument).mkdir()
        sc = _scena(tmp_path / konsument, kod)
        try:
            assert KONSUMENCI[konsument](sc), konsument
        finally:
            sc.con.close()


# ============================================================ cele pozostałych scen


@pytest.mark.xfail(strict=True, reason=_REGULA)
def test_p2_cofniecie_czesciowe_rozstrzyga_per_lokacja(tmp_path):
    """P2: cofnięcie R2 przerwane po pierwszym pliku, potem R1 (pierwszy plik wraca do RC8, drugi odmawia). Ponowne
    cofnięcie C2: pierwszy plik „już cofnięty” (łańcuch C2 → C1 na tej lokacji), drugi wraca do EQ6; Porządki czekają
    na JEDEN plik. Dziś klik przywraca oba pliki (pierwszy do EQ6 - wynik cofniętego C1)."""
    sc = _scena(tmp_path, "P2")
    try:
        assert queries.niedokonczone_cofniecia_kart(sc.con) == [(sc.c2, 1)]
        writeback.undo_run(sc.con, (sc.c2,), now=NOW)
        assert [_tel(p) for p in sc.pliki] == ["RC8", "EQ6"]
    finally:
        sc.con.close()


@pytest.mark.parametrize("kod", ["R11", "Z1", "K2"])
@pytest.mark.xfail(strict=True, reason=_REGULA)
def test_cofniety_zapis_nie_wraca_po_dalszych_zmianach(tmp_path, kod):
    """C2 cofnięty, a potem plik zmieniali: R11 - cofnięcie C1 i zapis C3 cofnięty; Z1 (`sol`) - zmiana z zewnątrz
    B → C → B i cofnięcie C1; K2 - cofnięcie C3 i C1, z zewnątrz D, potem bajty wyniku C3 i ponowne cofnięcie C3.
    Plik ma odcisk wyniku C2, ale postawiło go cofnięcie innego zapisu: zakres R2 pusty, szuflada po restarcie bez
    „Cofnij”, CLI „już cofnięte” bez zmiany bajtu. Dziś klasa C2 `zatwierdzony` i klik przywraca EQ6 (wynik C1)."""
    sc = _scena(tmp_path, kod)
    try:
        assert writeback.przebieg_do_cofniecia(sc.con, "R2") is None
        assert _cofniecie_cli_nie_zmienia_pliku(sc)
        assert _szuflada_po_restarcie(sc)
    finally:
        sc.con.close()


@pytest.mark.xfail(strict=True, reason=_N1)
def test_h2mr_wynik_przywrocony_w_przebiegu_daje_cofnij(tmp_path):
    """H2mr: C1 cofnięty, bajty B wróciły z zewnątrz, C2 (TEN SAM przebieg) cofnięty, bajty A z wyniku C2 wróciły
    z zewnątrz - wynik C2 przyniosła treść spoza Horreum, więc „Cofnij” C2 przywraca EQ6, jak w H2m między
    przebiegami (zmiana N1). Dziś łańcuch przebiegu mówi „już cofnięte”."""
    sc = _scena(tmp_path, "H2mr")
    try:
        u = writeback.undo_run(sc.con, (sc.c2,), now=NOW)
        assert u.restored and _tel(sc.pliki[0]) == "EQ6", (u.restored, u.already)
    finally:
        sc.con.close()


# ============================================================ piny HEAD, które fala utrzymuje


@pytest.mark.parametrize("kod, oczek", [("H2m", "EQ6"), ("H2a", "EQ6"), ("S5", "RC8")])
def test_wynik_wrocil_z_zewnatrz_cofnij_dziala(tmp_path, kod, oczek):
    """Pin HEAD: wynik C2 wrócił z zewnątrz po jego cofnięciu (H2 między przebiegami, S5) - zakres R2 ma co cofnąć,
    a klik przywraca stan sprzed C2. Falsyfikator reguły: wiersz zewnętrzny przezroczysty (powrót = „już cofnięte”)."""
    sc = _scena(tmp_path, kod)
    try:
        zakres = writeback.przebieg_do_cofniecia(sc.con, "R2")
        assert zakres is not None and zakres.cofnij, zakres
        u = writeback.undo_run(sc.con, (sc.c2,), now=NOW)
        assert u.restored and _tel(sc.pliki[0]) == oczek, (u.restored, u.already)
    finally:
        sc.con.close()


def test_a1_ponowne_cofniecie_po_powrocie_wyniku_nie_wskrzesza_zapisu(tmp_path):
    """Pin HEAD (`astra` A1, bajtowo): jeden przebieg C1 A → B, C2 B → A, C3 A → C, cofnięcie przebiegu, bajty wyniku
    C3 z zewnątrz i ponowne cofnięcie C3 - C2 zostaje „już cofnięty” (łańcuch przebiegu), CLI nie przywraca EQ6.
    Falsyfikator reguły z rodowodem: przeskok cofnięcia C3 pod PIERWSZY wiersz zapisu C3 (C2 `zywy` wetuje łańcuch)."""
    sc = _scena(tmp_path, "A1")
    try:
        assert writeback.przebieg_do_cofniecia(sc.con, "R") is None
        assert _cofniecie_cli_nie_zmienia_pliku(sc)
    finally:
        sc.con.close()
