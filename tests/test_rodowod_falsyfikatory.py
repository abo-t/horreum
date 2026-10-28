"""AR-421: sceny-falsyfikatory reguły klasy cofnięcia z rodowodem stanu lokacji (`writeback.stan_rodowodu`) - łańcuch
cofnięć MIĘDZY przebiegami i powrót wyniku z zewnątrz, na prawdziwym pisarzu. Sceny: H1, H2, S2, S5, P2, R11 (łańcuchy
i powroty dwóch-trzech zapisów), Z1 (objazd z zewnątrz B → C → B po cofnięciu C2), A1 (ponowne cofnięcie po powrocie
wyniku), K2 (objazd z zewnątrz PRZED powrotem wyniku) - przewidywania: tabela reguły w planie fali.

Trzy rodzaje testów:
  * warunki wstępne sceny: regresja samej sceny (gest nie przeszedł, plik w innym stanie) nie miesza się z celem;
  * cel sceny: macierz konsumentów reguły dla H1 i S2 (zakres szuflady, szuflada po restarcie, CLI `header-fix --undo`
    = `undo_run`, wiersz Porządków, straż nowszego zapisu, klasa nieprzetworzonego, recepta osi), cele P2, R11, H2mr
    (wynik przywrócony z zewnątrz w JEDNYM przebiegu daje znów „Cofnij”), Z1, K2 oraz obiekt z karty `OBJECT` przy
    cofnięciu starszego zapisu A → B → A (`repo._plan_obiektu_z_karty`, straż nowszego żywego zapisu);
  * zachowanie sprzed rodowodu, które zostaje - piny: H2m, H2a, S5 (wynik wrócił z zewnątrz - „Cofnij” działa),
    S2 `am`/`mm` (dowód wprost cofnięcia w miejscu), A1 bajtowo (łańcuch przebiegu po ponownym cofnięciu), oraz dwa
    konsumenty S2, które mówiły prawdę bez rodowodu (Porządki, straż nowszego zapisu).

TELESCOP: RC8 = A (stan wyjściowy), EQ6 = B, EQ8 = C, ED120 = D. Prawdziwy pisarz na syntetycznych FITS w `tmp_path`,
bez atrap."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, repo, resolver, scan, writeback
from horreum.gui import queries

from test_writeback_cofniecie_przebiegu import NOW, _baza, _makro, _tel


def _skan(con, p):
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary(),
                       pochodzenie=repo.ZEWNETRZNE)


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
    """Każdy gest sceny przechodzi na prawdziwym pisarzu i zostawia pliki w stanie, który zakłada test celu
    (regresja sceny osobno od celu)."""
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
# Konsumenci, którzy na scenie S2 (dwa przebiegi bez ABA) mówili prawdę bez rodowodu: lokacja nie opisuje wyniku C2,
# więc Porządki i straż nowszego zapisu go nie widzą - piny, nie falsyfikatory rodowodu.
_S2_DZIS = ("porzadki", "straz_nowszego")
_MACIERZ = ([(k, n) for k in ("H1m", "H1a") for n in KONSUMENCI]
            + [(k, n) for k in ("S2aa", "S2ma") for n in KONSUMENCI if n not in _S2_DZIS])


@pytest.mark.parametrize("kod, konsument", _MACIERZ)
def test_konsument_widzi_cofniecie_miedzy_przebiegami(tmp_path, kod, konsument):
    """H1 (A → B → A) i S2 (A → B → C) między przebiegami, cofnięcie C2, potem C1 - zapis C2 jest „już cofnięty” dla
    KAŻDEGO konsumenta reguły klasy (rodowód: `cofniety`). Falsyfikator: reguła bez rodowodu - klasa C2
    `zatwierdzony`: zakres i szuflada po restarcie stawiały „Cofnij”, CLI przy H1 przywracał EQ6 (wynik C1, który
    człowiek cofnął), przy S2 odmawiał `undo_header_changed`."""
    sc = _scena(tmp_path, kod)
    try:
        assert KONSUMENCI[konsument](sc)
    finally:
        sc.con.close()


@pytest.mark.parametrize("kod", ["S2aa", "S2ma"])
@pytest.mark.parametrize("konsument", _S2_DZIS)
def test_konsument_s2_mowi_prawde_dzis(tmp_path, kod, konsument):
    """Pin: S2 bez ABA - Porządki i straż nowszego zapisu nie widzą C2 (odcisk lokacji ≠ wynik C2)."""
    sc = _scena(tmp_path, kod)
    try:
        assert KONSUMENCI[konsument](sc)
    finally:
        sc.con.close()


@pytest.mark.parametrize("kod", ["S2am", "S2mm"])
def test_cofniecie_w_miejscu_jest_dowodem_wprost(tmp_path, kod):
    """Pin: C2 cofnięty w miejscu (`undo` w `synced` - dowód zakończenia) - każdy konsument mówi „już cofnięte” także
    bez rodowodu (asymetria dróg zostaje: faza operacji w miejscu = dowód wprost)."""
    for konsument in KONSUMENCI:
        (tmp_path / konsument).mkdir()
        sc = _scena(tmp_path / konsument, kod)
        try:
            assert KONSUMENCI[konsument](sc), konsument
        finally:
            sc.con.close()


# ============================================================ cele pozostałych scen


def test_p2_cofniecie_czesciowe_rozstrzyga_per_lokacja(tmp_path):
    """P2: cofnięcie R2 przerwane po pierwszym pliku, potem R1 (pierwszy plik wraca do RC8, drugi odmawia). Ponowne
    cofnięcie C2: pierwszy plik „już cofnięty” (łańcuch C2 → C1 na tej lokacji), drugi wraca do EQ6; Porządki czekają
    na JEDEN plik. Falsyfikator: reguła bez rodowodu (klik przywracał oba pliki, pierwszy do EQ6 - wynik cofniętego
    C1)."""
    sc = _scena(tmp_path, "P2")
    try:
        assert queries.niedokonczone_cofniecia_kart(sc.con) == [(sc.c2, 1)]
        writeback.undo_run(sc.con, (sc.c2,), now=NOW)
        assert [_tel(p) for p in sc.pliki] == ["RC8", "EQ6"]
    finally:
        sc.con.close()


@pytest.mark.parametrize("kod", ["R11", "Z1", "K2"])
def test_cofniety_zapis_nie_wraca_po_dalszych_zmianach(tmp_path, kod):
    """C2 cofnięty, a potem plik zmieniali: R11 - cofnięcie C1 i zapis C3 cofnięty; Z1 - zmiana z zewnątrz
    B → C → B i cofnięcie C1; K2 - cofnięcie C3 i C1, z zewnątrz D, potem bajty wyniku C3 i ponowne cofnięcie C3.
    Plik ma odcisk wyniku C2, ale postawiło go cofnięcie innego zapisu: zakres R2 pusty, szuflada po restarcie bez
    „Cofnij”, CLI „już cofnięte” bez zmiany bajtu. Falsyfikatory: reguła bez rodowodu (klik przywracał EQ6 - wynik
    C1); przeskok cofnięcia pod NAJNOWSZY wiersz z wynikiem X (Z1); bez zejścia przez objazdy pod powrotem (K2)."""
    sc = _scena(tmp_path, kod)
    try:
        assert writeback.przebieg_do_cofniecia(sc.con, "R2") is None
        assert _cofniecie_cli_nie_zmienia_pliku(sc)
        assert _szuflada_po_restarcie(sc)
    finally:
        sc.con.close()


def test_h2mr_wynik_przywrocony_w_przebiegu_daje_cofnij(tmp_path):
    """H2mr: C1 cofnięty, bajty B wróciły z zewnątrz, C2 (TEN SAM przebieg) cofnięty, bajty A z wyniku C2 wróciły
    z zewnątrz - wynik C2 przyniosła treść spoza Horreum (rodowód `powrot` wetuje łańcuch przebiegu), więc „Cofnij” C2
    przywraca EQ6, jak w H2m między przebiegami. Falsyfikator: łańcuch przebiegu bez veta rodowodu („już cofnięte”)."""
    sc = _scena(tmp_path, "H2mr")
    try:
        u = writeback.undo_run(sc.con, (sc.c2,), now=NOW)
        assert u.restored and _tel(sc.pliki[0]) == "EQ6", (u.restored, u.already)
    finally:
        sc.con.close()


# ============================================================ piny zachowania sprzed rodowodu


@pytest.mark.parametrize("kod, oczek", [("H2m", "EQ6"), ("H2a", "EQ6"), ("S5", "RC8")])
def test_wynik_wrocil_z_zewnatrz_cofnij_dziala(tmp_path, kod, oczek):
    """Pin: wynik C2 wrócił z zewnątrz po jego cofnięciu (H2 między przebiegami, S5) - zakres R2 ma co cofnąć,
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
    """Pin (A1, bajtowo): jeden przebieg C1 A → B, C2 B → A, C3 A → C, cofnięcie przebiegu, bajty wyniku
    C3 z zewnątrz i ponowne cofnięcie C3 - C2 zostaje „już cofnięty” (łańcuch przebiegu), CLI nie przywraca EQ6.
    Falsyfikator reguły z rodowodem: przeskok cofnięcia C3 pod PIERWSZY wiersz zapisu C3 (C2 `zywy` wetuje łańcuch)."""
    sc = _scena(tmp_path, "A1")
    try:
        assert writeback.przebieg_do_cofniecia(sc.con, "R") is None
        assert _cofniecie_cli_nie_zmienia_pliku(sc)
    finally:
        sc.con.close()


# ============================================================ obiekt z karty `OBJECT` przy łańcuchu A → B → A


def _plik_z_pusta_karta(tmp_path):
    """FITS z kartą `OBJECT` PUSTĄ (nagłówek nie nazywa obiektu - krok 4 planu obiektu z karty przepuszcza)."""
    d = tmp_path / "LIGHTS" / "NGC7635" / "RC8"
    d.mkdir(parents=True)
    p = d / "a.fits"
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16) + 1)
    for k, v in (("IMAGETYP", "Light"), ("OBJECT", ""), ("TELESCOP", "RC8"), ("DATE-OBS", "2024-03-15T21:30:45")):
        hdu.header[k] = v
    hdu.writeto(str(p))
    return p


def _karta_object(con, run_id, location_id, wartosc):
    naglowek = con.execute("SELECT header_hash FROM location WHERE id = ?", (location_id,)).fetchone()[0]
    repo.stage_pending(con, run_id=run_id, location_id=location_id, keyword="OBJECT", idx=0, op="set",
                       old_value=None, new_value=wartosc, new_type="str", new_comment=None,
                       expected_header_hash=naglowek)


def _obiekt(con, frame_id):
    return tuple(con.execute("SELECT o.canon, f.object_source FROM frame f LEFT JOIN object o ON o.id = f.object_id "
                             "WHERE f.id = ?", (frame_id,)).fetchone())


@pytest.mark.parametrize("inplace", [False, True], ids=["atomowo", "w_miejscu"])
def test_aba_karty_object_cofniecie_starszego_odtwarza_obiekt(tmp_path, inplace):
    """Karta `OBJECT` A → B → A między przebiegami: C1 (R1) pisze `NGC 7635` w pustą kartę, „Rozwiąż” przypisuje
    obiekt z nagłówka, C2 (R2) czyści kartę z powrotem; cofnięcie C2, potem C1. Cofnięcie C1 odtwarza obiekt sprzed
    zapisu (klatka bez obiektu, `objects_restored` = ta klatka): straż nowszego żywego zapisu w planie obiektu z karty
    (`repo._plan_obiektu_z_karty`, krok 0) widzi C2 jako cofnięty (rodowód), choć odcisk lokacji = wynik C2.
    Falsyfikator: reguła bez rodowodu - C2 „żywy”, plan obiektu zwraca None, klatka zostaje przy obiekcie z karty
    cofniętego C1."""
    con = db.open_db(str(tmp_path / "h.db"))
    try:
        p = _plik_z_pusta_karta(tmp_path)
        _skan(con, p)
        lid, fid = con.execute("SELECT id, frame_id FROM location").fetchone()
        _karta_object(con, "R1", lid, "NGC 7635")
        c1 = writeback.commit(con, "R1", now=NOW, inplace=inplace)
        assert c1.applied, c1
        resolver.run_resolver(con, NOW)
        assert _obiekt(con, fid) == ("NGC7635", "header")
        _karta_object(con, "R2", lid, "")
        c2 = writeback.commit(con, "R2", now=NOW, inplace=False)
        assert c2.applied, c2
        assert writeback.undo(con, c2.commit_id, now=NOW).complete
        u1 = writeback.undo(con, c1.commit_id, now=NOW)
        assert u1.complete and u1.objects_restored == (fid,), u1
        assert _obiekt(con, fid) == (None, None) and fits.getheader(str(p))["OBJECT"] == ""
    finally:
        con.close()
