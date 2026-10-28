"""AR-421, AR-422, AR-423: reguła klasy cofnięcia z RODOWODEM stanu lokacji (`writeback.stan_rodowodu` nad wierszami
`location_state`) - czysta reguła na sekwencjach ręcznych, rodziny scen na prawdziwym pisarzu (klasa i powód
wykonawcy), jedna migawka odczytu predykatów, które rozstrzygają zapis, cofnięcie zmiany obiektu po łańcuchu cofnięć
kart (AR-422) i kotwica wyniku zapisu odzyskanego, którego nagłówek wrócił z zewnątrz (AR-423).

Sekwencje ręczne (`_SEKWENCJE`): wiersz `cNX` - zapis backupu N z nagłówkiem X, `uNX` - cofnięcie backupu N, po którym
plik ma nagłówek X, `eX` - odczyt zewnętrzny z nagłówkiem X, `rX` - własny powrót pisarza; `post` - nagłówek wyniku
każdego backupu. Prawdziwy pisarz na syntetycznych FITS/XISF w `tmp_path`; atrapy wyłącznie wyboru drogi pisarza
(`Fallback` zapisu w miejscu), awarii weryfikacji i podmiany pliku w oknie."""
from __future__ import annotations

import dataclasses
import hashlib
import os
from types import SimpleNamespace

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, object_change as oc, repo, writeback
from horreum.item_reasons import PowodPozycji

from test_cofniecie_zamiar_kazda_droga import _ponowny_zapis_bez_cofniecia
from test_rodowod_falsyfikatory import _cofnij, _scena, _skan, _z_zewnatrz, _zapis
from test_rodowod_pisarze import _Smierc, _odzysk_przy_bazie_znajacej_stan_rozdarty, _smierc_po_podmianie
from test_writeback_cofniecie_przebiegu import (NOW, _BarieraOdczytu, _baza, _fakty_wprost, _jeden_zapis, _klasy_wprost,
                                                _klatki, _makro, _nakladka, _tel)
from test_writeback_inplace import _baza_z_plikiem, _fits, _fits_dwa_hdu, _xisf, _xisf_dwa_obrazy


# ============================================================ czysta reguła na sekwencjach ręcznych

# nazwa → (wiersze, post backupów, oczekiwany stan backupów). Sceny planu (H1, S2, P2, R11, H2, S5, Z1, Z2, A1, A3,
# granice, piny Porządków, K1-K8) i dwie sekwencje powtórzonego cofnięcia bez nowej instancji wyniku (v4 = None).
_SEKWENCJE = {
    "H1": ("c1B c2A u2B u1A", "1B 2A", {1: "cofniety", 2: "cofniety"}),
    "S2": ("c1B c2C u2B u1A", "1B 2C", {1: "cofniety", 2: "cofniety"}),
    "P2/L2": ("c2B c4A", "2B 4A", {2: "zywy", 4: "zywy"}),
    "R11": ("c1B c2A u2B u1A c3C u3A", "1B 2A 3C", {1: "cofniety", 2: "cofniety", 3: "cofniety"}),
    "H2": ("c1B u1A eB c2A u2B eA", "1B 2A", {1: None, 2: "powrot"}),
    "S5": ("c1B u1A c2C u2A eC", "1B 2C", {1: None, 2: "powrot"}),
    "Z1": ("c1B c2A u2B eC eB u1A", "1B 2A", {1: "cofniety", 2: "cofniety"}),
    "Z2": ("c1B u1A eB", "1B", {1: "powrot"}),
    "A1": ("c1B c2A c3C u3A u2B u1A eC u3A", "1B 2A 3C", {1: "cofniety", 2: "cofniety", 3: "cofniety"}),
    "A3": ("c0A u1A c2B", "0A 1B 2B", {0: None, 1: "cofniety", 2: "zywy"}),
    "zapis poznany skanem": ("eB c2A u2B u1A", "1B 2A", {1: "cofniety", 2: "cofniety"}),
    "historia sprzed rodowodu": ("", "1B", {1: None}),
    "powtorzony zapis": ("c0B u0A c1B u1A c2B u2A c3B", "0B 1B 2B 3B",
                         {0: "cofniety", 1: "cofniety", 2: "cofniety", 3: "zywy"}),
    "nowszy zakonczony starszy zywy": ("c1B u1A c2B u2A eB", "1B 2B", {1: "powrot", 2: "powrot"}),
    "zmiana po cofnieciu nowszego": ("c1B c3C u3B eX", "1B 3C", {1: None, 3: None}),
    "K1": ("c1B c2A u2B u1A eB eC eB u1A", "1B 2A", {1: "cofniety", 2: "cofniety"}),
    "K2": ("c1B c2A c3C u3A u2B u1A eD eC u3A", "1B 2A 3C", {1: "cofniety", 2: "cofniety", 3: "cofniety"}),
    "K3": ("c1B c2C u2B", "1B 2C", {1: "zywy", 2: "cofniety"}),
    "K4": ("c1B c2A u2B eA c3C u3A", "1B 2A 3C", {2: "powrot", 3: "cofniety"}),
    "K5": ("c1B u1A eB c2A u2B u1A", "1B 2A", {2: "cofniety"}),
    "K6 rollback po stanie rozdartym": ("c1B eT rB", "1B", {1: None}),
    "K7": ("c2A eD c9B u9A", "2A 9B", {2: None}),
    "K8": ("c1B c2A c3C u3A u2B u1A eA eC u3A", "1B 2A 3C", {2: "powrot"}),
    "przypisanie po powrocie wyniku C2": ("c1B c2A u2B u1A eC eA u1A", "1B 2A", {1: "cofniety", 2: None}),
    "powtorzone cofniecie bez instancji": ("c1B c2A u2B u1A u1A", "1B 2A", {1: "cofniety", 2: None}),
}
_POCHODZENIA = {"c": "commit", "u": "undo", "e": "external", "r": "rollback"}


def _wiersze(spec, post):
    """Wiersze `stan_rodowodu` z zapisu `cNX`/`uNX`/`eX`/`rX` (id od 1)."""
    wynik = []
    for i, t in enumerate(spec.split(), 1):
        backup = int(t[1]) if t[1].isdigit() else None
        naglowek = t[2:] if backup is not None else t[1:]
        wynik.append((i, _POCHODZENIA[t[0]], backup, naglowek, post.get(backup)))
    return wynik


def _post(tekst):
    return {int(t[:-1]): t[-1] for t in tekst.split()}


@pytest.mark.parametrize("nazwa", list(_SEKWENCJE))
def test_stan_rodowodu_tabela(nazwa):
    """Czysta reguła na sekwencjach ręcznych - stan każdego backupu: cofnięcie zapisu X przeskakuje pod NAJSTARSZY
    wiersz z wynikiem X po poprzednim cofnięciu X i schodzi przez obce objazdy pod powrotem wyniku, `rollback`
    przezroczysty, `external` kończy (`powrot` tylko przy własnym odcisku wiersza). Falsyfikatory: przeskok pod pierwszy
    zapis X (A1, K2), pod NAJNOWSZY wiersz z wynikiem X (Z1, K1, K2), bez zejścia przez objazdy (K2), cofnięcie bez
    przeskoku (Z1, K1, K2), `external` przezroczysty (H2, S5, Z2), `rollback` jak `external` (K6), powtórzone
    cofnięcie pod przeskok poprzedniego (dwie ostatnie sekwencje - przypisanie po powrocie wyniku C2 nie cofa C2)."""
    spec, post_tekst, oczek = _SEKWENCJE[nazwa]
    post = _post(post_tekst)
    wiersze = _wiersze(spec, post)
    assert {b: writeback.stan_rodowodu(b, post[b], wiersze) for b in oczek} == oczek


def test_stan_rodowodu_expect():
    """EXPECT: dwa wiersze `commit` jednego backupu (niezmiennik zapisu rodowodu) → `AssertionError`; sekwencja
    z wierszem `commit` po `undo` tego zapisu (spóźnione przypisanie, którego zapis rodowodu nie robi) kończy się,
    a przeskok idzie wyłącznie wstecz. Falsyfikator: przeskok bez warunku „starszy od cofnięcia” (cykl)."""
    post = _post("1B 2A")
    with pytest.raises(AssertionError):
        writeback.stan_rodowodu(1, "B", _wiersze("c1B u1A c1B", post))
    post = _post("0A 1B 2B")
    assert writeback.stan_rodowodu(0, "A", _wiersze("c0A u1A c2B c1B", post)) is None


def test_powtorzone_cofniecie_po_powrocie_wyniku_zostawia_cofnij(tmp_path):
    """C1 A → B, C2 B → A (dwa przebiegi), cofnięcie C2, cofnięcie C1, z zewnątrz C, potem bajty A z zewnątrz (wynik C2
    przywrócony spoza Horreum), a na koniec przypisanie „już cofnięte” C1 bez mutacji pliku (`repo.attribute_undo_state`
    - para odcisków śladu cofnięcia C1). Plik niesie wynik C2 przyniesiony z zewnątrz: klasa C2 `zatwierdzony`, zakres
    R2 zachowany. Falsyfikator: powtórzone cofnięcie C1 bez nowej instancji wyniku C1 pod przeskok poprzedniego
    cofnięcia (fałszywe `cofniety`, zakres R2 znika)."""
    con, (p,) = _baza(tmp_path, 1, "s")
    try:
        c1 = _zapis(con, "R1", "EQ6")
        c2 = _zapis(con, "R2", "RC8")
        _cofnij(con, c2, p, "EQ6")
        _cofnij(con, c1, p, "RC8")
        po_cofnieciu_c1 = p.read_bytes()
        _z_zewnatrz(con, p, tel="EQ8")
        _z_zewnatrz(con, p, bajty=po_cofnieciu_c1)
        [b1] = writeback.backups_for_commit(con, c1)
        [slad] = [r[0] for r in con.execute("SELECT id FROM atomic_undo WHERE backup_id = ?", (b1["id"],))]
        lid = int(b1["location_id"])
        assert repo.attribute_undo_state(con, location_id=lid, atomic_undo_id=slad, now=NOW) is not None
        assert [r[0] for r in con.execute("SELECT origin FROM location_state ORDER BY id")] == [
            "commit", "commit", "undo", "undo", "external", "external", "undo"]
        [b2] = writeback.backups_for_commit(con, c2)
        assert writeback._klasa_z_bazy(con, b2)[1] == "zatwierdzony"
        zakres = writeback.przebieg_do_cofniecia(con, "R2")
        assert zakres is not None and zakres.cofnij, zakres
    finally:
        con.close()


# ============================================================ rodziny scen na prawdziwym pisarzu: klasa i powód wykonawcy


def _sc(con, pliki, sciezka=None, **commity):
    return SimpleNamespace(con=con, pliki=pliki, commity=commity, sciezka=sciezka)


def _z_falsyfikatorow(kod):
    def _b(tmp_path, monkeypatch):
        s = _scena(tmp_path, kod)
        return _sc(s.con, s.pliki, **{n: getattr(s, n) for n in ("c1", "c2", "c3") if hasattr(s, n)})
    return _b


def _k1(tmp_path, monkeypatch):
    """K1: H1, potem bajty wyniku C1 z zewnątrz, objazd C, znów wynik C1, ponowne cofnięcie C1."""
    con, (p,) = _baza(tmp_path, 1, "s")
    c1 = _zapis(con, "R1", "EQ6")
    po_c1 = p.read_bytes()
    c2 = _zapis(con, "R2", "RC8")
    _cofnij(con, c2, p, "EQ6")
    _cofnij(con, c1, p, "RC8")
    _z_zewnatrz(con, p, bajty=po_c1)
    _z_zewnatrz(con, p, tel="EQ8")
    _z_zewnatrz(con, p, bajty=po_c1)
    _cofnij(con, c1, p, "RC8")
    return _sc(con, [p], c1=c1, c2=c2)


def _k5(tmp_path, monkeypatch):
    """K5: C1 cofnięty, wynik C1 z zewnątrz, C2 B → A cofnięty, ponowne cofnięcie C1."""
    con, (p,) = _baza(tmp_path, 1, "s")
    c1 = _zapis(con, "R1", "EQ6")
    po_c1 = p.read_bytes()
    _cofnij(con, c1, p, "RC8")
    _z_zewnatrz(con, p, bajty=po_c1)
    c2 = _zapis(con, "R2", "RC8")
    _cofnij(con, c2, p, "EQ6")
    _cofnij(con, c1, p, "RC8")
    return _sc(con, [p], c1=c1, c2=c2)


def _a3(tmp_path, monkeypatch):
    """A3: C0 (R0), C1 (R1) z padem re-syncu - wyniku C1 baza nie poznała, cofnięcie C1, C2 (R2) zapisuje te same bajty
    co C1."""
    con, (p,) = _baza(tmp_path, 1, "s")
    c0 = _zapis(con, "R0", "EQ8")
    _makro(con, "R1", "EQ6")
    with monkeypatch.context() as m:
        m.setattr(writeback, "_resync", lambda *a, **kw: (_ for _ in ()).throw(OSError(5, "zerwany udział")))
        assert len(writeback.commit(con, "R1", now=NOW).failed) == 1
    c1 = con.execute("SELECT max(id) FROM commits").fetchone()[0]
    _cofnij(con, c1, p, "EQ8")
    c2 = _zapis(con, "R2", "EQ6")
    return _sc(con, [p], c0=c0, c1=c1, c2=c2)


def _zapis_poznany_skanem(tmp_path, monkeypatch):
    """Okno śmierci po potwierdzeniu podmiany C1, przed re-synciem - wynik C1 poznany skanem; C2 B → A, cofnięcie C2
    i C1."""
    con, (p,) = _baza(tmp_path, 1, "s")
    _makro(con, "R1", "EQ6")
    _smierc_po_podmianie(monkeypatch, z_potwierdzeniem=True)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R1", now=NOW)
    monkeypatch.undo()
    c1 = con.execute("SELECT max(id) FROM commits").fetchone()[0]
    _skan(con, p)
    c2 = _zapis(con, "R2", "RC8")
    _cofnij(con, c2, p, "EQ6")
    _cofnij(con, c1, p, "RC8")
    return _sc(con, [p], c1=c1, c2=c2)


def _dwa_hdu(tmp_path):
    """FITS z drugim HDU (dane drugiego HDU poza `sha1_data` obrazu), skan; zwraca `(con, ścieżka, offset danych
    drugiego HDU)`."""
    con = db.open_db(str(tmp_path / "s.db"))
    p = tmp_path / "s0.fits"
    prim = fits.PrimaryHDU(data=(np.arange(64 * 64) % 3000).astype(np.int16).reshape(64, 64))
    for k, v in (("IMAGETYP", "Light"), ("OBJECT", "NGC7000"), ("TELESCOP", "RC8"),
                 ("DATE-OBS", "2024-03-15T21:30:45"), ("EXPTIME", 300.0)):
        prim.header[k] = v
    fits.HDUList([prim, fits.ImageHDU(data=np.full((64, 64), 3, dtype=np.int16), name="DRUGI")]).writeto(str(p))
    with fits.open(str(p)) as hdul:
        drugi = hdul.fileinfo(1)["datLoc"]
    _skan(con, p)
    return con, p, drugi


def _a1_semantycznie(tmp_path, monkeypatch):
    """A1 semantycznie: jeden przebieg C1 A → B, C2 B → A, C3 A → C, cofnięcie przebiegu, bajty wyniku C3 ze zmienionym
    drugim HDU z zewnątrz, ponowne cofnięcie C3 (wynik A z innymi danymi drugiego HDU)."""
    con, p, drugi = _dwa_hdu(tmp_path)
    c1 = _zapis(con, "R", "EQ6")
    c2 = _zapis(con, "R", "RC8")
    c3 = _zapis(con, "R", "EQ8")
    po_c3 = bytearray(p.read_bytes())
    assert writeback.undo_run(con, (c1, c2, c3), now=NOW).complete
    po_c3[drugi + 10] ^= 0x01
    _z_zewnatrz(con, p, bajty=bytes(po_c3))
    _cofnij(con, c3, p, "RC8")
    return _sc(con, [p], c1=c1, c2=c2, c3=c3)


def _ponowny_zapis(tmp_path, monkeypatch):
    """C1 (R1) na dwóch plikach cofnięty atomowo, C2 (R2) pisze TĘ SAMĄ kartę i zostaje."""
    con, _oczek = _ponowny_zapis_bez_cofniecia(tmp_path, monkeypatch)
    pliki = [__import__("pathlib").Path(r[0]) for r in con.execute("SELECT path FROM location ORDER BY id")]
    return _sc(con, pliki, c1=1, c2=2)


def _nakladka_inny_przebieg(tmp_path, monkeypatch):
    """Nakładka `aa` (R: C1 na L0 i L1, C2 na L0) cofnięta w całości, potem przebieg S zapisuje L0."""
    con, pliki = _nakladka(tmp_path, "aa")
    assert writeback.undo_run(con, (1, 2), now=NOW).complete
    _makro(con, "S", "EQ8", [_klatki(con)[0]])
    assert writeback.commit(con, "S", now=NOW, inplace=False).applied
    return _sc(con, pliki, c1=1, c2=2, s=3)


Z_, T_ = "zakonczony", "zatwierdzony"
# scena → (budowa, {(commit, plik): (klasa, kod powodu wykonawcy albo None - nie sprawdzany, cofnięcie zmienia plik)})
_RODZINY = {
    "H1a": (_z_falsyfikatorow("H1a"), {("c1", 0): (Z_, "undo_already_own"), ("c2", 0): (Z_, "undo_already_lineage")}),
    "Z1": (_z_falsyfikatorow("Z1"), {("c1", 0): (Z_, "undo_already_own"), ("c2", 0): (Z_, "undo_already_lineage")}),
    "K2": (_z_falsyfikatorow("K2"), {("c1", 0): (Z_, "undo_already_own"), ("c2", 0): (Z_, "undo_already_lineage"),
                                     ("c3", 0): (Z_, "undo_already_own")}),
    "K1": (_k1, {("c1", 0): (Z_, "undo_already_own"), ("c2", 0): (Z_, "undo_already_lineage")}),
    "K5": (_k5, {("c1", 0): (Z_, "undo_already_own"), ("c2", 0): (Z_, "undo_already_lineage")}),
    "A3": (_a3, {("c0", 0): (T_, "undo_newer_write"), ("c1", 0): (Z_, "undo_already_lineage"),
                 ("c2", 0): (T_, None)}),
    "zapis_poznany_skanem": (_zapis_poznany_skanem, {("c1", 0): (Z_, "undo_already_own"),
                                                     ("c2", 0): (Z_, "undo_already_lineage")}),
    "A1_semantycznie": (_a1_semantycznie, {("c1", 0): (Z_, "undo_already_lineage"),
                                           ("c2", 0): (Z_, "undo_already_lineage"),
                                           ("c3", 0): (Z_, "undo_already_own")}),
    "ponowny_zapis_tej_samej_karty": (_ponowny_zapis, {("c1", 0): (Z_, "undo_already_lineage"),
                                                       ("c1", 1): (Z_, "undo_already_lineage"),
                                                       ("c2", 0): (T_, None), ("c2", 1): (T_, None)}),
    "nakladka_cofnieta_i_inny_przebieg": (_nakladka_inny_przebieg, {
        ("c1", 0): (Z_, "undo_already_lineage"), ("c1", 1): (Z_, "undo_already_own"),
        ("c2", 0): (Z_, "undo_already_lineage")}),
}
_PRZYPADKI_RODZIN = [(s, k) for s, (_b, oczek) in _RODZINY.items() for k in oczek]


def _backup(sc, commit, plik):
    lid = sc.con.execute("SELECT id FROM location WHERE path = ?", (str(sc.pliki[plik]),)).fetchone()[0]
    [b] = [b for b in writeback.backups_for_commit(sc.con, sc.commity[commit]) if int(b["location_id"]) == lid]
    return b


@pytest.mark.parametrize("scena, klucz", _PRZYPADKI_RODZIN, ids=[f"{s}-{c}-{p}" for s, (c, p) in _PRZYPADKI_RODZIN])
def test_rodzina_klasa_i_powod_wykonawcy(tmp_path, monkeypatch, scena, klucz):
    """Rodziny tabeli reguły na prawdziwym pisarzu: łańcuch między przebiegami (H1, Z1, K1, K2, K5, zapis poznany
    skanem), własne cofnięcie przykryte nowszym zapisem (A3, A1 semantycznie, ta sama karta zapisana ponownie, nakładka
    cofnięta i przebieg S): klasa backupu (zasilacz pojedynczy == wsad) i wynik cofnięcia TEGO backupu pętlą
    wykonawcy (`_cofnij_backupy` = `undo_run`/CLI) - „już cofnięte” z powodem reguły, bez zmiany bajtu żadnego pliku.
    Starszy zapis łańcucha mówi „już cofnięte” wynikiem własnym (dawniej `undo_newer_write` - cofnięty nowszy uchodził
    za żywy). Falsyfikatory: reguła bez rodowodu; powód rodowodu dla łańcucha w przebiegu; rodowód przed dowodem
    wprost; przeskok pod pierwszy zapis X (A1 semantycznie, zapis poznany skanem); przeskok pod najnowszy wiersz
    z wynikiem X (Z1, K1, K2)."""
    budowa, oczek = _RODZINY[scena]
    klasa, kod = oczek[klucz]
    sc = budowa(tmp_path, monkeypatch)
    try:
        b = _backup(sc, *klucz)
        assert writeback._klasa_z_bazy(sc.con, b)[1] == klasa
        run = sc.con.execute("SELECT run_id FROM commits WHERE id = ?", (sc.commity[klucz[0]],)).fetchone()[0]
        wsad = {(c, lo): k for c, lo, k in writeback._klasy_przebiegu(sc.con, run)}
        assert wsad[(sc.commity[klucz[0]], int(b["location_id"]))] == klasa
        if kod is None:
            return
        przed = [p.read_bytes() for p in sc.pliki]
        u = writeback._cofnij_backupy(sc.con, run, [(sc.commity[klucz[0]], b)], now=NOW, progress=None,
                                      should_cancel=None)
        [fr] = u.restored + u.blocked + u.failed
        assert (fr.status, getattr(fr.reason, "code", None)) == ("blocked", kod), fr
        assert (u.already == [fr]) == kod.startswith("undo_already")
        assert [p.read_bytes() for p in sc.pliki] == przed
    finally:
        sc.con.close()


def _bajty_z_zewnatrz_bez_skanu(p, bajty):
    """Zmiana pliku spoza Horreum BEZ skanu: bajty pod ścieżką i `mtime` jawnie inny niż w bazie (+100 s)."""
    p.write_bytes(bajty)
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 100 * 10 ** 9))


@pytest.mark.parametrize("przebiegi", ["dwa", "jeden"], ids=["rodowod", "lancuch_w_przebiegu"])
def test_skrot_juz_cofnietego_tylko_przy_mtime_z_bazy(tmp_path, przebiegi):
    """C1 A → B, C2 B → C (dwa przebiegi - rodowód; jeden przebieg - łańcuch przebiegu), droga atomowa; cofnięcie C2,
    potem C1. Bajty C (wynik C2) wracają spoza Horreum z nowym `mtime`, BEZ skanu - baza dalej opisuje A. Cofnięcie C2
    nie bierze skrótu „już cofnięte” (reguła klasy czyta wyłącznie bazę), tylko zwykłą drogą czyta plik: przywraca B,
    bez „już cofnięte”. Falsyfikator: skrót wykonawcy bez kontroli `mtime` pliku (`undo_already_lineage` /
    `undo_already_chain`, plik zostaje C)."""
    con, (p,) = _baza(tmp_path, 1, "s")
    try:
        c1 = _zapis(con, "R1", "EQ6")
        c2 = _zapis(con, "R2" if przebiegi == "dwa" else "R1", "EQ8")
        po_c2 = p.read_bytes()
        _cofnij(con, c2, p, "EQ6")
        _cofnij(con, c1, p, "RC8")
        [b2] = writeback.backups_for_commit(con, c2)
        oczekiwany = writeback._JUZ_RODOWODEM if przebiegi == "dwa" else writeback._JUZ_LANCUCHEM
        assert writeback._powod_juz_cofnietego(con, b2) is oczekiwany
        _bajty_z_zewnatrz_bez_skanu(p, po_c2)
        u = writeback.undo(con, c2, now=NOW)
        assert len(u.restored) == 1 and not u.already, u
        assert _tel(p) == "EQ6"
    finally:
        con.close()


@pytest.mark.parametrize("przebiegi", ["dwa", "jeden"], ids=["rodowod", "lancuch_w_przebiegu"])
def test_skrot_juz_cofnietego_powod_i_lokacja_w_jednej_migawce(tmp_path, monkeypatch, przebiegi):
    """Scena testu wyżej, ale bajty C wracają RAZEM z pełnym skanem drugiego połączenia - MIĘDZY powodem reguły klasy
    a odczytem lokacji w skrócie wykonawcy (bariera na pierwszym `_location` po powodzie). Skrót odpowiada z jednej
    migawki: lokacja ma `mtime` sprzed skanu, plik - po nim; cofnięcie C2 schodzi do ciała i przywraca B, bez „już
    cofnięte”. Falsyfikator: powód w migawce predykatu, lokacja i `mtime` poza nią - powód sprzed skanu z lokacją po
    skanie daje fałszywe „już cofnięte”, plik zostaje C."""
    con, (p,) = _baza(tmp_path, 1, "s")
    try:
        c1 = _zapis(con, "R1", "EQ6")
        c2 = _zapis(con, "R2" if przebiegi == "dwa" else "R1", "EQ8")
        po_c2 = p.read_bytes()
        _cofnij(con, c2, p, "EQ6")
        _cofnij(con, c1, p, "RC8")
        stan = {"uzbrojona": False, "skany": 0}
        powod_wzor, lokacja_wzor = writeback._powod_juz_cofnietego, writeback._location

        def _powod(con_, b):
            wynik = powod_wzor(con_, b)
            stan["uzbrojona"] = wynik is not None and stan["skany"] == 0
            return wynik

        def _lokacja(con_, location_id):
            if stan["uzbrojona"]:
                stan["uzbrojona"], stan["skany"] = False, stan["skany"] + 1
                con2 = db.connect(str(tmp_path / "s.db"))
                try:
                    _bajty_z_zewnatrz_bez_skanu(p, po_c2)
                    _skan(con2, p)
                finally:
                    con2.close()
            return lokacja_wzor(con_, location_id)

        monkeypatch.setattr(writeback, "_powod_juz_cofnietego", _powod)
        monkeypatch.setattr(writeback, "_location", _lokacja)
        u = writeback.undo(con, c2, now=NOW)
        assert stan["skany"] == 1
        assert len(u.restored) == 1 and not u.already, u
        assert _tel(p) == "EQ6"
    finally:
        con.close()


def test_powrot_tylko_z_odcisku_wiersza(tmp_path):
    """R: C0 A → B w miejscu cofnięty (faza `synced` - dowód wprost na zawsze), C1 A → C atomowo cofnięty (ślad
    wciągnięty); z zewnątrz D; C2 (S) zapisuje C - bieżący odcisk lokacji = wynik C1, ale postawił go C2. C1 dalej
    „już cofnięty” łańcuchem przebiegu: przejście kończy się na odczycie zewnętrznym D (None), nie na odcisku lokacji.
    Falsyfikator: `powrot` z odcisku bieżącej lokacji zamiast własnego odcisku wiersza (C1 `zatwierdzony`, zakres R
    z C1)."""
    con, (p,) = _baza(tmp_path, 1, "s")
    try:
        c0 = _zapis(con, "R", "EQ6", inplace=True)
        _cofnij(con, c0, p, "RC8")
        c1 = _zapis(con, "R", "EQ8")
        _cofnij(con, c1, p, "RC8")
        _z_zewnatrz(con, p, tel="ED120")
        _zapis(con, "S", "EQ8")
        assert [k for *_x, k in writeback._klasy_przebiegu(con, "R")] == [Z_, Z_]
        assert writeback.przebieg_do_cofniecia(con, "R") is None
    finally:
        con.close()


@pytest.mark.parametrize("kod", ["S2am", "S2mm"])
def test_dowod_wprost_mowi_wlasnym_powodem(tmp_path, kod):
    """C2 cofnięty w miejscu (dowód wprost `synced`) i rodowód `cofniety`: wykonawca zostawia dowód wprost ciału -
    „już cofnięte” z powodem operacji zamkniętej (`undo_already_op`), nie z rodowodu. Falsyfikator: powód rodowodu
    sprawdzany przed dowodem wprost."""
    sc = _scena(tmp_path, kod)
    try:
        [b2] = writeback.backups_for_commit(sc.con, sc.c2)
        u = writeback._cofnij_backupy(sc.con, "R2", [(sc.c2, b2)], now=NOW, progress=None, should_cancel=None)
        assert [fr.reason.code for fr in u.already] == ["undo_already_op"], u
    finally:
        sc.con.close()


def test_odzysk_po_skanie_stanu_rozdartego_zostaje_poza(tmp_path, monkeypatch):
    """Zapis w miejscu nieweryfikowany, baza zna jego stan (odczyt zewnętrzny), odzysk - wiersz `rollback`: klasa
    zapisu `poza` (baza nie opisuje jego wyniku), bez „Cofnij”."""
    con, p, op, przed = _odzysk_przy_bazie_znajacej_stan_rozdarty(tmp_path, monkeypatch)
    try:
        monkeypatch.undo()
        assert writeback.recover_torn(con, op["id"], now=NOW).status == "restored"
        assert [k for *_x, k in writeback._klasy_przebiegu(con, "R")] == ["poza"]
        assert writeback.przebieg_do_cofniecia(con, "R") is None
    finally:
        con.close()


# ============================================================ zasilacze: równoważność, jeden odczyt, jedna migawka


@pytest.mark.parametrize("kod", ["H1a", "S2aa", "P2", "Z1", "K2", "H2mr", "A1", "R11"])
def test_rownowaznosc_zasilaczy_scen_rodowodu(tmp_path, kod):
    """Zasilacz wsadowy i pojedynczy dają te same fakty (ze stanem rodowodu) i te same klasy na scenach łańcuchów między
    przebiegami i powrotów wyniku. Falsyfikatory: stan z wierszy innej lokacji; `post_hash` innego backupu."""
    sc = _scena(tmp_path, kod)
    try:
        for run in [r[0] for r in sc.con.execute("SELECT DISTINCT run_id FROM commits ORDER BY run_id")]:
            assert writeback._fakty_przebiegu(sc.con, run) == _fakty_wprost(sc.con, run)
            assert writeback._klasy_przebiegu(sc.con, run) == _klasy_wprost(sc.con, run)
    finally:
        sc.con.close()


def test_wsad_jeden_odczyt_rodowodu(tmp_path):
    """Wsad czyta wiersze rodowodu WSZYSTKICH lokacji przebiegu jednym zapytaniem: cztery SELECT-y na przebieg (dwa
    pliki). Falsyfikator: odczyt wierszy per lokacja w pętli."""
    sc = _scena(tmp_path, "P2")
    try:
        licznik = _BarieraOdczytu(sc.con, 10 ** 6, lambda: None)
        writeback._fakty_przebiegu(licznik, "R1")
        assert licznik._licz == 4
    finally:
        sc.con.close()


def _zmiana_z_zewnatrz(sciezka_bazy, p, tel="ED120"):
    def _zapis():
        con2 = db.connect(sciezka_bazy)
        try:
            fits.setval(str(p), "TELESCOP", value=tel)
            _skan(con2, p)
        finally:
            con2.close()
    return _zapis


def test_wsad_czwarty_odczyt_w_migawce(tmp_path):
    """H1a: zmiana pliku z zewnątrz i skan drugim połączeniem MIĘDZY odczytem śladów a odczytem wierszy rodowodu
    (bariera przed czwartym SELECT-em) - klasa C2 z migawki (`zakonczony`); po zapisie `zatwierdzony` (odczyt
    zewnętrzny bez wyniku C2). Falsyfikator: wiersze rodowodu czytane poza transakcją odczytu wsadu."""
    sc = _scena(tmp_path, "H1a")
    try:
        bariera = _BarieraOdczytu(sc.con, 4, _zmiana_z_zewnatrz(sc.sciezka, sc.pliki[0]))
        assert [k for *_x, k in writeback._klasy_przebiegu(bariera, "R2")] == [Z_]
        assert [k for *_x, k in writeback._klasy_przebiegu(sc.con, "R2")] == [T_]
    finally:
        sc.con.close()


def test_wsad_odczyt_sladow_w_migawce_pod_regula(tmp_path):
    """C1 cofnięty atomowo, z zewnątrz C, potem bajty wyniku cofnięcia - klasa C1 z WYNIKU WŁASNEGO (rodowód kończy się
    na odczycie zewnętrznym bez wyniku C1 - None). Zmiana z zewnątrz drugim połączeniem przed odczytem śladów (bariera
    przed trzecim SELECT-em): klasa z migawki `zakonczony`, po zapisie `zatwierdzony`. Falsyfikator: odczyt śladów
    poza transakcją odczytu wsadu (scena, w której rodowód tego nie przykrywa)."""
    con, (p,) = _baza(tmp_path, 1, "s")
    try:
        c1 = _zapis(con, "R1", "EQ6")
        _cofnij(con, c1, p, "RC8")
        po_cofnieciu = p.read_bytes()
        _z_zewnatrz(con, p, tel="EQ8")
        _z_zewnatrz(con, p, bajty=po_cofnieciu)
        bariera = _BarieraOdczytu(con, 3, _zmiana_z_zewnatrz(str(tmp_path / "s.db"), p))
        assert [k for *_x, k in writeback._klasy_przebiegu(bariera, "R1")] == [Z_]
        assert [k for *_x, k in writeback._klasy_przebiegu(con, "R1")] == [T_]
    finally:
        con.close()


def test_predykat_wykonawcy_w_jednej_migawce(tmp_path):
    """Nakładka `aa` cofnięta w całości: predykat wykonawcy dla nowszego backupu L0 - łańcuch przebiegu
    (`undo_already_chain`). Zmiana L0 z zewnątrz drugim połączeniem PO odczycie faktów i rodowodu, PRZED odczytem
    starszych backupów przebiegu (bariera przed trzecim SELECT-em): odpowiedź z migawki - łańcuch; po zapisie - None
    (łańcuch zerwany, rodowód kończy się na odczycie zewnętrznym). Falsyfikator: predykat bez jednej migawki -
    rodowód sprzed zapisu (`cofniety`) z łańcuchem po zapisie daje „już cofnięte” rodowodem, którego nie było w żadnym
    stanie bazy."""
    con, pliki = _nakladka(tmp_path, "aa")
    try:
        assert writeback.undo_run(con, (1, 2), now=NOW).complete
        [b2] = writeback.backups_for_commit(con, 2)
        bariera = _BarieraOdczytu(con, 3, _zmiana_z_zewnatrz(str(tmp_path / "n.db"), pliki[0]))
        assert writeback._powod_juz_cofnietego(bariera, b2) is writeback._JUZ_LANCUCHEM
        assert not con.in_transaction
        assert writeback._powod_juz_cofnietego(con, b2) is None
    finally:
        con.close()


def test_straz_nowszego_zapisu_w_jednej_migawce(tmp_path):
    """C1 (R1) A → B, C2 (R2) B → A - nowszy żywy zapis C2. Zmiana pliku z zewnątrz drugim połączeniem po odczycie
    kandydatów, przed faktami C2 (bariera przed czwartym SELECT-em): straż odpowiada stanem z migawki (C2); po zapisie
    - None (baza nie opisuje wyniku C2). Falsyfikator: straż bez jednej migawki (fakty C2 po zapisie)."""
    con, (p,) = _baza(tmp_path, 1, "s")
    try:
        c1 = _zapis(con, "R1", "EQ6")
        c2 = _zapis(con, "R2", "RC8")
        [b1] = writeback.backups_for_commit(con, c1)
        bariera = _BarieraOdczytu(con, 4, _zmiana_z_zewnatrz(str(tmp_path / "s.db"), p))
        assert writeback._nowszy_zywy_zapis(bariera, b1) == c2
        assert not con.in_transaction
        assert writeback._nowszy_zywy_zapis(con, b1) is None
    finally:
        con.close()


def test_predykat_w_transakcji_wolajacego_nie_zamyka_jej(tmp_path):
    """Predykat wykonawcy wołany W otwartej transakcji wołającego (`_migawka_odczytu` zagnieżdżona): czyta w niej -
    widzi niezatwierdzony zapis wołającego (wiersz rodowodu `external` z obcym nagłówkiem: C2 przestaje być „już
    cofnięty”) - i jej nie zamyka: transakcja trwa po wyjściu, a po jej wycofaniu predykat wraca do rodowodu.
    Falsyfikatory: migawka zawsze wycofuje w `finally` (zapis wołającego znika, transakcja zamknięta); migawka zawsze
    otwiera własne `BEGIN` (błąd zagnieżdżenia)."""
    sc = _scena(tmp_path, "H1a")
    try:
        [b2] = writeback.backups_for_commit(sc.con, sc.c2)
        lid = int(b2["location_id"])
        sc.con.execute("BEGIN")
        sc.con.execute("INSERT INTO location_state(location_id, origin, file_sha1, header_hash, at) "
                       "VALUES (?, 'external', ?, ?, ?)", (lid, "f" * 40, "e" * 40, NOW))
        assert writeback._powod_juz_cofnietego(sc.con, b2) is None
        assert sc.con.in_transaction
        assert sc.con.execute("SELECT count(*) FROM location_state WHERE header_hash = ?",
                              ("e" * 40,)).fetchone()[0] == 1
        sc.con.rollback()
        assert writeback._powod_juz_cofnietego(sc.con, b2) is writeback._JUZ_RODOWODEM
    finally:
        sc.con.close()


# ============================================================ AR-422: cofnięcie zmiany obiektu po łańcuchu cofnięć kart


def _plik_obiektu(tmp_path):
    d = tmp_path / "LIGHTS" / "Sh2-229" / "RC8"
    d.mkdir(parents=True)
    p = d / "a.fits"
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16) + 1)
    for k, v in (("IMAGETYP", "Light"), ("OBJECT", "Sh2-229"), ("TELESCOP", "RC8"), ("DATE-OBS", "2024-03-15T21:30:45")):
        hdu.header[k] = v
    hdu.writeto(str(p))
    return p


def _karta_object(con, run_id, location_id, wartosc):
    naglowek = con.execute("SELECT header_hash FROM location WHERE id = ?", (location_id,)).fetchone()[0]
    repo.stage_pending(con, run_id=run_id, location_id=location_id, keyword="OBJECT", idx=0, op="set",
                       old_value=None, new_value=wartosc, new_type="str", new_comment=None,
                       expected_header_hash=naglowek)


def _zmiana_obiektu_po_zapisie_kart(tmp_path, monkeypatch, aba):
    """C1 (R1) zapisuje kartę `OBJECT` `IC 405`; zmiana obiektu O zapisuje `Sh2-229` (ABA - nagłówek wraca do stanu
    sprzed C1) albo `M 42`, drogą ATOMOWĄ (zapis w miejscu odbity `Fallback` - cofnięcie atomowe nie ma dowodu wprost
    fazy `synced`). Zwraca `(con, ścieżka, C1, commit O)`."""
    con = db.open_db(str(tmp_path / "h.db"))
    p = _plik_obiektu(tmp_path)
    _skan(con, p)
    lid = con.execute("SELECT id FROM location").fetchone()[0]
    _karta_object(con, "R1", lid, "IC 405")
    c1 = writeback.commit(con, "R1", now=NOW, inplace=False).commit_id
    w = con.execute("SELECT * FROM location").fetchone()
    nowa = "Sh2-229" if aba else "M 42"
    item = oc.ObjectChangeItem(frame_id=w["frame_id"], location_id=w["id"], old_path=str(p), new_path=None, mkdirs=(),
                               card_op="set", card_old="IC 405", card_new=nowa, expected_header_hash=w["header_hash"],
                               expected_mtime=w["mtime"], expected_object=(None, None, None), object_change=True)
    cel = oc.ObjectTarget(canon="Sh2-229" if aba else "M42", catalog="Sh2" if aba else "M", kind="deep_sky",
                          alias_norm=None, card_form=nowa)
    repo.stage_object_change(con, plan=oc.ObjectChangePlan(run_id="O", target=cel, items=(item,), skipped=()), now=NOW)
    with monkeypatch.context() as m:
        m.setattr(writeback, "write_changes_inplace",
                  lambda *a, **kw: writeback.Fallback(PowodPozycji("droga atomowa w teście", "fb_no_room")))
        assert len(writeback.commit_object_change(con, "O", now=NOW).applied) == 1
    co = con.execute("SELECT max(id) FROM commits WHERE run_id = 'O'").fetchone()[0]
    assert con.execute("SELECT count(*) FROM inplace_op WHERE commit_id = ?", (co,)).fetchone()[0] == 0
    return con, p, c1, co


@pytest.mark.parametrize("aba", [True, False], ids=["aba", "bez_aba"])
def test_okno_zmiany_obiektu_po_lancuchu_cofniec_kart(tmp_path, monkeypatch, aba):
    """Zapis kart C1, zmiana obiektu O (atomowo), CLI `header-fix --undo` cofa O, potem C1 - plik w stanie sprzed C1.
    „Cofnij” okna zmiany obiektu: karta O „już cofnięta” regułą klasy - plik bez zmiany bajtu, przebieg `undone`.
    Falsyfikator: `_cofnij_pozycje` bez predykatu reguły - ABA: plik dostaje `IC 405` (cofnięty wynik C1); bez ABA:
    karta odmawia (`undo_card`), przebieg zostaje `undoing`."""
    con, p, c1, co = _zmiana_obiektu_po_zapisie_kart(tmp_path, monkeypatch, aba)
    try:
        assert writeback.undo(con, co, now=NOW).complete
        assert writeback.undo(con, c1, now=NOW).complete
        przed = p.read_bytes()
        wynik = writeback.undo_object_change(con, "O", now=NOW)
        assert len(wynik.applied) == 1 and not wynik.blocked and not wynik.failed, wynik
        assert p.read_bytes() == przed and fits.getheader(str(p))["OBJECT"] == "Sh2-229"
        assert con.execute("SELECT status FROM object_change_run WHERE run_id = 'O'").fetchone()[0] == "undone"
    finally:
        con.close()


def test_okno_zmiany_obiektu_wynik_z_zewnatrz_bez_skanu_cofa_karte(tmp_path, monkeypatch):
    """Scena `bez_aba` testu wyżej, ale po cofnięciach kart bajty wyniku zmiany obiektu (`M 42`) wracają spoza Horreum
    z nowym `mtime`, BEZ skanu - baza dalej opisuje stan sprzed C1. „Cofnij” okna nie domyka pozycji skrótem „już
    cofnięte” (reguła klasy czyta wyłącznie bazę): ciało cofnięcia czyta plik i karta wraca do wyniku C1 (`IC 405`), bez
    powodu „już cofnięte”. Falsyfikator: `_cofnij_pozycje` z predykatem reguły bez kontroli `mtime` pliku (pozycja
    domknięta skrótem, plik zostaje `M 42`)."""
    con, p, c1, co = _zmiana_obiektu_po_zapisie_kart(tmp_path, monkeypatch, False)
    try:
        po_o = p.read_bytes()
        assert writeback.undo(con, co, now=NOW).complete
        assert writeback.undo(con, c1, now=NOW).complete
        _bajty_z_zewnatrz_bez_skanu(p, po_o)
        wynik = writeback.undo_object_change(con, "O", now=NOW)
        assert len(wynik.applied) == 1 and not wynik.blocked and not wynik.failed, wynik
        assert fits.getheader(str(p))["OBJECT"] == "IC 405"
        kody = {getattr(fr.reason, "code", None) for fr in wynik.applied}
        assert not kody & {"undo_already_lineage", "undo_already_chain"}, wynik
        assert con.execute("SELECT status FROM object_change_run WHERE run_id = 'O'").fetchone()[0] == "undone"
    finally:
        con.close()


def test_okno_zmiany_obiektu_bez_cofniec_kart_cofa_karte(tmp_path, monkeypatch):
    """Ta sama scena bez cofnięć kart: „Cofnij” okna cofa kartę O jak dotąd (plik wraca do `IC 405`). Falsyfikator:
    predykat, który pomija backup żywego zapisu."""
    con, p, _c1, _co = _zmiana_obiektu_po_zapisie_kart(tmp_path, monkeypatch, True)
    try:
        wynik = writeback.undo_object_change(con, "O", now=NOW)
        assert len(wynik.applied) == 1, wynik
        assert fits.getheader(str(p))["OBJECT"] == "IC 405"
    finally:
        con.close()


# ============================================================ AR-423: kotwica wyniku zapisu odzyskanego


def _odzysk_z_wynikiem_z_zewnatrz(tmp_path, monkeypatch, obcy=None):
    """Zapis w miejscu nieweryfikowany (region zapisany cały), odzysk - plik sprzed zapisu; potem bajty wyniku zapisu
    z zewnątrz (`obcy(bajty)` - zmienione) i skan. Zwraca `(con, ścieżka, bajty sprzed zapisu, bajty wyniku, commit)`."""
    con, p, przed = _jeden_zapis(tmp_path, "nieweryfikowany", monkeypatch)
    wynik = p.read_bytes()
    op = con.execute("SELECT id, commit_id FROM inplace_op WHERE kind = 'commit'").fetchone()
    assert writeback.recover_torn(con, op["id"], now=NOW).status == "restored" and p.read_bytes() == przed
    _z_zewnatrz(con, p, bajty=wynik if obcy is None else obcy(wynik))
    return con, p, przed, wynik, op["commit_id"]


def _tymczasowe(katalog):
    return sorted(x.name for x in katalog.rglob("*.tmp"))


def _odzysk_formatu(tmp_path, monkeypatch, fmt):
    """FITS z drugim HDU albo XISF z drugim obrazem: zapis karty `OBJECT` w miejscu nieweryfikowany (region zapisany
    cały), odzysk - plik sprzed zapisu. Zwraca `(con, ścieżka, bajty sprzed, bajty wyniku, offset bajtu poza obrazem
    nagłówka, commit)`."""
    p, drugi = (_fits_dwa_hdu if fmt == "fits" else _xisf_dwa_obrazy)(tmp_path / f"o.{fmt}")
    przed = p.read_bytes()
    con, _loc = _baza_z_plikiem(tmp_path, p)
    prawdziwa = writeback._verify_inplace

    def _rozjazd(plan, size, probka, backup_text):
        prawdziwa(plan, size, probka, backup_text)
        return writeback.WriteResult("failed", PowodPozycji("rozjazd odczytu", "inplace_verify_mismatch"),
                                     plan.post_hash, backup_text, in_place=True)
    with monkeypatch.context() as m:
        m.setattr(writeback, "_verify_inplace", _rozjazd)
        writeback.commit(con, "R", now=NOW, inplace=True)
    wynik = p.read_bytes()
    op = con.execute("SELECT id, commit_id FROM inplace_op WHERE kind = 'commit'").fetchone()
    assert writeback.recover_torn(con, op["id"], now=NOW).status == "restored" and p.read_bytes() == przed
    return con, p, przed, wynik, drugi, op["commit_id"]


@pytest.mark.parametrize("wariant", ["dokladny", "obcy"])
@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_ar423_odzysk_z_wynikiem_z_zewnatrz(tmp_path, monkeypatch, fmt, wariant):
    """Zapis w miejscu odzyskany, potem z zewnątrz plik z nagłówkiem wyniku i skan - FITS (drugie HDU) i XISF
    (drugi obraz):
      * `dokladny` - bajty wyniku zapisu: klasa `niepewny` (dawniej `poza` - bez „Cofnij”), zakres liczy plik „do
        sprawdzenia”, cofnięcie przywraca plik sprzed zapisu bajt w bajt - kotwica dowiedziona pod blokadą pisarza, więc
        bez noty `undo_bytes_unverified`;
      * `obcy` - inny bajt drugiego HDU / drugiego obrazu (ten sam obraz nagłówka): odmowa `undo_result_unproven`, plik
        bez zmiany bajtu, bez pliku tymczasowego obok.
    Falsyfikatory: klasa odzysku zawsze `poza`; bajtowość liczona bez kotwicy; pisarz bez kotwicy (nagłówek obcego
    pliku przepisany); sha1 części planu XISF liczony jak FITS."""
    con, p, przed, wynik, drugi, cid = _odzysk_formatu(tmp_path, monkeypatch, fmt)
    try:
        bajty = bytearray(wynik)
        if wariant == "obcy":
            bajty[drugi + 10] ^= 0x01
        _z_zewnatrz(con, p, bajty=bytes(bajty))
        zakres = writeback.przebieg_do_cofniecia(con, "R")
        assert zakres == writeback.ZakresCofniecia((cid,), 0, 1, 0), zakres
        u = writeback.undo(con, cid, now=NOW)
        if wariant == "dokladny":
            assert u.complete and len(u.restored) == 1 and u.restored[0].reason is None, u
            assert p.read_bytes() == przed
        else:
            assert [fr.reason.code for fr in u.blocked] == ["undo_result_unproven"] and not u.complete, u
            assert p.read_bytes() == bytes(bajty) and _tymczasowe(tmp_path) == []
    finally:
        con.close()


def test_ar423_podmiana_miedzy_proba_a_pisarzem(tmp_path, monkeypatch):
    """Wynik zapisu odzyskanego wrócił z zewnątrz bajt w bajt (baza go opisuje), a tuż przed wejściem do pisarza
    (`write_full_header`) inny program podmienia plik na obcy z tym samym nagłówkiem: dowód kotwicy liczony z uchwytu
    pod blokadą pisarza - odmowa `undo_result_unproven`, bajty obcego pliku bez zmian. Falsyfikator: dowód kotwicy
    przed wywołaniem pisarza (plik otwierany od nowa - obcy plik dostaje nagłówek)."""
    con, p, _przed, wynik, cid = _odzysk_z_wynikiem_z_zewnatrz(tmp_path, monkeypatch)
    obcy = wynik[:-1] + bytes([wynik[-1] ^ 0x01])
    prawdziwy = writeback.write_full_header

    def _podmiana(path, *a, **kw):
        p.write_bytes(obcy)
        return prawdziwy(path, *a, **kw)
    try:
        monkeypatch.setattr(writeback, "write_full_header", _podmiana)
        u = writeback.undo(con, cid, now=NOW)
        monkeypatch.undo()
        assert [fr.reason.code for fr in u.blocked] == ["undo_result_unproven"], u
        assert p.read_bytes() == obcy
    finally:
        con.close()


def test_ar423_bez_kotwicy_odmowa_bez_pisarza(tmp_path, monkeypatch):
    """Operacja odzyskana bez kotwicy (`anchor_sha1` pusty, koperta bez sha1 pliku - emulacja zapisu sprzed kotwicy):
    dowodu nie będzie - odmowa `undo_result_unproven` bez wołania pisarza, plik bez zmian. Falsyfikator: pisarz bez
    kontroli przy braku kotwicy."""
    con, p, _przed, wynik, cid = _odzysk_z_wynikiem_z_zewnatrz(tmp_path, monkeypatch)
    try:
        con.execute("UPDATE inplace_op SET anchor_sha1 = NULL WHERE kind = 'commit'")
        con.commit()
        [b] = writeback.backups_for_commit(con, cid)
        assert writeback.RegionBackup.decode(b["header_text"]).file_sha1 is None
        def _pisarz(*a, **kw):
            raise AssertionError("pisarz wołany mimo braku kotwicy wyniku")
        monkeypatch.setattr(writeback, "write_full_header", _pisarz)
        u = writeback.undo(con, cid, now=NOW)
        monkeypatch.undo()
        assert [fr.reason.code for fr in u.blocked] == ["undo_result_unproven"], u
        assert p.read_bytes() == wynik
    finally:
        con.close()


def _zapis_w_miejscu(tmp_path, fmt):
    """FITS albo XISF z załącznikiem, zapis karty `OBJECT` w miejscu (operacja `synced`). Zwraca `(ścieżka, bajty
    sprzed, bajty wyniku, backup, kotwica operacji)`."""
    p = tmp_path / ("w.fits" if fmt == "fits" else "w.xisf")
    _fits(str(p)) if fmt == "fits" else _xisf(str(p))
    przed = p.read_bytes()
    con, _loc = _baza_z_plikiem(tmp_path, p)
    try:
        assert writeback.commit(con, "R", now=NOW, inplace=True).applied
        [b] = writeback.backups_for_commit(con, 1)
        kotwica = con.execute("SELECT anchor_sha1 FROM inplace_op WHERE kind = 'commit'").fetchone()[0]
        return p, przed, p.read_bytes(), dict(b), kotwica
    finally:
        con.close()


@pytest.mark.parametrize("kotwica", ["dobra", "zla", "brak"])
@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_write_full_header_kotwica_wyniku(tmp_path, fmt, kotwica):
    """Pisarz cofnięcia z kotwicą wyniku (FITS: trzy części planu, XISF z załącznikiem: region + ogon od załącznika):
    kotwica = sha1 pliku sprzed zapisu → plik wraca bajt w bajt (`byte_exact`); kotwica obca → 'blocked'
    `undo_result_unproven`, plik bez zmian, bez pliku tymczasowego; bez kotwicy - jak dotąd (przywrócenie). Falsyfikatory:
    sha1 części liczony inaczej niż plik tymczasowy; kontrola po złożeniu bez sprzątnięcia; kotwica ignorowana."""
    p, przed, wynik, b, kotwica_op = _zapis_w_miejscu(tmp_path, fmt)
    assert kotwica_op == hashlib.sha1(przed).hexdigest()
    k = {"dobra": kotwica_op, "zla": "0" * 40, "brak": None}[kotwica]
    res = writeback.write_full_header(str(p), b["header_text"], b["post_hash"], kotwica_wyniku=k)
    if kotwica == "zla":
        assert (res.status, res.reason.code) == ("blocked", "undo_result_unproven"), res
        assert p.read_bytes() == wynik and _tymczasowe(tmp_path) == []
    else:
        assert res.status == "applied", res
        assert p.read_bytes() == przed
        if kotwica == "dobra":
            assert res.byte_exact is True


def test_write_full_header_kotwica_przy_ukladzie_niezgodnym(tmp_path):
    """Kotwica wyniku i koperta, której układ nie pasuje do pliku (droga bajtowa niemożliwa): 'blocked'
    `undo_region_changed`, plik bez zmian. Falsyfikator: droga semantyczna mimo kotwicy (plik przepisany bez dowodu)."""
    p, _przed, wynik, b, kotwica_op = _zapis_w_miejscu(tmp_path, "fits")
    env = writeback.RegionBackup.decode(b["header_text"])
    przesunieta = dataclasses.replace(env, offset=env.offset + 2880).encode()
    res = writeback.write_full_header(str(p), przesunieta, b["post_hash"], kotwica_wyniku=kotwica_op)
    assert (res.status, res.reason.code) == ("blocked", "undo_region_changed"), res
    assert p.read_bytes() == wynik and _tymczasowe(tmp_path) == []


def test_write_full_header_kotwica_przy_backupie_tekstowym(tmp_path):
    """Kotwica wyniku i backup TEKSTOWY (bez koperty - nie ma regionu do podstawienia): dowodu nie będzie - 'blocked'
    `undo_result_unproven`, nie zdanie o regionie nagłówka; plik bez zmian. Falsyfikatory: `undo_region_changed` przy
    backupie bez regionu; droga semantyczna mimo kotwicy."""
    p, _przed, wynik, b, kotwica_op = _zapis_w_miejscu(tmp_path, "fits")
    tekst = writeback.RegionBackup.decode(b["header_text"]).header_text()
    assert writeback.RegionBackup.decode(tekst) is None
    res = writeback.write_full_header(str(p), tekst, b["post_hash"], kotwica_wyniku=kotwica_op)
    assert (res.status, res.reason.code) == ("blocked", "undo_result_unproven"), res
    assert p.read_bytes() == wynik and _tymczasowe(tmp_path) == []


def test_stan_rodowodu_w_faktach_lokacji_bez_historii(tmp_path):
    """Lokacja bez wierszy rodowodu (historia sprzed migracji 0048): stan None - reguła sprzed rodowodu (zapis
    atomowy potwierdzony `zatwierdzony`). Falsyfikator: brak wierszy czytany jako `cofniety` albo `zywy`."""
    con, (p,) = _baza(tmp_path, 1, "s")
    try:
        c1 = _zapis(con, "R1", "EQ6")
        con.execute("DELETE FROM location_state")
        con.commit()
        [b1] = writeback.backups_for_commit(con, c1)
        f, klasa = writeback._klasa_z_bazy(con, b1)
        assert (f.stan_rodowodu, klasa) == (None, "zatwierdzony") and _tel(p) == "EQ6"
    finally:
        con.close()
