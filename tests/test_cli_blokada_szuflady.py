"""Wyłączność szuflady poza GUI (AR-322): blokada `<baza>.szuflada.lock` modułu `horreum.blokada_szuflady`
w formacie `QLockFile`, pięć wejść CLI zapisu pod nią (migracja bazy dopiero pod blokadą; plan, zapis i pochodne
`header-fix` pod nią), zgodność z prawdziwym `QLockFile` w drugim procesie, wyścigi założenia i przejęcia, pad
procesu, przerwanie po założeniu pliku. Pliki syntetyczne w `tmp_path`; drugi proces - `subprocess` z limitem."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
if sys.platform != "win32":
    pytest.skip("blokada szuflady - Windows (CreateFileW, jak QLockFile)", allow_module_level=True)

import horreum
from horreum import blokada_szuflady, cli, db, writeback

from test_cli_rename import _seed

KORZEN = str(Path(horreum.__file__).resolve().parent.parent)   # podproces bierze `horreum` stąd (worktree mutantów)
LIMIT = 60

# Drugi proces trzyma prawdziwy `QLockFile` (jak okno z przebiegiem w szufladzie) do pliku-sygnału.
_TRZYMAJ_QT = r'''
import os, sys, time
from PySide6.QtCore import QLockFile
l = QLockFile(sys.argv[1]); l.setStaleLockTime(0)
assert l.tryLock(10000)
open(sys.argv[2], "w").write(str(os.getpid()))
k = time.monotonic() + 60
while not os.path.exists(sys.argv[3]) and time.monotonic() < k:
    time.sleep(0.02)
l.unlock()
'''

# Sprawdzacz Qt w drugim procesie (tak jak okno: `setStaleLockTime(0)`, `tryLock(0)`).
_SPRAWDZ_QT = r'''
import sys
from PySide6.QtCore import QLockFile
l = QLockFile(sys.argv[1]); l.setStaleLockTime(0)
ok = l.tryLock(0)
print(f"{ok}|{l.error().name}|{l.getLockInfo()[0] if l.getLockInfo() else ''}|{QLockFile(sys.argv[1]).isLocked()}")
if ok:
    l.unlock()
'''

# Drugi proces bierze blokadę modułem: bariera (czeka na plik startu), wynik do pliku, trzyma do sygnału,
# albo (`pad`) ginie z trzymaną blokadą.
_WEZ_MODULEM = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
from horreum import blokada_szuflady
baza, start, wynik, zwolnij, tryb = sys.argv[2:7]
k = time.monotonic() + 60
while start != "-" and not os.path.exists(start) and time.monotonic() < k:
    time.sleep(0.001)
try:
    b = blokada_szuflady.wez(baza)
except blokada_szuflady.SzufladaZajeta as z:
    open(wynik, "w").write(f"ZAJETA {z.pid}")
    sys.exit(0)
open(wynik, "w").write(f"OK {os.getpid()}")
if tryb == "pad":
    os._exit(0)
while not os.path.exists(zwolnij) and time.monotonic() < k:
    time.sleep(0.01)
b.zwolnij()
'''


def _czekaj_plik(p, s=30):
    koniec = time.monotonic() + s
    while not (os.path.exists(p) and open(p).read()) and time.monotonic() < koniec:
        time.sleep(0.01)
    return open(p).read()


def _sprawdz_qt(plik):
    w = subprocess.run([sys.executable, "-c", _SPRAWDZ_QT, plik], capture_output=True, text=True, timeout=LIMIT)
    ok, blad, pid, zablokowany = w.stdout.strip().split("|")
    return ok == "True", blad, pid, zablokowany == "True"


class _TrzymaQt:
    """Kontekst: drugi proces trzyma `QLockFile` na `<baza>.szuflada.lock`; `pid` - jego PID."""

    def __init__(self, tmp_path, baza):
        self.plik = blokada_szuflady.sciezka(str(baza))
        self.gotowe, self.zwolnij = tmp_path / "qt.gotowe", tmp_path / "qt.zwolnij"

    def __enter__(self):
        self.proces = subprocess.Popen([sys.executable, "-c", _TRZYMAJ_QT, self.plik, str(self.gotowe),
                                        str(self.zwolnij)])
        self.pid = int(_czekaj_plik(str(self.gotowe)))
        return self

    def __exit__(self, *_a):
        self.zwolnij.write_text("")
        try:
            self.proces.wait(timeout=LIMIT)
        except subprocess.TimeoutExpired:
            self.proces.kill()


def _stan_bazy(dbp):
    con = db.connect(str(dbp))
    try:
        return tuple(con.execute(q).fetchone()[0] for q in (
            "SELECT count(*) FROM event", "SELECT count(*) FROM pending_renames",
            "SELECT count(*) FROM pending_changes", "SELECT count(*) FROM commits",
            "SELECT count(*) FROM location WHERE path LIKE '%raw%'"))
    finally:
        con.close()


def test_format_blokady_bajt_w_bajt_jak_qlockfile(tmp_path):
    """Treść blokady modułu = treść prawdziwego `QLockFile` tego procesu (PID, nazwa obrazu, host, MachineGuid,
    pusta linia). Falsyfikator: inne źródło hosta albo nazwy (np. `gethostname().lower()`, `applicationName`)."""
    from PySide6.QtCore import QLockFile
    q = QLockFile(str(tmp_path / "q.db") + blokada_szuflady.PRZYROSTEK)
    q.setStaleLockTime(0)
    assert q.tryLock(0)
    try:
        wzor = open(q.fileName(), "rb").read()
    finally:
        q.unlock()
    b = blokada_szuflady.wez(str(tmp_path / "m.db"))
    try:
        assert open(b.plik, "rb").read() == wzor
    finally:
        b.zwolnij()
    assert not os.path.exists(b.plik)


def _wejscia(tmp_path, capsys):
    """(nazwa, argv, pliki do porównania bajtów, baza) dla pięciu wejść CLI zapisu - każde gotowe do zapisu."""
    from test_header_fix import _archiwum, _plan
    dbp, files = _seed(tmp_path / "r")
    hdb, master, light, osc = _archiwum(tmp_path / "h")
    assert cli.main(["header-fix", hdb]) == 0
    plan = _plan(capsys.readouterr().out)
    return [
        ("rename --apply", ["rename", str(dbp), "--apply"], files, dbp),
        ("rename --undo", ["rename", str(dbp), "--undo", "R"], files, dbp),
        ("header-fix --apply", ["header-fix", hdb, "--apply", "--plan", plan], [master, light, osc], hdb),
        ("header-fix --undo", ["header-fix", hdb, "--undo", "1"], [master, light, osc], hdb),
        ("object-change finish", ["object-change", "finish", str(dbp), "R"], files, dbp),
    ]


@pytest.mark.parametrize("nr", range(5))
def test_kazde_wejscie_cli_odmawia_przy_zywej_blokadzie_okna(tmp_path, capsys, nr):
    """Szufladę bazy trzyma okno (prawdziwy `QLockFile` w drugim procesie): każde z pięciu wejść CLI zapisu
    odmawia kodem 2 zdaniem z PID-em tamtego procesu (ASCII), bez żadnej zmiany - pliki bajt w bajt, dziennik
    zdarzeń, staging, commity i ścieżki bez zmian. Falsyfikator: wejście bez blokady (zapis mimo okna)."""
    (tmp_path / "r").mkdir()
    (tmp_path / "h").mkdir()
    nazwa, argv, pliki, baza = _wejscia(tmp_path, capsys)[nr]
    bajty = {Path(p): Path(p).read_bytes() for p in pliki}
    stan = _stan_bazy(baza)
    with _TrzymaQt(tmp_path, baza) as okno:
        kod = cli.main(argv)
        out = capsys.readouterr().out
        assert os.path.exists(okno.plik)
    assert kod == 2, (nazwa, out)
    assert "ODMOWA -- szuflade tej bazy prowadzi inny proces Horreum" in out and f"PID {okno.pid}" in out, out
    assert out.isascii(), out
    assert {p: p.read_bytes() for p in bajty} == bajty, nazwa
    assert _stan_bazy(baza) == stan, nazwa


def test_okno_czyta_blokade_cli_jako_cudza_a_po_poleceniu_jej_nie_ma(tmp_path, capsys, monkeypatch):
    """W biegu `rename --apply` prawdziwy `QLockFile` w drugim procesie odmawia (`LockFailedError`) i czyta PID
    polecenia; świeży obiekt `isLocked()` = False (własności nie przypisuje). Po poleceniu pliku blokady nie ma,
    a zmiana nazw zaszła. Falsyfikator: zwolnienie bez usunięcia pliku albo treść bez PID-u."""
    dbp, files = _seed(tmp_path)
    plik = blokada_szuflady.sciezka(str(dbp))
    widziane = []
    prawdziwe = writeback.commit_renames

    def _w_biegu(con, run_id, *, now, progress=None, should_cancel=None):
        widziane.append(_sprawdz_qt(plik))
        return prawdziwe(con, run_id, now=now, progress=progress, should_cancel=should_cancel)
    monkeypatch.setattr(writeback, "commit_renames", _w_biegu)
    assert cli.main(["rename", str(dbp), "--apply"]) == 0
    assert widziane == [(False, "LockFailedError", str(os.getpid()), False)], widziane
    assert not os.path.exists(plik)
    assert not any(f.exists() for f in files), "zmiana nazw nie zaszła"


def test_szuflada_nie_podejmuje_przebiegu_cli_w_biegu(tmp_path, capsys, monkeypatch):
    """Szew na prawdziwym rdzeniu: między plikami `rename --apply` (przebieg do podjęcia - dwa z trzech wpisów
    czekają) szuflada okna na drugim połączeniu NIE podejmuje go i mówi zdaniem cudzej szuflady; po końcu
    polecenia nie ma czego podejmować. Falsyfikator: polecenie bez blokady - okno podejmuje przebieg w biegu."""
    from PySide6.QtWidgets import QApplication
    from horreum.gui import grid as grid_mod
    from horreum.gui import i18n, queries
    QApplication.instance() or QApplication([])
    from test_gui_grid_szuflada import _baza_szuflady
    path, con, _p = _baza_szuflady(tmp_path, 3)
    con.close()
    con_b = db.connect(path)
    wyniki = []
    prawdziwe = writeback.commit_renames

    def _w_biegu(c, run_id, *, now, progress=None, should_cancel=None):
        def _po_pliku(done, total, p, status):
            if done == 1:
                v = grid_mod.FramesView(con_b, now_fn=lambda: "2026-07-03T14:00:00")
                try:
                    czeka = [x["n"] for x in queries.oczekujace_przebiegi_szuflady(con_b)]
                    v._podejmij_przebieg_poprzedni()
                    wyniki.append((czeka, v._rename_run_id, v.drawer.result.text()))
                finally:
                    v.close()
            if progress:
                progress(done, total, p, status)
        return prawdziwe(c, run_id, now=now, progress=_po_pliku, should_cancel=should_cancel)
    monkeypatch.setattr(writeback, "commit_renames", _w_biegu)
    try:
        assert cli.main(["rename", path, "--apply"]) == 0
        assert wyniki == [([2], None, i18n.t("grid.drawer.foreign_owner", pid=os.getpid()))], wyniki
        assert queries.oczekujace_przebiegi_szuflady(con_b) == []
    finally:
        con_b.close()


def _bierz_w_procesie(tmp_path, baza, nr, start="-", tryb="trzymaj"):
    wynik, zwolnij = tmp_path / f"w{nr}.txt", tmp_path / f"z{nr}.txt"
    p = subprocess.Popen([sys.executable, "-c", _WEZ_MODULEM, KORZEN, str(baza), str(start), str(wynik),
                          str(zwolnij), tryb])
    return p, wynik, zwolnij


@pytest.mark.parametrize("martwa", [False, True], ids=["wolna", "martwa_do_przejecia"])
def test_wyscig_dwoch_procesow_jeden_wchodzi_drugi_odmawia(tmp_path, martwa):
    """Dwa procesy biorą blokadę jednej bazy w tej samej chwili (bariera), 20 razy: dokładnie jeden wchodzi,
    drugi dostaje `SzufladaZajeta` z PID-em zwycięzcy, plik zwycięzcy bajt w bajt nietknięty do jego końca.
    Wariant `martwa`: pod barierą leży blokada martwego procesu - dwaj przejmujący (jeden usuwa, drugiemu
    `os.remove` mówi `FileNotFoundError` - „ktoś sprzątnął pierwszy”) dalej kończą się jednym zwycięzcą.
    Falsyfikator: przejęcie bez ponownej próby po `FileNotFoundError` albo bez odmowy przy trzymanej."""
    baza = tmp_path / "b.db"
    plik = blokada_szuflady.sciezka(str(baza))
    for i in range(20):
        if martwa:
            open(plik, "wb").write(b"999999\nmartwy\nINNY\n\n\n")
        start = tmp_path / f"start{i}"
        procesy = [_bierz_w_procesie(tmp_path, baza, f"{i}_{j}", start) for j in range(2)]
        time.sleep(0.3)
        start.write_text("")
        try:
            wyniki = [_czekaj_plik(str(w)) for _p, w, _z in procesy]
            ok = [w for w in wyniki if w.startswith("OK ")]
            assert len(ok) == 1, (i, wyniki)
            zwyciezca = ok[0].split()[1]
            assert [w for w in wyniki if w != ok[0]] == [f"ZAJETA {zwyciezca}"], (i, wyniki)
            assert open(plik, "rb").read().split(b"\n")[0] == zwyciezca.encode(), i
        finally:
            for _p, _w, z in procesy:
                z.write_text("")
            for p, _w, _z in procesy:
                p.wait(timeout=LIMIT)
        assert not os.path.exists(plik), i


def test_przejecie_martwej_gdy_ktos_sprzatnal_pierwszy(tmp_path, monkeypatch):
    """Martwa blokada pod bazą; w chwili naszego usuwania sprząta ją ktoś inny (plik znika, nasze `os.remove`
    dostaje `FileNotFoundError`), a nowej nie zakłada: to nadal „martwa usunięta” - ta sama jedna ponowna próba
    zakłada naszą. Wyścig z barierą trafia w to okno rzadko (zwycięzca zwykle zdąży założyć swoją), stąd wariant
    deterministyczny. Falsyfikator: `FileNotFoundError` traktowane jak blokada żywa (odmowa bez właściciela)."""
    baza = tmp_path / "b.db"
    plik = blokada_szuflady.sciezka(str(baza))
    open(plik, "wb").write(b"999999\nmartwy\nINNY\n\n\n")

    def _ubiegniety(p):
        os.remove(p)
        raise FileNotFoundError(2, "plik usunął inny sprzątający", p)
    monkeypatch.setattr(blokada_szuflady, "_usun", _ubiegniety)
    b = blokada_szuflady.wez(str(baza))
    monkeypatch.undo()
    try:
        assert open(plik, "rb").read().split(b"\n")[0] == str(os.getpid()).encode()
    finally:
        b.zwolnij()


def test_przejecie_po_zamknieciu_uchwytu_jest_ciche(tmp_path, monkeypatch):
    """Zwolnienie: między zamknięciem uchwytu a usunięciem pliku drugi proces przejmuje blokadę (plik już
    nietrzymany) i ją trzyma - nasze usunięcie dostaje WinError 32, a zwolnienie kończy się bez wyjątku;
    blokada drugiego procesu trwa (prawdziwy `QLockFile` odmawia z jego PID-em). Falsyfikator: sprzątanie
    bez wyciszenia WinError 32 (wynik polecenia zamieniony w błąd) albo usunięcie cudzej blokady."""
    baza = tmp_path / "b.db"
    b = blokada_szuflady.wez(str(baza))
    prawdziwe = blokada_szuflady._usun
    obcy = {}

    def _przejecie_w_oknie(plik):
        p, wynik, zwolnij = _bierz_w_procesie(tmp_path, baza, "obcy")
        obcy.update(p=p, wynik=wynik, zwolnij=zwolnij)
        assert _czekaj_plik(str(wynik)).startswith("OK ")
        prawdziwe(plik)
    monkeypatch.setattr(blokada_szuflady, "_usun", _przejecie_w_oknie)
    try:
        b.zwolnij()
        pid_obcego = open(str(obcy["wynik"])).read().split()[1]
        assert _sprawdz_qt(b.plik)[:3] == (False, "LockFailedError", pid_obcego)
    finally:
        if obcy:
            obcy["zwolnij"].write_text("")
            obcy["p"].wait(timeout=LIMIT)


def test_pad_procesu_zostawia_plik_ktory_okno_i_polecenie_przejmuja(tmp_path):
    """Proces z blokadą ginie (`os._exit`) - plik zostaje nietrzymany; prawdziwy `QLockFile` (okno) przejmuje go
    od razu (PID martwy), a po drugim padzie - następne `wez` modułu. Falsyfikator: reguła „plik istnieje =
    właściciel żyje” (szuflada stoi do ręcznego usunięcia)."""
    baza = tmp_path / "b.db"
    plik = blokada_szuflady.sciezka(str(baza))
    for nr, kto in enumerate(("okno", "polecenie")):
        p, wynik, _z = _bierz_w_procesie(tmp_path, baza, f"pad{nr}", tryb="pad")
        p.wait(timeout=LIMIT)
        assert _czekaj_plik(str(wynik)).startswith("OK ") and os.path.exists(plik), kto
        if kto == "okno":
            assert _sprawdz_qt(plik)[0] is True
        else:
            b = blokada_szuflady.wez(str(baza))
            assert open(plik, "rb").read().split(b"\n")[0] == str(os.getpid()).encode()
            b.zwolnij()
        assert not os.path.exists(plik), kto


def test_zly_wzor_nie_rekoncyliuje_i_nie_bierze_blokady(tmp_path, capsys, monkeypatch):
    """Zamiar renamu przerwany śmiercią procesu (`in_flight`) czeka na rekoncyliację; `rename --apply` ze złym
    regexem odmawia kodem 2, zamiar zostaje nietknięty, a blokady nikt nie brał - walidacja wzoru stoi przed
    blokadą i przed rekoncyliacją. Falsyfikator: walidacja z powrotem za `reconcile_renames`."""
    from horreum import repo
    dbp, _files = _seed(tmp_path)
    with monkeypatch.context() as m:
        m.setattr(repo, "_apply_relocation", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            cli.main(["rename", str(dbp), "--apply"])
    assert not os.path.exists(blokada_szuflady.sciezka(str(dbp))), "blokada zwolniona także przy przerwaniu"
    con = db.connect(str(dbp))
    przed = [tuple(r) for r in writeback.open_rename_intents(con)]
    con.close()
    assert przed, "zamiar nie został - test nic by nie mierzył"
    capsys.readouterr()
    wzieto = []
    monkeypatch.setattr(blokada_szuflady, "wez", lambda *a: wzieto.append(a) or (_ for _ in ()).throw(AssertionError))
    assert cli.main(["rename", str(dbp), "--apply", "--template-json", '[{"t": "orig", "re": "("}]']) == 2
    assert "błąd wzoru" in capsys.readouterr().out
    con = db.connect(str(dbp))
    assert [tuple(r) for r in writeback.open_rename_intents(con)] == przed
    con.close()
    assert wzieto == []


def _do_v46(baza):
    """Baza starszego wydania (schemat v46): bieżąca baza bez tabel z 0047 (`migration_log`) i 0048 (`location_state`
    z indeksami) - jedynych przyrostów tych migracji."""
    con = db.connect(str(baza))
    try:
        con.execute("DROP TABLE location_state")
        con.execute("DROP TABLE migration_log")
        con.execute("PRAGMA user_version = 46")
        con.commit()
    finally:
        con.close()


@pytest.mark.parametrize("nr", range(5))
def test_odmowa_przy_blokadzie_okna_nie_migruje_bazy(tmp_path, capsys, nr):
    """Baza w schemacie v46 (okno starszego wydania), szufladę trzyma okno (prawdziwy `QLockFile` w drugim
    procesie): każde z pięciu wejść CLI zapisu odmawia kodem 2 ze zdaniem „Zero zmian”, a baza zostaje w swojej
    wersji - `user_version` 46, tabeli `migration_log` brak, plik bazy bajt w bajt. Ta sama baza otwarta potem
    bez blokady migruje do bieżącej wersji (baza naprawdę wymagała migracji). Falsyfikator: `db.open_db`
    (migracja) przed blokadą szuflady."""
    (tmp_path / "r").mkdir()
    (tmp_path / "h").mkdir()
    nazwa, argv, _pliki, baza = _wejscia(tmp_path, capsys)[nr]
    _do_v46(baza)
    przed = Path(baza).read_bytes()
    with _TrzymaQt(tmp_path, baza) as okno:
        kod = cli.main(argv)
        out = capsys.readouterr().out
    assert kod == 2 and "Zero zmian" in out and f"PID {okno.pid}" in out, (nazwa, out)
    assert Path(baza).read_bytes() == przed, nazwa
    con = db.connect(str(baza))
    try:
        assert db._user_version(con) == 46, nazwa
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE name = 'migration_log'").fetchone()[0] == 0
    finally:
        con.close()
    con = db.open_db(str(baza))
    try:
        assert db._user_version(con) == db.SCHEMA_VERSION > 46
    finally:
        con.close()


def _header_fix_z_planem(tmp_path, capsys):
    from test_header_fix import _archiwum, _plan
    hdb, *_pliki = _archiwum(tmp_path)
    assert cli.main(["header-fix", hdb]) == 0
    return hdb, _plan(capsys.readouterr().out)


def test_header_fix_apply_czyta_stan_pod_blokada_a_odmowa_planu_ja_zwalnia(tmp_path, capsys, monkeypatch):
    """`header-fix --apply`: wiersze planu liczonego teraz (`_header_fix_rows`) czytane są już pod blokadą
    szuflady - drugi proces (prawdziwy `QLockFile`, jak okno) w tej chwili odmawia z PID-em polecenia, więc
    cudzy gest nie zmieni stanu między planem liczonym teraz, porównaniem z planem DRY i zapisem. Odmowa planu
    pod blokadą (plan z DRY inny niż liczony teraz - kod 1, zero zapisu) zwalnia ją: pliku blokady nie ma,
    a następny `--apply` z właściwym planem zapisuje. Falsyfikator: blokada wzięta po porównaniu z planem DRY."""
    import json
    hdb, plan = _header_fix_z_planem(tmp_path, capsys)
    plik = blokada_szuflady.sciezka(hdb)
    tresc = json.loads(Path(plan).read_text(encoding="utf-8"))
    assert len(tresc["items"]) >= 2, "plan z jedną kartą - odmowa planu nie miałaby czego ująć"
    tresc["items"] = tresc["items"][1:]
    inny = tmp_path / "plan_inny.json"
    inny.write_text(json.dumps(tresc), encoding="utf-8")
    widziane = []
    prawdziwe = cli._header_fix_rows

    def _wiersze(con, frame_ids=None):
        widziane.append(_sprawdz_qt(plik))
        return prawdziwe(con, frame_ids)
    monkeypatch.setattr(cli, "_header_fix_rows", _wiersze)
    pod_blokada = (False, "LockFailedError", str(os.getpid()), False)
    assert cli.main(["header-fix", hdb, "--apply", "--plan", str(inny)]) == 1
    assert "ODMOWA w calosci, zero zapisu" in capsys.readouterr().out
    assert widziane == [pod_blokada] and not os.path.exists(plik), widziane
    assert cli.main(["header-fix", hdb, "--apply", "--plan", plan]) == 0
    assert "zapisane" in capsys.readouterr().out
    assert widziane == [pod_blokada, pod_blokada] and not os.path.exists(plik), widziane


def test_pochodne_header_fix_po_zapisie_i_po_cofnieciu_biegna_pod_blokada(tmp_path, capsys, monkeypatch):
    """Łańcuch pochodnych `header-fix` po `--apply` i po `--undo` biegnie pod blokadą szuflady: drugi proces
    (prawdziwy `QLockFile`, jak okno) w trakcie `_pochodne` odmawia z PID-em polecenia - cudze cofnięcie albo
    zapis nie wejdą między zapis plików a utrwalenie przeliczonego kanonu. Po każdym poleceniu pliku blokady
    nie ma. Falsyfikator: zwolnienie blokady przed `_pochodne` (po zapisie albo po cofnięciu)."""
    import re
    hdb, plan = _header_fix_z_planem(tmp_path, capsys)
    plik = blokada_szuflady.sciezka(hdb)
    widziane = []
    prawdziwe = cli._pochodne

    def _pochodne(con, now, lines):
        widziane.append(_sprawdz_qt(plik))
        return prawdziwe(con, now, lines)
    monkeypatch.setattr(cli, "_pochodne", _pochodne)
    assert cli.main(["header-fix", hdb, "--apply", "--plan", plan]) == 0
    commit = re.search(r"--undo (\d+)", capsys.readouterr().out).group(1)
    assert not os.path.exists(plik)
    assert cli.main(["header-fix", hdb, "--undo", commit]) == 0
    assert "przywrocone" in capsys.readouterr().out and not os.path.exists(plik)
    assert widziane == [(False, "LockFailedError", str(os.getpid()), False)] * 2, widziane


def test_przerwanie_po_zalozeniu_pliku_sprzata_blokade(tmp_path, monkeypatch):
    """Przerwanie (`KeyboardInterrupt`) po założeniu pliku blokady, a przed oddaniem uchwytu (tu: w zapisie
    treści): uchwyt zamknięty, plik usunięty, przerwanie idzie dalej - pustej blokady, której okno
    z `setStaleLockTime(0)` nie uzna za martwą (bez PID-u), nie ma, a następne `wez` bierze od razu.
    Falsyfikator: sprzątanie wyłącznie przy porażce `WriteFile` (uchwyt bez sprzątania przy wyjątku)."""
    baza = tmp_path / "b.db"
    plik = blokada_szuflady.sciezka(str(baza))
    prawdziwy = blokada_szuflady._kernel32()
    zalozony = []

    class _PrzerwanieWZapisie:
        def __getattr__(self, nazwa):
            return getattr(prawdziwy, nazwa)

        def WriteFile(self, *_a):
            zalozony.append(os.path.exists(plik))
            raise KeyboardInterrupt
    monkeypatch.setattr(blokada_szuflady, "_kernel32", lambda: _PrzerwanieWZapisie())
    with pytest.raises(KeyboardInterrupt):
        blokada_szuflady.wez(str(baza))
    monkeypatch.undo()
    assert zalozony == [True], "przerwanie przed założeniem pliku - test nic by nie mierzył"
    assert not os.path.exists(plik)
    b = blokada_szuflady.wez(str(baza))
    try:
        assert open(plik, "rb").read().split(b"\n")[0] == str(os.getpid()).encode()
    finally:
        b.zwolnij()
    assert not os.path.exists(plik)


def test_przerwanie_w_sprawdzeniu_uchwytu_sprzata_blokade(tmp_path, monkeypatch):
    """Przerwanie (`KeyboardInterrupt`) zaraz po założeniu pliku blokady - w sprawdzeniu uchwytu, przed zapisem
    treści (atrapa uchwytu rzuca przy pierwszym porównaniu): uchwyt zamknięty, plik usunięty, przerwanie idzie
    dalej, następne `wez` bierze od razu. Falsyfikator: sprawdzenie uchwytu poza objęciem sprzątania."""
    baza = tmp_path / "b.db"
    plik = blokada_szuflady.sciezka(str(baza))
    prawdziwy = blokada_szuflady._kernel32()
    zalozony = []

    class _Uchwyt(int):
        przerwij = True

        def __eq__(self, inny):
            if _Uchwyt.przerwij:
                _Uchwyt.przerwij = False
                zalozony.append(os.path.exists(plik))
                raise KeyboardInterrupt
            return int.__eq__(self, inny)
        __hash__ = int.__hash__

    class _PrzerwanieWSprawdzeniu:
        def __getattr__(self, nazwa):
            return getattr(prawdziwy, nazwa)

        def CreateFileW(self, *a):
            return _Uchwyt(prawdziwy.CreateFileW(*a))
    monkeypatch.setattr(blokada_szuflady, "_kernel32", lambda: _PrzerwanieWSprawdzeniu())
    with pytest.raises(KeyboardInterrupt):
        blokada_szuflady.wez(str(baza))
    monkeypatch.undo()
    assert zalozony == [True], "przerwanie przed założeniem pliku - test nic by nie mierzył"
    assert not os.path.exists(plik)
    b = blokada_szuflady.wez(str(baza))
    try:
        assert open(plik, "rb").read().split(b"\n")[0] == str(os.getpid()).encode()
    finally:
        b.zwolnij()
    assert not os.path.exists(plik)


def _pliki_katalogu(katalog):
    return {str(p.relative_to(katalog)): p.read_bytes() for p in sorted(Path(katalog).rglob("*")) if p.is_file()}


def _tryb_dziennika(baza):
    import sqlite3
    con = sqlite3.connect(Path(baza).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return con.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        con.close()


@pytest.mark.parametrize("nr", range(5))
def test_odmowa_przy_blokadzie_okna_nie_zmienia_bazy_w_trybie_delete(tmp_path, capsys, nr):
    """Baza w trybie dziennika DELETE (nie WAL, jak ustawia `db.connect`), szufladę trzyma okno (prawdziwy
    `QLockFile` w drugim procesie): każde z pięciu wejść CLI zapisu odmawia kodem 2, a katalog bazy (plik bazy,
    pliki obok, blokada okna) jest bajt w bajt jak przed - ścieżkę bazy daje połączenie tylko do odczytu; tryb
    dziennika dalej `delete`. Falsyfikator: ścieżka bazy przez `db.connect` (zapis trybu WAL przed blokadą)."""
    import sqlite3
    (tmp_path / "r").mkdir()
    (tmp_path / "h").mkdir()
    nazwa, argv, _pliki, baza = _wejscia(tmp_path, capsys)[nr]
    con = sqlite3.connect(str(baza))
    assert con.execute("PRAGMA journal_mode = DELETE").fetchone()[0] == "delete"
    con.close()
    katalog = Path(baza).parent
    with _TrzymaQt(tmp_path, baza) as okno:
        przed = _pliki_katalogu(katalog)
        kod = cli.main(argv)
        out = capsys.readouterr().out
        po = _pliki_katalogu(katalog)
    assert kod == 2 and "Zero zmian" in out and f"PID {okno.pid}" in out, (nazwa, out)
    assert po == przed, (nazwa, set(po) ^ set(przed))
    assert _tryb_dziennika(baza) == "delete", nazwa


@pytest.mark.parametrize("wariant", ["wzgledna", "inna_wielkosc_liter"])
def test_sciezka_wzgledna_i_inna_wielkosc_liter_trafiaja_w_blokade_okna(tmp_path, capsys, monkeypatch, wariant):
    """Okno trzyma blokadę pod bezwzględną ścieżką bazy; `rename --apply` z tą samą bazą podaną ścieżką względną
    albo inną wielkością liter odmawia z PID-em okna (ten sam plik blokady). W drugą stronę: polecenie z tą ścieżką
    w biegu trzyma blokadę, którą prawdziwy `QLockFile` pod ścieżką bezwzględną widzi jako cudzą (PID polecenia),
    a po poleceniu pliku blokady nie ma. Falsyfikator: blokada pod surowym argumentem obok innego katalogu
    roboczego albo pod ścieżką, której okno nie trafi."""
    (tmp_path / "r").mkdir()
    dbp, files = _seed(tmp_path / "r")
    monkeypatch.chdir(dbp.parent)
    arg = dbp.name if wariant == "wzgledna" else str(dbp).swapcase()
    assert os.path.samefile(arg, dbp)
    with _TrzymaQt(tmp_path, dbp) as okno:
        kod = cli.main(["rename", arg, "--apply"])
        out = capsys.readouterr().out
    assert kod == 2 and f"PID {okno.pid}" in out, out
    plik = blokada_szuflady.sciezka(str(dbp))
    widziane = []
    prawdziwe = writeback.commit_renames

    def _w_biegu(con, run_id, *, now, progress=None, should_cancel=None):
        widziane.append(_sprawdz_qt(plik))
        return prawdziwe(con, run_id, now=now, progress=progress, should_cancel=should_cancel)
    monkeypatch.setattr(writeback, "commit_renames", _w_biegu)
    assert cli.main(["rename", arg, "--apply"]) == 0
    assert widziane == [(False, "LockFailedError", str(os.getpid()), False)], widziane
    assert not os.path.exists(plik) and not any(f.exists() for f in files)


def test_nieistniejaca_baza_powstaje_dopiero_pod_blokada(tmp_path, capsys, monkeypatch):
    """Ścieżka bazy, której jeszcze nie ma: polecenie zapisu idzie dalej drogą `db.open_db` (zakłada bazę - bez
    odmowy blokady), ale blokadę bierze ZANIM plik bazy powstanie, pod ścieżką bezwzględną; po poleceniu baza
    w bieżącym schemacie, pliku blokady nie ma. Falsyfikator: założenie pliku bazy przed blokadą."""
    baza = tmp_path / "nowa.db"
    prawdziwe = blokada_szuflady.wez
    widziane = []

    def _wez(db_path):
        widziane.append((db_path, os.path.exists(baza)))
        return prawdziwe(db_path)
    monkeypatch.setattr(blokada_szuflady, "wez", _wez)
    assert cli.main(["rename", str(baza), "--apply"]) == 0
    assert widziane == [(str(baza), False)], widziane
    con = db.connect(str(baza))
    try:
        assert db._user_version(con) == db.SCHEMA_VERSION
    finally:
        con.close()
    assert not os.path.exists(blokada_szuflady.sciezka(str(baza)))


def test_brak_katalogu_bazy_pada_bledem_bazy_przed_blokada(tmp_path, monkeypatch):
    """Katalog bazy nie istnieje: polecenie zapisu pada tym samym błędem SQLite, którym pada `db.open_db` (bazy nie
    da się założyć), zanim weźmie blokadę - nie zdaniem o blokadzie, której nie da się założyć. Falsyfikator:
    ścieżka zapasowa bez sprawdzenia katalogu (odmowa blokady zamiast błędu bazy)."""
    import sqlite3
    wzieto = []
    monkeypatch.setattr(blokada_szuflady, "wez", lambda *a: wzieto.append(a))
    with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
        cli.main(["rename", str(tmp_path / "nie_ma" / "x.db"), "--apply"])
    assert wzieto == [] and not (tmp_path / "nie_ma").exists()


def test_rename_apply_zamyka_baze_i_zwalnia_blokade_przy_wyjatku(tmp_path, capsys, monkeypatch):
    """Wyjątek w `rename --apply` po otwarciu bazy (w zapisie nazw): połączenie zamknięte - plik bazy da się od
    razu przenieść (na Windows otwarte połączenie go trzyma) - i blokada zwolniona, a wyjątek idzie dalej.
    Falsyfikator: zamknięcie połączenia poza `finally` (po zwolnieniu blokady)."""
    dbp, _files = _seed(tmp_path)

    def _pada(*_a, **_k):
        raise RuntimeError("awaria zapisu nazw")
    monkeypatch.setattr(writeback, "commit_renames", _pada)
    with pytest.raises(RuntimeError, match="awaria zapisu nazw") as blad:
        cli.main(["rename", str(dbp), "--apply"])
    assert not os.path.exists(blokada_szuflady.sciezka(str(dbp)))
    os.replace(dbp, dbp.with_name("przeniesiona.db"))       # ślad wyjątku (ramki) żyje do końca testu
    assert blad.value is not None


def test_sciezka_verbatim_bazy_trafia_w_blokade_okna(tmp_path):
    """Baza podana ścieżką verbatim (`\\\\?\\C:\\...`): ścieżka blokady pochodzi z połączenia tylko do odczytu
    (`PRAGMA database_list` - postać kanoniczna, jak w oknie), więc to ten sam plik blokady co dla zwykłej ścieżki,
    bez wyjątku i bez zapisu. Falsyfikator: ścieżka blokady z samego argumentu (`os.path.abspath` zostawia
    prefiks `\\\\?\\` - inny napis, brak wykluczenia z oknem)."""
    dbp, _files = _seed(tmp_path)
    verbatim = "\\\\?\\" + str(dbp)
    przed = dbp.read_bytes()
    assert os.path.abspath(verbatim) != os.path.abspath(str(dbp))       # przesłanka falsyfikatora
    assert cli._sciezka_bazy(verbatim) == cli._sciezka_bazy(str(dbp))
    assert dbp.read_bytes() == przed


def _goracy_wal_bez_shm(katalog):
    """Baza w trybie WAL z ramkami niezcheckpointowanymi w `-wal` i bez `-shm` - stan kopii przywróconej bez
    pliku pamięci dzielonej. Kopia plików bazy i `-wal` pisanej połączeniem z wyłączonym autocheckpointem."""
    import shutil
    (katalog / "zrodlo").mkdir()
    zrodlo = katalog / "zrodlo" / "h.db"
    con = db.connect(str(zrodlo))
    try:
        con.execute("PRAGMA wal_autocheckpoint = 0")
        con.execute("CREATE TABLE t (x)")
        con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(200)])
        con.commit()
        strona = con.execute("PRAGMA page_size").fetchone()[0]
        baza = katalog / "h.db"
        shutil.copyfile(zrodlo, baza)
        shutil.copyfile(f"{zrodlo}-wal", f"{baza}-wal")
    finally:
        con.close()
    # Nagłówek WAL (32 B) i co najmniej jedna pełna ramka (24 B nagłówka ramki + strona) - sam nagłówek to WAL pusty.
    assert os.path.getsize(f"{baza}-wal") >= 32 + 24 + strona and not os.path.exists(f"{baza}-shm")
    return baza


@pytest.mark.parametrize("stan", ["goracy_wal_bez_shm", "plik_nie_sqlite", "katalog_pod_sciezka"])
def test_sciezka_istniejacej_nieotwieralnej_bazy_bez_wyjatku_i_bez_zapisu(tmp_path, stan):
    """AR-342: baza, która ISTNIEJE, ale nie jest zwykłym plikiem SQLite gotowym do odczytu (gorący WAL bez `-shm`,
    plik nie-SQLite, katalog pod ścieżką bazy) - `_sciezka_bazy` oddaje bezwzględną ścieżkę bez wyjątku i bez zapisu:
    pliki katalogu bajt w bajt jak przed, `-shm` nie powstaje (decyzję o bazie podejmuje dopiero `db.open_db` pod
    blokadą). Falsyfikator: połączenie ścieżki z zapisem (`db.connect` - tryb WAL, checkpoint, `-shm`) albo wyjątek
    pierwszego zapytania poza strażą."""
    if stan == "goracy_wal_bez_shm":
        baza = _goracy_wal_bez_shm(tmp_path)
    elif stan == "plik_nie_sqlite":
        baza = tmp_path / "h.db"
        baza.write_bytes(b"to nie jest baza SQLite " * 64)
    else:
        baza = tmp_path / "h.db"
        baza.mkdir()
    przed = _pliki_katalogu(tmp_path)
    assert cli._sciezka_bazy(str(baza)) == os.path.abspath(baza)
    assert _pliki_katalogu(tmp_path) == przed
    assert not os.path.exists(f"{baza}-shm")
