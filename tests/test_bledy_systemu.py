"""Błąd systemu KLASĄ na każdej drodze plików poza pisarzem kart (AR-184, AR-183, P4-6): jeden
właściciel klasyfikacji (`item_reasons.powod_systemu`/`blad_systemu`) dla projekcji i kopii mastera,
żniw, wersji stosów, kopii wiodącej i planera zmiany obiektu.

Co pilnujemy: pisarz kart woła TEGO SAMEGO właściciela (alias, nie kopia); klasa po kodzie Windows,
kod spoza klas zostaje tekstem systemu; powód klasy nie dokleja ścieżki (ta stoi obok powodu -
w `dst`, w wierszu CLI, w zdaniu okna), a surowy tekst systemu jedzie w `detail`; zeznanie żniw
trzyma surowy tekst za zdaniem; zerwany udział w planerze to nie „katalog nie istnieje”. Ścieżki
syntetyczne (`X:\\L\\…`) i pliki w `tmp_path`."""
import json
import os

import pytest

from horreum import db, harvest, item_reasons, lead_copy, object_change, projection, scan, stack_variants
from horreum import writeback
from horreum.item_reasons import PowodPozycji, blad_systemu, powod_systemu

from test_harvest import NOW as NOW_ZNIW, _would_place, con  # noqa: F401 - fikstura `con`
from test_lead_copy import LATER, _loc, niezgodne  # noqa: F401 - fikstura `niezgodne`
from test_presence import tree  # noqa: F401 - fikstura `tree` (ogon `presence --apply`)
from test_projection import _lib, _master_dst
from test_stack_variants import _plan_sam, _po_zrodle, samodzielne  # noqa: F401 - fikstura


def _odmowa(*_a, **_k):
    raise OSError(None, "Odmowa dostępu.", r"X:\L\a.fits", 5)


# ============================================================ właściciel


def test_jeden_wlasciciel_klasy_bledu_systemu():
    """Pisarz kart woła właściciela pod dawnymi nazwami (aliasy importu), a publicznego aliasu
    `writeback.blad_systemu` już nie ma - wykonawca GUI bierze właściciela wprost. Falsyfikator:
    kopia funkcji w `writeback` (dwie tabele kodów rozjadą się po cichu)."""
    assert writeback._blad_systemu is item_reasons.blad_systemu
    assert writeback._szczegoly_systemu is item_reasons.szczegoly_systemu
    assert writeback._proza_z_diagnoza is item_reasons.proza_z_diagnoza
    assert not hasattr(writeback, "blad_systemu")
    assert not hasattr(writeback, "_OS_WINERROR") and not hasattr(writeback, "_OS_ERRNO")


@pytest.mark.parametrize("exc, kod", [
    (OSError(None, "x", None, 5), "os_denied"), (OSError(None, "x", None, 2), "os_missing"),
    (OSError(None, "x", None, 112), "os_no_space"), (OSError(None, "x", None, 64), "os_share_lost"),
    (OSError(None, "x", None, 53), "os_share_lost"), (OSError(28, "No space left"), "os_no_space"),
    (OSError(None, "zajęty", None, 32), None), (OSError(None, "x", None, 1117), None),
    (OSError(None, "istnieje", None, 183), None), (OSError("gołe"), None),
    (ValueError("nie system"), None)],
    ids=["5", "2", "112", "64", "53", "errno28", "32", "1117", "183", "gole", "ValueError"])
def test_powod_systemu_klasa_albo_nic(exc, kod):
    """`powod_systemu` oddaje WYŁĄCZNIE klasę (kod Windows przed errno); spoza klas - None, więc
    wołający z własną diagnozą jej nie traci. `blad_systemu` = klasa albo `Typ: opis` (AR-168).
    Falsyfikator: `powod_systemu` oddaje surowy tekst zamiast None."""
    powod = powod_systemu(exc)
    if kod is None:
        assert powod is None
        assert blad_systemu(exc) == f"{type(exc).__name__}: {exc}"
        assert blad_systemu(exc, z_typem=False) == str(exc)
    else:
        assert isinstance(powod, PowodPozycji) and powod.code == kod, powod
        assert dict(powod.params)["detail"] == f"{type(exc).__name__}: {exc}"
        assert blad_systemu(exc) == powod and blad_systemu(exc).code == kod


_ZDANIA_KLAS = {"os_denied": "odmowa dostępu do pliku ({})", "os_missing": "plik albo folder nie istnieje ({})",
                "os_no_space": "brak miejsca na dysku ({})",
                "os_share_lost": "udział sieciowy albo dysk nie odpowiada ({})"}
# JAWNA tabela każdego kodu klas (kopia wiedzy, nie odczyt `_OS_WINERROR`): kod Windows → klasa,
# a bez `winerror` - errno CRT → klasa.
_KODY_KLAS = ([(OSError(None, "Komunikat", r"X:\L\a.fits", w), k, f"WinError {w}") for w, k in (
    (5, "os_denied"), (19, "os_denied"), (65, "os_denied"), (2, "os_missing"), (3, "os_missing"),
    (112, "os_no_space"), (39, "os_no_space"), (21, "os_share_lost"), (51, "os_share_lost"),
    (53, "os_share_lost"), (54, "os_share_lost"), (55, "os_share_lost"), (59, "os_share_lost"),
    (64, "os_share_lost"), (67, "os_share_lost"), (121, "os_share_lost"), (240, "os_share_lost"),
    (1222, "os_share_lost"), (1231, "os_share_lost"), (1236, "os_share_lost"))]
    + [(OSError(e, "Komunikat"), k, f"Errno {e}") for e, k in (
        (13, "os_denied"), (1, "os_denied"), (2, "os_missing"), (28, "os_no_space"))])


@pytest.mark.parametrize("exc, kod, os_code", _KODY_KLAS, ids=[c for _e, _k, c in _KODY_KLAS])
@pytest.mark.parametrize("z_typem", [True, False])
def test_kazdy_kod_klasy_daje_kod_zdanie_numer_i_surowy_tekst(exc, kod, os_code, z_typem):
    """Każdy kod tabeli klas: kod powodu, zdanie PL z numerem, `os_code` i `detail` = surowy tekst
    systemu z typem - dla obu wartości `z_typem` (ten przełącznik dotyczy wyłącznie tekstu spoza
    klas). Falsyfikator: kod zdjęty z tabeli albo przypisany innej klasie."""
    powod = blad_systemu(exc, z_typem=z_typem)
    assert isinstance(powod, PowodPozycji) and powod.code == kod, (os_code, powod)
    assert str(powod) == _ZDANIA_KLAS[kod].format(os_code)
    assert dict(powod.params) == {"os_code": os_code, "detail": f"{type(exc).__name__}: {exc}"}


# ============================================================ projekcja i kopia mastera


def test_link_projekcji_mowi_klasa_bez_sciezki_a_szczegol_niesie_obie(tmp_path):
    """P4-6 + AR-184: prawdziwy `os.link` z brakującego źródła. Dawny powód `str(exc)` niósł
    `'źródło' -> 'cel'`, a CLI dokleja nazwę trzeci raz. Teraz zdanie klasy bez ścieżki, obie
    ścieżki w `detail`. Falsyfikator: przywrócony `f"{type(exc).__name__}: {exc}"`."""
    src, dst = str(tmp_path / "brak_zrodla.fits"), str(tmp_path / "_WBPP" / "NGC1" / "a_cel.fits")
    status, powod = projection._link_to(src, dst, do_apply=True, copy=False)
    assert status == "error" and powod.code == "os_missing", powod
    assert "brak_zrodla" not in powod and "a_cel" not in powod, powod
    szczegol = dict(powod.params)["detail"]
    assert szczegol.startswith("FileNotFoundError") and "brak_zrodla" in szczegol and "a_cel" in szczegol


def test_kopia_mastera_klasa_a_kod_spoza_klas_surowo(tmp_path):
    """Brak źródła (CRT: samo errno 2) → klasa `os_missing`; rodzic celu jest plikiem (WinError
    183, spoza klas) → tekst systemu jak dotąd. Falsyfikator: `copy_master` bez właściciela."""
    dst = _master_dst(tmp_path)
    status, powod = projection.copy_master(str(tmp_path / "brak.xisf"), dst, expected_sha1="x",
                                           library_root=_lib(tmp_path))
    assert status == "error" and powod.code == "os_missing" and dict(powod.params)["os_code"] == "Errno 2"
    src, dst = tmp_path / "wbpp" / "m.xisf", _master_dst(tmp_path / "b")
    src.parent.mkdir(parents=True)
    src.write_bytes(b"M" * 10)
    os.makedirs(os.path.dirname(os.path.dirname(dst)))
    open(os.path.dirname(dst), "wb").write(b"PLIK")
    status, powod = projection.copy_master(str(src), dst, expected_sha1="x",
                                           library_root=_lib(tmp_path / "b"))
    assert status == "error" and not isinstance(powod, PowodPozycji) and powod.startswith("FileExistsError")


@pytest.mark.parametrize("granica", ["open_part", "kopia", "fsync", "hasz", "utime", "publikacja"])
@pytest.mark.parametrize("kod_win", [64, 1117], ids=["klasa", "spoza_klas"])
def test_kopia_mastera_kazda_granica_io_ten_sam_status_inna_tylko_postac_powodu(tmp_path, monkeypatch,
                                                                                 granica, kod_win):
    """Awaria na każdej granicy I/O klingi kopii (otwarcie `.part`, kopiowanie, `fsync`, hasz, czasy,
    publikacja): status `error` jak dawniej, `.part` zdjęty, cel nietknięty - zmienia się wyłącznie
    postać powodu: klasa z kodem i dawnym tekstem w `detail` albo (kod spoza klas) dawny tekst znak
    w znak. Falsyfikator: gałąź `except OSError` bez `blad_systemu` → surowy tekst przy kodzie 64."""
    src = tmp_path / "wbpp" / "m.xisf"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"M" * 100)
    dst = _master_dst(tmp_path)
    exc = OSError(None, "Komunikat systemu", dst + projection.PART_SUFFIX, kod_win)

    def pada(*_a, **_k):
        raise exc
    sha1_fn = projection.hashing.sha1_of
    if granica == "open_part":
        prawdziwy = open

        def otwarcie(path, *a, **k):
            if str(path).endswith(projection.PART_SUFFIX):
                raise exc
            return prawdziwy(path, *a, **k)
        monkeypatch.setattr(projection, "open", otwarcie, raising=False)
    elif granica == "kopia":
        monkeypatch.setattr(projection.shutil, "copyfileobj", pada)
    elif granica == "fsync":
        monkeypatch.setattr(projection.os, "fsync", pada)
    elif granica == "hasz":
        sha1_fn = pada
    elif granica == "utime":
        monkeypatch.setattr(projection.os, "utime", pada)
    else:
        monkeypatch.setattr(projection.os, "rename", pada)
    status, powod = projection.copy_master(str(src), dst, expected_sha1=projection.hashing.sha1_of(str(src)),
                                           library_root=_lib(tmp_path), sha1_fn=sha1_fn)
    monkeypatch.undo()
    dawny = f"{type(exc).__name__}: {exc}"
    assert status == "error", (granica, status, powod)
    if kod_win == 64:
        assert powod.code == "os_share_lost" and dict(powod.params)["detail"] == dawny
    else:
        assert powod == dawny and not isinstance(powod, PowodPozycji)
    assert not os.path.exists(dst + projection.PART_SUFFIX) and not os.path.exists(dst)


def test_wersje_stosow_zwykle_apply_blad_odczytu_ten_sam_status_klasa_powodu(samodzielne):  # noqa: F811
    """Zwykłe `stack_variants.apply` (para wariant-oryginał): odczyt autocropu pada błędem systemu
    → wiersz `error` jak dawniej, powód klasą z dawnym tekstem w `detail`. Falsyfikator: gałąź
    `except OSError` w `apply` bez `blad_systemu`."""
    s = samodzielne
    plan = stack_variants.plan(s["con"], str(s["old"]), library_root=str(s["arch"]))
    assert [it for it in plan.items if it.applicable], [it.status for it in plan.items]
    exc = OSError(None, "Nazwa sieciowa jest już niedostępna", r"X:\L\a.xisf", 64)

    def pada(_path):
        raise exc
    wiersze = [w for w in stack_variants.apply(plan, con=s["con"], now="2026-10-16T00:00:00Z", read=pada)
               if w.status != "skipped"]
    assert wiersze and {w.status for w in wiersze} == {"error"}
    assert all(w.reason.code == "os_share_lost"
               and dict(w.reason.params)["detail"] == f"{type(exc).__name__}: {exc}" for w in wiersze)


# ============================================================ żniwa


def test_zniwa_kopia_i_zeznanie_klasa_a_zeznanie_trzyma_surowy_tekst(con, tmp_path, monkeypatch):  # noqa: F811
    """Błąd kopii (`copy` rzuca) → pozycja `error` z klasą; zeznanie `_ZNIWA_*.json` niesie zdanie
    i ZA NIM surowy tekst systemu (JSON podklasy `str` wziąłby samo zdanie). Błąd zapisu zeznania →
    `manifest_error` klasą. Falsyfikator: `_manifest_payload` bez `proza_z_diagnoza`."""
    p = _would_place(con, tmp_path)
    r = harvest.apply(p, now=NOW_ZNIW, copy=_odmowa)
    assert [it.status for it in r.items] == ["error", "error"]
    assert all(it.detail.code == "os_denied" for it in r.items), r.items
    with open(r.manifest_path, encoding="utf-8") as fh:
        zapis = json.load(fh)["items"][0]["detail"]
    assert zapis == ("odmowa dostępu do pliku (WinError 5) - PermissionError: [WinError 5] "
                     "Odmowa dostępu.: 'X:\\\\L\\\\a.fits'"), zapis

    def pelny(*_a, **_k):
        raise OSError(None, "Brak miejsca na dysku.", None, 112)
    monkeypatch.setattr(projection, "write_harvest_manifest", pelny)
    r = harvest.apply(_would_place(con, tmp_path / "2"), now=NOW_ZNIW)
    assert r.manifest_path is None and r.manifest_error.code == "os_no_space", r.manifest_error


@pytest.mark.parametrize("reason, detail", [
    ("seat_unreadable", "odmowa dostępu do pliku (WinError 5) - PermissionError: [WinError 5] x"),
    ("unreadable", {"inny": ["kształt", 1]}), (None, None)], ids=["klasa", "obcy_ksztalt", "puste"])
def test_stan_wydania_nie_zalezy_od_tekstu_powodu_w_zeznaniu(con, tmp_path, reason, detail):  # noqa: F811
    """Czytelnik zeznań żniw (`_release_state`, `_pending_stack`) nie czyta `reason` ani `detail`:
    dwa zeznania różniące się WYŁĄCZNIE tymi polami dają identyczny stan wydania (pending/done/
    review/awaiting/lineage) i identyczny stos do przyjęcia. Falsyfikator: czytelnik, który bierze
    `detail` (np. odrzuca pozycję z „odmową” w treści) - stan rozjeżdża się z wariantem `puste`."""
    from test_harvest import STOS_WBPP, TS, _lighty, _stos_po_dostawie, _wydanie_na_dysku, _wynik_wbpp
    root = _wydanie_na_dysku(tmp_path)
    _names, ids = _lighty(con, 2)
    a = _wynik_wbpp(root, STOS_WBPP)
    arch = tmp_path / "arch"
    kopia = arch / "STACKS" / "IC1795" / "76EDPH_2600MM" / "Ha" / "stos.xisf"
    kopia.parent.mkdir(parents=True)
    kopia.write_bytes(b"STOS")
    _stos_po_dostawie(con, "stos-a", str(kopia))
    pozycja = {"src": a, "kind": "master_light", "sha1_data": "stos-a", "status": "placed",
               "src_mtime_ns": os.stat(a).st_mtime_ns, "frame_ids": ids, "dst": str(kopia)}
    stany = []
    for poz in (pozycja, {**pozycja, "reason": reason, "detail": detail}):
        zeznanie = projection.write_harvest_manifest(str(root / "out"), {
            "ts": TS, "archive_root": str(arch), "items": [poz]}, now=TS)
        zeznania = harvest._harvest_testimonies(str(root / "out"))
        klucz = harvest._path_key(a)
        stany.append((harvest._release_state(str(root / "out"), None, archive_root=str(arch), con=con),
                      harvest._pending_stack(con, klucz, os.stat(a).st_mtime_ns, zeznania,
                                             str(arch / "STACKS"))))
        os.remove(zeznanie)
    assert stany[0] == stany[1]
    assert stany[0][0][1] == 1 and stany[0][1] is not None          # wciągnięty, stos czeka na rodowód


def test_zniwa_czytnik_klasa_a_parser_po_staremu(con, tmp_path):  # noqa: F811
    """Czytnik wyjścia WBPP pada zerwanym udziałem → `unreadable` z klasą (kod w oknie, szczegół
    w podpowiedzi); odmowa parsera mówi jak dotąd `ValueError: …` (diagnoza czytnika, nie system).
    Falsyfikator: `plan` bez `powod_systemu`."""
    from test_harvest import _one, _out
    _out(tmp_path)

    def zerwany(p):
        raise OSError(None, "Nazwa sieciowa jest już niedostępna", p, 64)
    it = _one(harvest.plan(con, str(tmp_path / "wbpp"), archive_root="A", read=zerwany))
    assert (it.status, it.reason) == ("review", "unreadable") and it.detail.code == "os_share_lost"

    def parser(_p):
        raise ValueError("nie XISF monolithic")
    it = _one(harvest.plan(con, str(tmp_path / "wbpp"), archive_root="A", read=parser))
    assert it.detail == "ValueError: nie XISF monolithic"


# ============================================================ wersje stosów (CLI)


def test_wersje_stosow_klasa_bledu_i_sciezka_raz(samodzielne, monkeypatch):  # noqa: F811
    """Każda droga błędu I/O planu i kopii wersji stosów mówi klasą: nagłówek autocropu
    (`plan`), odczyt samodzielnego (`plan_standalone`), hasz celu (`_standalone_targets` - cel raz,
    w `dst`), kopia samodzielnego (`apply_standalone`). Falsyfikator: `f"{dst}: {…}"` wraca."""
    s = samodzielne
    plan = stack_variants.plan(s["con"], str(s["old"]), library_root=str(s["arch"]), read_header=_odmowa)
    nieczytelne = [it for it in plan.items if it.status == "header_unreadable"]
    assert nieczytelne and all(it.detail.code == "os_denied" for it in nieczytelne)
    sam = _plan_sam(s)
    odczyt = stack_variants.plan_standalone(s["con"], str(s["old"]), [sam.items[0].src],
                                            library_root=str(s["arch"]), read=_odmowa).items[0]
    assert (odczyt.status, odczyt.reason) == ("standalone_conflict", "unreadable")
    assert odczyt.detail.code == "os_denied"
    with monkeypatch.context() as m:
        m.setattr(projection, "copy_stack_variant", _odmowa)
        wiersze = [w for w in stack_variants.apply_standalone(sam, con=s["con"]) if w.status == "error"]
    assert wiersze and all(w.reason.code == "os_denied" for w in wiersze)
    stack_variants.apply_standalone(_plan_sam(s), con=s["con"])        # cele leżą - hasz celu rusza
    g1 = _po_zrodle(_plan_sam(s))[s["src"]["G1"]]

    def hasz(path):
        if os.path.normcase(path) == os.path.normcase(g1.dst):
            raise OSError(None, "Nazwa sieciowa jest już niedostępna", path, 64)
        return stack_variants.hashing.sha1_of(path)
    it = _po_zrodle(stack_variants.plan_standalone(s["con"], str(s["old"]), [g1.src],
                                                   library_root=str(s["arch"]), sha1_fn=hasz))[g1.src]
    assert (it.status, it.reason) == ("standalone_conflict", "unreadable")
    assert it.detail.code == "os_share_lost" and it.dst == g1.dst and g1.dst not in it.detail


# ============================================================ pełne wyjście CLI (P4-6, cp1250)


@pytest.mark.parametrize("kod_win", [5, 1117], ids=["klasa", "spoza_klas"])
def test_cli_project_wiersz_bledu_sciezka_raz_i_cp1250(tmp_path, capsys, monkeypatch, kod_win):
    """`horreum project --apply`: link pada błędem systemu. Klasa: wiersz `ERROR` mówi nazwę pliku
    RAZ (dawny powód `str(exc)` niósł `'źródło' -> 'cel'`, nazwa trzy razy), zdanie z numerem; kod
    spoza klas: tekst systemu znak w znak (granica AR-168 - ścieżki z komunikatu systemu zostają).
    Całe wyjście koduje się w cp1250 (przekierowana konsola). Falsyfikator: `_link_to` bez właściciela."""
    from horreum import cli
    from test_cli_project import _seed
    dbp, files = _seed(tmp_path)
    exc = OSError(None, "Komunikat systemu", str(files[1]), kod_win, "X:\\cel\\raw1.fits")
    prawdziwy = os.link

    def link(src, dst, *a, **k):
        if os.path.basename(src) == "raw1.fits":
            raise exc
        return prawdziwy(src, dst, *a, **k)
    monkeypatch.setattr(projection.os, "link", link)
    root = tmp_path / "_WBPP" / "feed"
    assert cli.main(["project", str(dbp), "--root", str(root), "--apply"]) == 0
    out = capsys.readouterr().out
    out.encode("cp1250")
    (wiersz,) = [w for w in out.splitlines() if w.strip().startswith("ERROR")]
    if kod_win == 5:
        assert wiersz == "    ERROR raw1.fits: odmowa dostępu do pliku (WinError 5)", wiersz
        assert out.count("raw1.fits") == 1, out
    else:
        assert wiersz == f"    ERROR raw1.fits: {type(exc).__name__}: {exc}", wiersz


@pytest.mark.parametrize("kod_win", [5, 33], ids=["klasa", "spoza_klas"])
def test_cli_stack_versions_wiersz_bledu_sciezka_raz_i_cp1250(samodzielne, capsys, monkeypatch,  # noqa: F811
                                                              kod_win):
    """`horreum stack-versions --standalone LISTA --apply`: kopia pada błędem systemu. Klasa: każda
    ścieżka (źródło, cel) w wierszu RAZ, powód zdaniem z numerem; kod spoza klas: tekst systemu znak
    w znak. Wyjście koduje się w cp1250. Falsyfikator: `apply_standalone` bez właściciela."""
    from horreum import cli
    s = samodzielne
    g1 = _po_zrodle(_plan_sam(s))[s["src"]["G1"]]
    exc = OSError(None, "Komunikat systemu", g1.dst + projection.PART_SUFFIX, kod_win)

    def kopia(src, dst, **_k):
        if os.path.normcase(dst) == os.path.normcase(g1.dst):
            raise exc
        return "placed", None
    monkeypatch.setattr(projection, "copy_stack_variant", kopia)
    lista = s["tmp"] / "g1.tsv"
    lista.write_text(f"autocrop\n{g1.src}\n", encoding="utf-8")
    s["con"].close()
    assert cli.main(["stack-versions", str(s["old"]), s["db"], "--archive", str(s["arch"]),
                     "--standalone", str(lista), "--apply"]) == 1
    out = capsys.readouterr().out
    out.encode("cp1250")
    (wiersz,) = [w for w in out.splitlines() if w.strip().startswith("error:")]
    if kod_win == 5:
        assert wiersz == f"  error: {g1.src} -> {g1.dst} | odmowa dostępu do pliku (WinError 5)", wiersz
        assert wiersz.count(g1.src) == 1 and wiersz.count(g1.dst) == 1, wiersz
    else:
        assert wiersz.endswith(f"| {type(exc).__name__}: {exc}"), wiersz


# ============================================================ kopia wiodąca


def test_kopia_wiodaca_klasa_a_reszta_diagnoza_skanu_bez_sciezki(niezgodne, monkeypatch):  # noqa: F811
    """Odczyt kopii pada zerwanym udziałem → klasa z kodem; zajętość (32, spoza klas) zostaje
    diagnozą skanu BEZ ścieżki - zdanie okna już nazywa kopię (P4-6). Falsyfikator: `blad_systemu`
    zamiast `powod_systemu(...) or unreadable_reason_of(...)` → ścieżka w powodzie zajętości."""
    con, _root, _fid, _a, b = niezgodne
    lid = _loc(con, b)["id"]
    for kod, oczek in ((64, "os_share_lost"), (32, None)):
        exc = OSError(None, "Komunikat systemu", r"X:\L\B_CLS\m.xisf", kod)

        def pada(path, exc=exc, **_k):
            raise exc
        monkeypatch.setattr(scan, "scan_file", pada)
        wynik = lead_copy.adopt_lead_copy(con, location_id=lid, now=LATER)
        assert wynik.verdict == "failed"
        if oczek is None:
            assert wynik.reason == scan.unreadable_reason_of(exc) and "B_CLS" not in wynik.reason
        else:
            assert wynik.reason.code == oczek, wynik.reason


# ============================================================ planer zmiany obiektu (AR-183)


@pytest.mark.parametrize("kod_win, kod", [(53, "dir_share_lost"), (67, "dir_share_lost"),
                                          (64, "dir_share_lost"), (21, "dir_share_lost"),
                                          (5, "dir_denied"), (2, "dir_missing"), (3, "dir_missing"),
                                          (112, "dir_no_space"), (39, "dir_no_space"),
                                          (1117, "dir_unreadable"), (32, "dir_unreadable"),
                                          (33, "dir_unreadable")])
def test_planer_zerwany_udzial_to_nie_brak_katalogu(kod_win, kod):
    """AR-183: klasa katalogu celu po kodzie Windows, nie po podklasie wyjątku - 53/67 to
    `FileNotFoundError`, a katalog istnieje; 21 (dysk niegotowy) to `PermissionError`. Zerwany udział
    mówi własnym zdaniem z numerem, surowy tekst systemu w `detail`; kod spoza klas - jak dziś,
    tekstem systemu w zdaniu. Falsyfikator: klasyfikacja klasą wyjątku → 53 = `dir_missing`."""
    katalog = r"X:\L\NGC1\cam"

    def listdir(k):
        raise OSError(None, "Komunikat systemu", k, kod_win)
    dysk = object_change._Dysk(os.path.isdir, listdir)
    with pytest.raises(object_change._Odmowa) as odmowa:
        dysk.wpisy(katalog)
    zdanie, kod_odmowy, params = odmowa.value.wpis
    p = dict(params)
    assert kod_odmowy == kod and p["dir"] == katalog, (kod_odmowy, zdanie)
    exc = OSError(None, "Komunikat systemu", katalog, kod_win)
    if kod == "dir_unreadable":
        assert p["detail"] == str(exc) and zdanie == f"katalog celu nieczytelny ({katalog}): {exc}"
    else:
        assert p["detail"] == f"{type(exc).__name__}: {exc}"
    if kod == "dir_share_lost":
        assert p["os_code"] == f"WinError {kod_win}"
        assert zdanie == (f"udział sieciowy albo dysk nie odpowiada (WinError {kod_win}) - katalog "
                          f"celu: {katalog}")
    if kod == "dir_no_space":
        assert p["os_code"] == f"WinError {kod_win}"
        assert zdanie == f"brak miejsca na dysku (WinError {kod_win}) - katalog celu: {katalog}"


def test_planer_brak_miejsca_bez_winerror_i_drugi_odczyt_z_pamieci():
    """Brak miejsca z samego errno CRT (ENOSPC) to ta sama klasa `dir_no_space` z surowym tekstem
    w `detail` (dawniej zdanie klasy po polsku wpadało w parametr `detail` zdania „nieczytelny” -
    w UI EN polskie słowa, surowa diagnoza ginęła). Drugi odczyt tego samego katalogu bierze
    wyjątek z pamięci planera: ten sam powód, JEDNO wywołanie `listdir`."""
    import errno
    katalog, wolania = r"X:\L\NGC2\cam", []

    def listdir(k):
        wolania.append(k)
        raise OSError(errno.ENOSPC, "No space left on device")
    dysk = object_change._Dysk(os.path.isdir, listdir)
    wpisy = []
    for _ in range(2):
        with pytest.raises(object_change._Odmowa) as odmowa:
            dysk.wpisy(katalog)
        wpisy.append(odmowa.value.wpis)
    assert wpisy[0] == wpisy[1] and wolania == [katalog]
    zdanie, kod, params = wpisy[0]
    assert kod == "dir_no_space" and dict(params) == {
        "dir": katalog, "os_code": "Errno 28", "detail": "OSError: [Errno 28] No space left on device"}
    assert zdanie == f"brak miejsca na dysku (Errno 28) - katalog celu: {katalog}"


# ============================================================ AR-198: klasa błędu bazy, druki CLI

_ZERWANY = r"X:\L\a.fits"


def _zerwany_udzial(sciezka=_ZERWANY):
    return OSError(None, "Komunikat systemu", sciezka, 64)


def _prawdziwy_blad_sqlite(tmp_path, rodzaj):
    """PRAWDZIWY wyjątek SQLite (z `sqlite_errorcode`/`sqlite_errorname`) - sztuczny
    `OperationalError("database is locked")` kodu nie niesie i klasy nie dostaje."""
    import sqlite3

    def baza(nazwa, wierszy=50):
        p = str(tmp_path / nazwa)
        c = sqlite3.connect(p)
        c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        c.executemany("INSERT INTO t (v) VALUES (?)", [("x" * 500,)] * wierszy)
        c.commit()
        c.close()
        return p
    trzymane = []
    try:
        if rodzaj == "busy":
            p = baza("busy.db")
            a = sqlite3.connect(p)
            trzymane.append(a)
            a.execute("BEGIN EXCLUSIVE")
            b = sqlite3.connect(p, timeout=0)
            trzymane.append(b)
            b.execute("SELECT * FROM t").fetchall()
        elif rodzaj == "locked":
            c = sqlite3.connect(baza("locked.db"))
            trzymane.append(c)
            kursor = c.execute("SELECT * FROM t")     # otwarty odczyt trzyma tabelę (referencja!)
            kursor.fetchone()
            c.execute("DROP TABLE t")
        elif rodzaj == "cantopen":
            sqlite3.connect(str(tmp_path / "brak_katalogu" / "x.db")).execute("SELECT 1")
        elif rodzaj == "readonly":
            c = sqlite3.connect(f"file:{baza('ro.db')}?mode=ro", uri=True)
            trzymane.append(c)
            c.execute("INSERT INTO t (v) VALUES ('z')")
        elif rodzaj == "full":
            c = sqlite3.connect(baza("full.db", wierszy=1))
            trzymane.append(c)
            c.execute("PRAGMA max_page_count = 3")
            c.executemany("INSERT INTO t (v) VALUES (?)", [("x" * 4000,)] * 50)
        elif rodzaj == "notadb":
            p = tmp_path / "smieci.db"
            p.write_bytes(b"to nie jest baza" * 512)
            c = sqlite3.connect(str(p))
            trzymane.append(c)
            c.execute("SELECT * FROM sqlite_master").fetchall()
        elif rodzaj == "corrupt":
            p = baza("corrupt.db", wierszy=400)
            with open(p, "r+b") as fh:
                fh.seek(4096 * 3)
                fh.write(b"\xa5" * 4096 * 5)
            c = sqlite3.connect(p)
            trzymane.append(c)
            c.execute("SELECT * FROM t").fetchall()
        elif rodzaj == "zamkniete":
            c = sqlite3.connect(baza("closed.db"))
            c.close()
            c.execute("SELECT 1")
        elif rodzaj == "przerwane":
            c = sqlite3.connect(baza("int.db", wierszy=1))
            trzymane.append(c)
            c.set_progress_handler(lambda: 1, 1)
            c.execute("SELECT * FROM t").fetchall()
        elif rodzaj == "ograniczenie":
            c = sqlite3.connect(baza("con.db", wierszy=1))
            trzymane.append(c)
            c.execute("INSERT INTO t (id, v) VALUES (1, 'dup')")
    except sqlite3.Error as e:
        return e
    finally:
        for c in trzymane:
            c.close()
    raise AssertionError(f"brak błędu SQLite: {rodzaj}")


@pytest.mark.parametrize("rodzaj, kod, nazwa", [
    ("busy", "db_busy", "SQLITE_BUSY"), ("locked", "db_busy", "SQLITE_LOCKED"),
    ("cantopen", "db_unavailable", "SQLITE_CANTOPEN"), ("readonly", "db_unavailable", "SQLITE_READONLY"),
    ("full", "db_full", "SQLITE_FULL"), ("notadb", "db_damaged", "SQLITE_NOTADB"),
    ("corrupt", "db_damaged", "SQLITE_CORRUPT")])
def test_klasa_bazy_na_prawdziwych_bledach_SQLite(tmp_path, rodzaj, kod, nazwa):
    """AR-198: prawdziwy błąd SQLite (drugie połączenie przy blokadzie zapisu, baza poza zasięgiem,
    pełna, uszkodzona) to klasa bazy z nazwą błędu SQLite; surowy tekst w `detail`, za zdaniem
    w kolumnie prozowej. `blad_systemu` pyta obu właścicieli. Falsyfikator: `_DB_KLASY` bez kodu
    głównego - klasa przepada, wraca `OperationalError: …`."""
    exc = _prawdziwy_blad_sqlite(tmp_path, rodzaj)
    powod = blad_systemu(exc)
    assert isinstance(powod, PowodPozycji) and powod.code == kod, (rodzaj, powod)
    assert item_reasons.powod_bazy(exc) == powod and powod_systemu(exc) is None
    assert dict(powod.params) == {"db_code": nazwa, "detail": f"{type(exc).__name__}: {exc}"}
    assert nazwa in powod and str(exc) not in powod
    assert item_reasons.proza_z_diagnoza(powod) == f"{powod} - {type(exc).__name__}: {exc}"
    assert kod in item_reasons.SYSTEM_REASON_CODES


@pytest.mark.parametrize("rodzaj", ["zamkniete", "przerwane", "ograniczenie", "sztuczny"])
def test_poza_klasa_bazy_tekst_jak_dotad(tmp_path, rodzaj):
    """Operacja na zamkniętym połączeniu (cykl życia, bez kodu SQLite), przerwanie zapytania
    (anulowanie wątku tła) i ograniczenie (odmowa klingi bazy) nie są stanem bazy - tekst wyjątku
    jak dotąd; sztuczny `OperationalError` z testów (bez kodu) też. Falsyfikator: klasa dla
    każdego `OperationalError` - przerwanie dostaje zdanie „baza zablokowana”."""
    import sqlite3
    exc = (sqlite3.OperationalError("database is locked") if rodzaj == "sztuczny"
           else _prawdziwy_blad_sqlite(tmp_path, rodzaj))
    assert item_reasons.powod_bazy(exc) is None
    assert blad_systemu(exc) == f"{type(exc).__name__}: {exc}"
    assert blad_systemu(exc, z_typem=False) == str(exc)


def test_druk_presence_zerwany_udzial_klasa_kod_1(tmp_path, capsys, monkeypatch):
    """`presence`: zerwany udział (53 to `FileNotFoundError`) - wiersz `blad --` mówi klasą
    z surowym tekstem, kod 1 bez śladu stosu; wyjątek bez kodu systemu (sama proza) mówi swoim
    tekstem jak dotąd. Odmowa korzenia `canonize_root` niesie od AR-212 kod systemu i mówi klasą."""
    from horreum import cli, presence
    dbp = str(tmp_path / "p.db")
    db.open_db(dbp).close()
    for exc, oczekiwany in [
            (FileNotFoundError(None, "Komunikat systemu", r"X:\L", 53),
             "udział sieciowy albo dysk nie odpowiada (WinError 53) - FileNotFoundError: [WinError 53]"),
            (FileNotFoundError(r"root skanu nie istnieje albo niedostępny: X:\L"),
             r"root skanu nie istnieje albo niedostępny: X:\L")]:
        def _pada(*_a, exc=exc, **_k):
            raise exc
        monkeypatch.setattr(presence, "check", _pada)
        assert cli.main(["presence", dbp, "--root", str(tmp_path), "--volume", "V"]) == 1
        out = capsys.readouterr().out
        out.encode("cp1250")
        (wiersz,) = [w for w in out.splitlines() if w.startswith("Horreum presence: blad -- ")]
        assert wiersz.startswith("Horreum presence: blad -- " + oczekiwany), wiersz


def test_druk_ogona_presence_klasa_kod_2(tree, capsys, monkeypatch):  # noqa: F811
    """Ogon `presence --apply` pada zerwanym udziałem: wiersz ogona mówi klasą z surowym tekstem
    (ścieżka jest tylko w nim), kod 2 jak dotąd. Falsyfikator: `{type(exc).__name__}: {exc}`."""
    from horreum import cli
    con, root, vol, paths = tree
    con.commit()
    dbp = con.execute("PRAGMA database_list").fetchone()[2]
    os.remove(paths[0])

    def _ogon(con_, root_, *, now):
        yield "  fakty kopii: etap przed awaria"
        raise _zerwany_udzial()
    monkeypatch.setattr(cli, "_presence_tail", _ogon)
    assert cli.main(["presence", dbp, "--root", root, "--volume", vol, "--apply"]) == 2
    out = capsys.readouterr().out
    out.encode("cp1250")
    assert ("blad ogona zapisu -- udział sieciowy albo dysk nie odpowiada (WinError 64) - "
            "OSError: [WinError 64] Komunikat systemu") in out, out


@pytest.mark.parametrize("polecenie", ["rederive-kind", "header-fix"])
def test_druk_planu_apply_nieczytelny_klasa_kod_2(tmp_path, capsys, monkeypatch, polecenie):
    """`rederive-kind`/`header-fix --apply --plan`: plik planu na zerwanym udziale - odmowa mówi
    klasą z surowym tekstem, kod 2 jak dotąd; zła treść planu (`ValueError`) - zdaniem jak dotąd."""
    from horreum import cli
    dbp = str(tmp_path / "p.db")
    db.open_db(dbp).close()
    for exc, oczekiwany in [(_zerwany_udzial(r"X:\plany\p.json"),
                             "odmowa - udział sieciowy albo dysk nie odpowiada (WinError 64) - "
                             "OSError: [WinError 64] Komunikat systemu"),
                            (ValueError("plan innej bazy"), "odmowa - plan innej bazy")]:
        def _pada(*_a, exc=exc, **_k):
            raise exc
        monkeypatch.setattr(cli, "_wczytaj_plan", _pada)
        assert cli.main([polecenie, dbp, "--apply", "--plan", r"X:\plany\p.json"]) == 2
        out = capsys.readouterr().out
        out.encode("cp1250")
        assert f"(APPLY): {oczekiwany}" in out, out


def test_druk_listy_samodzielnych_nieczytelnej_klasa_kod_2(samodzielne, capsys, monkeypatch):  # noqa: F811
    """`stack-versions --standalone`: lista na zerwanym udziale - klasa z surowym tekstem, kod 2."""
    from horreum import cli
    s = samodzielne

    def _pada(_sciezka):
        raise _zerwany_udzial(r"X:\L\lista.tsv")
    monkeypatch.setattr(stack_variants, "read_standalone_list", _pada)
    s["con"].close()
    assert cli.main(["stack-versions", str(s["old"]), s["db"], "--archive", str(s["arch"]),
                     "--standalone", r"X:\L\lista.tsv"]) == 2
    out = capsys.readouterr().out
    out.encode("cp1250")
    assert ("stack-versions: lista samodzielnych nieczytelna: udział sieciowy albo dysk nie "
            "odpowiada (WinError 64) - OSError: [WinError 64] Komunikat systemu") in out, out


def test_odmowa_przeliczenia_rodzaju_klasa_i_druk_dry(tmp_path, capsys, monkeypatch):
    """`kind_rederive_plan`: odczyt kopii pada zerwanym udziałem - odmowa „odczyt <klasa> - <surowy
    tekst ze ścieżką>” i ten wiersz w druku `rederive-kind` (DRY; import dawcy liczy odmowy, ale
    ich nie drukuje). Falsyfikator: `f"odczyt {type(exc).__name__}: {exc}"`."""
    from horreum import cli
    from test_rederive_kind import _baza_flat
    dbp = str(tmp_path / "h.db")
    c = db.open_db(dbp)
    fid, _lid, _hh = _baza_flat(c, tmp_path)
    sciezka = c.execute("SELECT path FROM location WHERE frame_id = ?", (fid,)).fetchone()[0]

    def _pada(path, size):
        raise _zerwany_udzial(path)
    monkeypatch.setattr(scan, "_read_meta", _pada)
    zmiany, _bez, odmowy = scan.kind_rederive_plan(c)
    c.close()
    assert zmiany == [] and [f for f, _ in odmowy] == [fid]
    powod = odmowy[0][1]
    assert powod.startswith("odczyt udział sieciowy albo dysk nie odpowiada (WinError 64) - "
                            "OSError: [WinError 64] Komunikat systemu"), powod
    assert powod.count(os.path.basename(sciezka)) == 1, powod
    assert cli.main(["rederive-kind", dbp, "--plan-dir", str(tmp_path / "plany")]) == 1
    assert f"frame {fid}: {powod}" in capsys.readouterr().out


def test_abort_importu_przy_bledzie_bazy_mowi_klasa(tmp_path, monkeypatch):
    """Backstop wjazdu importu: zapis do bazy i szkielet padają PRAWDZIWYM błędem SQLite (baza
    zajęta) - `ImportAbort` mówi klasą bazy, nie `OperationalError: database is locked`; ścieżka stoi
    w zdaniu raz. Falsyfikator: `({type(exc).__name__}: {exc})`."""
    from horreum import import_fitsmirror as imp
    from test_import_fitsmirror import NOW as NOW_IMP, SPECS, _mk_donor
    busy = _prawdziwy_blad_sqlite(tmp_path, "busy")
    donor_path, files = _mk_donor(tmp_path, SPECS)
    pada = str(files[os.path.join("LIGHTS", "m31_2.fits")][0])
    prawdziwy = imp.ingest_record

    def _wjazd(con, rec, **kw):
        if rec.path == pada:
            raise busy
        return prawdziwy(con, rec, **kw)

    def _szkielet(*_a, **_k):
        raise busy
    monkeypatch.setattr(imp, "ingest_record", _wjazd)
    monkeypatch.setattr(imp, "_szkielet_po_awarii_zapisu", _szkielet)
    with pytest.raises(imp.ImportAbort) as abort:
        imp.import_fitsmirror(str(donor_path), str(tmp_path / "horreum.db"), now=NOW_IMP, rng_seed=1)
    tekst = str(abort.value)
    assert tekst == (f"wjazd {pada} padl (baza zablokowana (SQLITE_BUSY)), a szkielet "
                     f"tez nie wszedl (baza zablokowana (SQLITE_BUSY))"), tekst
