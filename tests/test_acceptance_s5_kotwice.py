"""Pochodzenie kotwic bramki akceptacji (AR-53) i zakres doskanu FULL bez `STACKS` (O1).

Skrypt `scripts/acceptance_s5.py` chodzi na dawcy i realnym archiwum, więc tu testujemy wyłącznie
to, co da się sprawdzić bez `R:`: strukturę `Pomiar`/`Kotwica`, wydruk niezgodności (oczekiwana,
aktualna, pochodzenie, wiek kotwicy), wybór poddrzew doskanu i etap stosów (T) na syntetycznym
archiwum w `tmp_path`. Przebieg kryteriów na bazie
z importu pinuje `test_import_fitsmirror.py`.
"""
import importlib.util
import os
import re
from datetime import date

import pytest

DZIS = date(2026, 10, 5)


def _acceptance():
    """Moduł `scripts/acceptance_s5.py` (skrypt, nie pakiet) - ładowany z pliku."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "acceptance_s5.py")
    spec = importlib.util.spec_from_file_location("acceptance_s5_kotwice", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


acc = _acceptance()


def _kotwice():
    return {n: getattr(acc, n) for n in dir(acc) if n.startswith("EXP_")}


def test_kazda_kotwica_niesie_pochodzenie():
    """Każda `EXP_*` jest `Kotwica` z `Pomiar`: data ISO albo jawne „nieustalone" (None), nie
    z przyszłości, i niepuste pola przebiegu, stanu archiwum i kodu. Liczba bez pochodzenia to
    dokładnie to, co trzeba było rozbierać ręcznie po przebiegu FULL 2026-10-04."""
    kotwice = _kotwice()
    assert kotwice, "skrypt bez kotwic EXP_*"
    for nazwa, k in kotwice.items():
        assert isinstance(k, acc.Kotwica), nazwa
        for p in (k.pomiar, k.potwierdzenie):
            if p is None:
                continue
            assert isinstance(p, acc.Pomiar), nazwa
            assert p.przebieg and p.stan_r and p.kod, nazwa
            if p.dzien is not None:
                assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.dzien), nazwa
                # „nie z przyszłości" wobec dnia URUCHOMIENIA - stały `DZIS` odbijał każdą kotwicę
                # zmierzoną po dniu, w którym test napisano (pomiar EXIF 2026-10-06).
                assert date.fromisoformat(p.dzien) <= date.today(), nazwa
        if k.potwierdzenie is not None and k.pomiar.dzien and k.potwierdzenie.dzien:
            assert k.potwierdzenie.dzien >= k.pomiar.dzien, nazwa


def test_kotwice_pochodne_nie_dziedzicza_po_cichu():
    """Kotwice etapów, które kiedyś liczono z innych (`dict(IMPORT, …)`), są wypisane wprost -
    ponowny pomiar jednej nie może przestawić drugiej, której nikt nie mierzył."""
    assert acc.EXP_CAMERAS_FULL.wartosc is not acc.EXP_CAMERAS_IMPORT.wartosc
    assert acc.EXP_XISF_KINDS_STACKS.wartosc is not acc.EXP_XISF_KINDS.wartosc
    assert set(acc.EXP_CAMERAS_IMPORT.wartosc) < set(acc.EXP_CAMERAS_FULL.wartosc)
    assert acc.EXP_XISF_KINDS_STACKS.wartosc["master_light"] == acc.EXP_STACKS_INGESTED.wartosc


def test_opis_pomiaru_liczy_wiek_i_mowi_nieustalone():
    p = acc.Pomiar("2026-08-04", "FULL --live-db", "po kasacji", "9ac4c18")
    assert acc.opis_pomiaru(p, DZIS) == ("2026-08-04 (62 dni temu); przebieg: FULL --live-db; "
                                         "stan R: po kasacji; kod: 9ac4c18")
    bez_daty = acc.Pomiar(None, "nieustalone", "nieustalone", "wpisane w abc")
    assert acc.opis_pomiaru(bez_daty, DZIS).startswith("data nieustalona; ")


def test_wydruk_niezgodnosci_niesie_obie_wartosci_pochodzenie_i_potwierdzenie():
    zmierzona = acc.Pomiar("2026-08-01", "FULL", "po pilocie", "33a2a19")
    potwierdzona = acc.Pomiar("2026-08-04", "FULL: WSZYSTKO PASS", "po kasacji", "9ac4c18")
    k = acc.Kotwica(12, zmierzona, potwierdzona)
    linie = acc.opis_niezgodnosci(k, 16, DZIS)
    assert linie[0] == "oczekiwano == 12, aktualnie 16"
    assert linie[1].startswith("kotwica zmierzona: 2026-08-01 (65 dni temu); przebieg: FULL")
    assert linie[2].startswith("ostatnio potwierdzona: 2026-08-04 (62 dni temu)")
    # bez potwierdzenia - dwie linie, próg - relacja w pierwszej
    prog = acc.Kotwica(85.0, acc.Pomiar(None, "próg", "nie dotyczy", "70abc43"))
    linie = acc.opis_niezgodnosci(prog, 80.1, DZIS, ">=")
    assert linie == ["oczekiwano >= 85.0, aktualnie 80.1",
                     "kotwica zmierzona: data nieustalona; przebieg: próg; "
                     "stan R: nie dotyczy; kod: 70abc43"]


def test_wydruk_niezgodnosci_bez_znakow_lamiacych_konsole():
    """Wydruk idzie na konsolę cp1250/cp852: zero strzałek, ptaszków i pauz w tekście, który
    skrypt sam składa (treść pól `Pomiar` pochodzi z kodu i też jest pilnowana)."""
    for k in _kotwice().values():
        for linia in acc.opis_niezgodnosci(k, 0, DZIS):
            assert not set(linia) & set("→✓✗—–"), linia


# ── O1: doskan FULL bez `STACKS` ─────────────────────────────────────────────────────────────
def _drzewo(tmp_path, *katalogi):
    for k in katalogi:
        (tmp_path / k).mkdir(parents=True)
    return str(tmp_path)


def test_korzenie_doskanu_odcinaja_stacks_i_drzewa_robocze(tmp_path):
    root = _drzewo(tmp_path, "LIGHTS", "CALIBRATION", "Stacks", "_WBPP", "LIGHTS/M31")
    korzenie, odciete, robocze = acc.korzenie_doskanu(root)
    assert [os.path.basename(k) for k in korzenie] == ["CALIBRATION", "LIGHTS"]
    assert [os.path.basename(p) for p in odciete] == ["Stacks"]   # niewrażliwie na wielkość
    assert [os.path.basename(p) for p in robocze] == ["_WBPP"]    # do telemetrii `dirs_excluded`


def test_korzenie_doskanu_pomija_symlink_katalogu_jak_os_walk(tmp_path):
    """Skan korzenia (`os.walk(followlinks=False)`) nie schodzi do dowiązania symbolicznego
    katalogu - przebieg po poddrzewach też nie może (inaczej doskan wciągnąłby obce drzewo)."""
    obce = tmp_path / "obce"
    (obce / "M31").mkdir(parents=True)
    root = tmp_path / "archiwum"
    (root / "LIGHTS").mkdir(parents=True)
    try:
        os.symlink(str(obce), str(root / "LINK"), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("brak uprawnień do tworzenia symlinków na tej maszynie")
    korzenie, _odciete, _robocze = acc.korzenie_doskanu(str(root))
    assert [os.path.basename(k) for k in korzenie] == ["LIGHTS"]


def test_korzenie_doskanu_odmawia_pliku_pod_korzeniem(tmp_path):
    """Plik nagłówkonośny wprost pod korzeniem - przebieg po podkatalogach by go pominął."""
    root = _drzewo(tmp_path, "LIGHTS")
    (tmp_path / "zgubiony.FITS").write_bytes(b"")
    (tmp_path / "notatka.txt").write_bytes(b"")                    # nienagłówkowy - bez odmowy
    with pytest.raises(RuntimeError, match="wprost pod korzeniem"):
        acc.korzenie_doskanu(root)


def test_korzenie_doskanu_odmawia_stacks_w_podkatalogu(tmp_path):
    """`STACKS` jeden poziom niżej: skan korzenia nie nakłada tam sita pochodnych, a skan
    podkatalogu by nałożył - zakres przestałby być równoważny, więc odmowa zamiast cichej różnicy."""
    root = _drzewo(tmp_path, "LIGHTS/STACKS")
    with pytest.raises(RuntimeError, match="poza korzeniem doskanu"):
        acc.korzenie_doskanu(root)


# ── (T) etap stosów drogą produktu: zwykły `scan_tree` korzenia archiwum ────────────────────
def _archiwum_po_doskanie(tmp_path, monkeypatch, *, obcy_rodzaj=False):
    """Archiwum z jednym plikiem już zeskanowanym doskanem (O1) i `STACKS\\Obj\\Zestaw\\Filtr\\`
    ze stosem o nazwie kanonicznej i jego pochodną. Wolumin stały, żeby brama `mtime` działała."""
    from test_scan import NOW, _db, _stack
    monkeypatch.setattr(acc, "volume_serial", lambda _p: "VOL1")
    root = tmp_path / "ASTRO_"
    zestaw = root / "STACKS" / "CTB1" / "A140R_2600MM" / "Ha"
    zestaw.mkdir(parents=True)
    (root / "LIGHTS" / "CTB1").mkdir(parents=True)
    _stack(root / "LIGHTS" / "CTB1" / "CTB1_Ha_600s_0001.xisf", imagetyp="Light Frame", n=1)
    _stack(zestaw / "CTB1_2025-08-30_A140R_2600MM_Ha_600s_mono_ast.xisf", n=2)
    _stack(zestaw / "CTB1_2025-08-30_A140R_2600MM_Ha_600s_mono_ast_ABE.xisf", n=3)
    if obcy_rodzaj:
        _stack(zestaw / "CTB1_flat_Ha.xisf", imagetyp="Master Flat", n=4)
    con = _db(tmp_path)
    acc.doskan_xisf(con, str(root), NOW, lambda *_a: None)
    assert con.execute("SELECT count(*) FROM location").fetchone()[0] == 1   # STACKS odcięty
    return con, root, NOW


def test_etap_stosow_wciaga_tylko_stos_spod_STACKS(tmp_path, monkeypatch):
    """Stos o nazwie kanonicznej (nie `masterLight…`) wchodzi, pochodna odpada sitem, plik archiwum
    przeskakuje brama `mtime`; drugi przebieg nie dodaje klatki ani eventu."""
    con, root, now = _archiwum_po_doskanie(tmp_path, monkeypatch)
    e, idem = acc.doskan_stacks(con, str(root), str(root / "STACKS"), now, lambda *_a: None)
    assert (e.pod_stacks, e.candidates, e.derived_skipped, e.ingested, e.rejected, e.failed) \
        == (2, 1, 1, 1, 0, 0)
    assert [os.path.basename(p) for p in e.derived_paths] \
        == ["CTB1_2025-08-30_A140R_2600MM_Ha_600s_mono_ast_ABE.xisf"]
    assert idem is True
    kinds = [r[0] for r in con.execute("SELECT f.kind FROM location l JOIN frame f "
                                       "ON f.id = l.frame_id WHERE l.path LIKE '%STACKS%'")]
    assert kinds == ["master_light"]
    assert con.execute("SELECT count(*) FROM location").fetchone()[0] == 2
    con.close()


def test_etap_stosow_liczy_odrzucone_bez_rodzaju_stosu(tmp_path, monkeypatch):
    """Plik pod `STACKS`, który zeznaje inny rodzaj, zwykły skan wciąga (to droga produktu) -
    etap liczy go jako odrzucony z przykładem ścieżki, a nie jako stos."""
    con, root, now = _archiwum_po_doskanie(tmp_path, monkeypatch, obcy_rodzaj=True)
    e, idem = acc.doskan_stacks(con, str(root), str(root / "STACKS"), now, lambda *_a: None)
    assert (e.candidates, e.ingested, e.rejected) == (2, 1, 1)
    assert "CTB1_flat_Ha.xisf" in e.rejected_paths[0] and idem is True
    con.close()


def test_etap_stosow_odmawia_korzenia_innego_niz_STACKS(tmp_path, monkeypatch):
    """`--stacks-root` inny niż `<xisf-root>\\STACKS` przesunąłby sito pochodnych - twardy błąd.
    Wielkość liter nie gra roli (NTFS)."""
    con, root, now = _archiwum_po_doskanie(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="to nie <xisf-root>"):
        acc.doskan_stacks(con, str(root), str(root / "LIGHTS"), now, lambda *_a: None)
    e, _idem = acc.doskan_stacks(con, str(root), str(root / "stacks"), now, lambda *_a: None)
    assert e.ingested == 1
    con.close()


def test_etap_stosow_odmawia_nowej_lokacji_spoza_STACKS(tmp_path, monkeypatch):
    """Plik archiwum, który przybył po doskanie, wszedłby etapem stosów - liczby §5.13 mierzyłyby
    wtedy coś więcej niż `STACKS`, więc etap przerywa przebieg."""
    from test_scan import _stack
    con, root, now = _archiwum_po_doskanie(tmp_path, monkeypatch)
    _stack(root / "LIGHTS" / "CTB1" / "CTB1_Ha_600s_0002.xisf", imagetyp="Light Frame", n=9)
    with pytest.raises(RuntimeError, match="spoza"):
        acc.doskan_stacks(con, str(root), str(root / "STACKS"), now, lambda *_a: None)
    con.close()


def test_etap_stosow_odmawia_podmiany_tresci_pliku_archiwum(tmp_path, monkeypatch):
    """Plik archiwum przepisany INNYMI danymi pod tą samą ścieżką po doskanie nie daje nowej lokacji -
    skan przepina starą na nową klatkę. Etap ma to nazwać i wskazać plik, nie `STACKS`."""
    from test_scan import _stack
    con, root, now = _archiwum_po_doskanie(tmp_path, monkeypatch)
    plik = root / "LIGHTS" / "CTB1" / "CTB1_Ha_600s_0001.xisf"
    _stack(plik, imagetyp="Light Frame", n=9)
    st = plik.stat()
    os.utime(plik, (st.st_atime + 100, st.st_mtime + 100))   # brama `mtime` musi przepuścić odczyt
    with pytest.raises(RuntimeError, match="przepiął 1 znanych lokacji.*CTB1_Ha_600s_0001"):
        acc.doskan_stacks(con, str(root), str(root / "STACKS"), now, lambda *_a: None)
    con.close()
