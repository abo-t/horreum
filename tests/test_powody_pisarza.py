"""Powody warstwy pisarza karty i renamu z KODEM (AR-148): zdanie PL rdzenia + kod + parametry
w wynikach pisarza i w bazie (`pending_changes`, `pending_renames`, `withheld_write` - 0042), okno
mówi je w języku UI (`gui.wb_worker.tekst_powodu`).

Co pilnujemy: każdy kod ma zdanie PL i EN i składa się z próbki parametrów każdego rodzaju (brak
próbki = czerwień); droga wyjścia z izolacji rozpoznana po RODZINIE kodów `way_*`, nie po prozie
(dawny parser `"recover_torn" in reason`); rdzeń nie oddaje gołej prozy w wynikach (AST, wyjątek:
surowy tekst wyjątku systemu); trójkę powodu w bazie pisze jeden pisarz na tabelę; dopisek
zamknięcia wstrzymania trzyma prozę i kod razem; odczyt z bazy totalny; CLI mówi prozą PL znak
w znak; odmowa zwolnienia przez bazę ma ten sam status i tekst co dawniej."""
import ast
import inspect
import json
import re
import string
from types import SimpleNamespace

import pytest

from horreum import cli, db, repo, writeback
from horreum.gui.i18n_catalog import CATALOG
from horreum.item_reasons import ITEM_REASON_CODES, PARAM_KINDS, PowodPozycji

NOW = "2026-10-15T00:00:00+00:00"
_POLSKIE = set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


def _probki():
    """Wartość każdego parametru z `PARAM_KINDS` - rodzaj z kontraktu, tekst ASCII (EN bez polskich
    liter), parametry-powody z kodem (zagnieżdżenie), lista cech z kodami."""
    return {
        "detail": "OSError: x", "inner": PowodPozycji("brak location w bazie", "no_location"),
        "outer": PowodPozycji("kopia zniknęła (present=0)", "copy_gone"),
        "path": "X:/L/a.fits", "dir": "X:/L", "src": "X:/L/a.fits", "dst": "X:/L/b.fits",
        "db_path": "X:/L/a.fits", "in_flight": "commit", "intent_detail": "OSError: y",
        "alias": "flamingstar", "canon": "IC405", "target": "IC405", "text": "abc",
        "status": "blocked", "commits": "1, 2", "op_kind": "commit", "phase": "written",
        "volume": "V", "copies": repo._kopie(2), "lead": PowodPozycji("żadna kopia jednoznacznie",
                                                                       "lead_none"),
        "keyword": "OBJECT", "copy": "X:/L/a.fits.k.horreum-kopia", "tmp": "X:/L/t.tmp",
        "change": writeback._zmiana_w_oknie([writeback._CECHA_ROZMIAR]),
        "way": writeback._droga_przywroc(7), "error": "OSError: z",
        "prop": "Observation:Object:Name", "value": "'IC 405'", "current": "IC405",
        "card": "'IC405'", "derived": "IC 405", "op": "del", "value_type": "int",
        "sha1": "abc", "mtime": "2026-01-01T00:00:00",
        "db_mtime": "2026-01-02T00:00:00", "expected": "written",
        "n": 2, "tries": 3, "winerror": 32, "op_id": 7, "location": 5, "object_id": 9,
        "rename_id": 4, "commit_id": 11, "before": 60, "after": 40,
        "needed": writeback._wolne_rekordy(2), "free": 1,
        "attr": "comment", "attrs": "foo, id", "char": "'\\x07'", "name": "'OBJECTNAM'",
        "length": 70, "limit": 68,
        "features": [writeback._CECHA_ROZMIAR, writeback._CECHA_NAGLOWEK],
        "paths": ["X:/L/a", "X:/L/b"], "sums": ["CHECKSUM", "DATASUM"],
        "os_code": "WinError 5", "db_code": "SQLITE_BUSY",
    }


def test_KAZDY_kod_ma_probke_i_sklada_sie_w_PL_i_EN_a_EN_bez_polskiego():
    """Każdy kod z wpisem prostym (wpisy mnogie - `copies`, `free_records` - mają własne testy)
    SKŁADA SIĘ z próbki parametrów w obu językach: zdanie z kodu istnieje (parametry pokrywają pola,
    rodzaje z kontraktu - bez spadku na prozę), a EN nie ma polskich liter. Nowy parametr bez
    próbki = czerwień (próbki = komplet `PARAM_KINDS`). Zdanie PL próbki powstaje tu z katalogu,
    więc równości PL z prozą RDZENIA ten test nie dowodzi - trzyma ją test AST
    `test_gui_object_change.test_KAZDY_kod_powodu_pozycji_ma_zdanie_PL_i_EN_a_PL_to_zdanie_rdzenia`."""
    pytest.importorskip("PySide6")
    from horreum.gui import i18n
    from horreum.gui.wb_worker import _zdanie_z_kodu, czytelny_powod, tekst_powodu
    probki = _probki()
    assert set(probki) == set(PARAM_KINDS), set(probki) ^ set(PARAM_KINDS)
    sprawdzone = 0
    for kod in sorted(ITEM_REASON_CODES):
        wpis = CATALOG[f"objchg.item.{kod}"]
        if isinstance(wpis["pl"], dict):
            continue
        pola = {f for _, f, _, _ in string.Formatter().parse(wpis["pl"]) if f}
        params = {f: probki[f] for f in pola}
        tekst = wpis["pl"].format(**{f: (", ".join(map(str, v)) if isinstance(v, list) else v)
                                     for f, v in params.items()})
        powod = PowodPozycji(tekst, kod, **params)
        for lang in ("pl", "en"):
            i18n.set_lang(lang)
            assert _zdanie_z_kodu(powod) is not None, (kod, lang)
            zdanie = tekst_powodu(powod)
            if lang == "pl":
                assert zdanie == czytelny_powod(str(powod)), (kod, zdanie)
            else:
                assert not set(zdanie) & _POLSKIE, (kod, zdanie)
        sprawdzone += 1
    i18n.set_lang("pl")
    assert sprawdzone > 190, sprawdzone


# ============================================================ droga wyjścia z izolacji po KODZIE


def test_droga_wyjscia_rozpoznana_po_KODACH_z_literalem_drogi_nie_po_prozie():
    """Parser „czy powód już niesie drogę wyjścia” (dawniej `"recover_torn" in reason or _RECZNA in
    reason`) idzie po JAWNYM zbiorze kodów, których zdanie niesie literał drogi - rekurencyjnie po
    parametrach i uwagach. SPOT: zbiór == kody, których PL katalogu spełnia DOKŁADNIE predykat
    dawnego parsera - zawiera `recover_torn` albo całe `_RECZNA` (nowy taki kod bez wpisu do zbioru
    = czerwień; `finish_failed_isolated_release` niesie samo `release_isolation(…)`, więc - jak
    w dawnym parserze - poza zbiorem). `way_finish` literału nie
    niesie, więc - jak dawny parser - drogi nie daje. Proza z tym samym tekstem bez kodu NIE jest
    rozpoznawana (rdzeń jej już nie oddaje)."""
    literalne = {k for k in ITEM_REASON_CODES
                 if isinstance(CATALOG[f"objchg.item.{k}"]["pl"], str)
                 and ("recover_torn" in CATALOG[f"objchg.item.{k}"]["pl"]
                      or str(writeback._RECZNA) in CATALOG[f"objchg.item.{k}"]["pl"])}
    assert writeback._KODY_DROGI == literalne, writeback._KODY_DROGI ^ literalne
    faza = PowodPozycji("operacja 3 jest w fazie synced, nie czeka na dokończenie",
                        "finish_not_waiting", op_id=3, phase="synced")
    powrot = PowodPozycji(f"przerwany powrót tej operacji - ponów: {writeback._droga_przywroc(3)}",
                          "way_resume_return", way=writeback._droga_przywroc(3))
    region = PowodPozycji(f"region nagłówka na dysku nie jest wynikiem operacji 3 - plik zmienił "
                          f"się od zapisu; {powrot}", "finish_region_changed", op_id=3, way=powrot)
    izolacja = writeback._powod_izolacji({"id": 3, "kind": "commit", "phase": "writing"})
    assert izolacja.code == "isolated_recover", izolacja
    for niesie in (writeback._RECZNA, writeback._droga_przywroc(3), izolacja,
                   writeback._INNY_PLIK, region, writeback._dopisz(faza, writeback._INNY_PLIK)):
        assert writeback._niesie_droge(niesie), niesie
    for nie in (None, faza, writeback._droga_dokoncz(3),
                PowodPozycji("lokacja ma operację nowszą niż 3 - dokończenie odmawia",
                             "finish_newer_op", op_id=3),
                str(writeback._INNY_PLIK), f"x (`recover_torn(3)`)"):
        assert not writeback._niesie_droge(nie), nie


@pytest.mark.parametrize("status, powod, kod", [
    # status 'failed' - recepty zwolnienia nie ma nawet przy powodzie bez drogi (człon statusu)
    ("failed", PowodPozycji("brak location w bazie", "no_location"), "finish_failed_isolated"),
    ("blocked", PowodPozycji("operacja 1 jest w fazie synced, nie czeka na dokończenie",
                             "finish_not_waiting", op_id=1, phase="synced"),
     "finish_failed_isolated_release"),
    ("blocked", writeback._INNY_PLIK, "finish_failed_isolated"),
    # jak dawny parser prozy: `isolated_recover` niesie `recover_torn(` (spoza rodziny `way_*`),
    # `way_finish` nie niesie literału drogi - recepta zwolnienia dochodzi
    ("blocked", writeback._powod_izolacji({"id": 1, "kind": "commit", "phase": "writing"}),
     "finish_failed_isolated"),
    ("blocked", writeback._droga_dokoncz(1), "finish_failed_isolated_release"),
], ids=["failed_bez_drogi", "blocked_bez_drogi", "blocked_z_recepta", "blocked_odzysk_izolacji",
        "blocked_droga_dokonczenia"])
def test_wynik_dokonczenia_dostaje_recepte_zwolnienia_po_KODZIE(tmp_path, monkeypatch, status, powod,
                                                                 kod):
    """Dokończenie zapisu w miejscu odmówiło albo padło: wynik lokacji mówi o izolacji, a receptę
    zwolnienia ręką dostaje WYŁĄCZNIE odmowa ('blocked'), której powód nie niesie drogi `way_*`.
    Kod wyniku i wpis stagingu w bazie niosą ten sam kod, a dokończenie jako `inner`."""
    from test_writeback_inplace import _baza_z_plikiem, _fits
    p = _fits(tmp_path / "z.fits")
    con, _ = _baza_z_plikiem(tmp_path, p)
    monkeypatch.setattr(writeback, "_dokoncz",
                        lambda con_, op_id, *, now: writeback.WriteResult(status, powod, None))
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    (f,) = res.failed
    assert f.reason.code == kod and dict(f.reason.params)["inner"] == powod, f.reason
    assert f.reason.count("writeback.release_isolation") == (
        1 if kod == "finish_failed_isolated_release" or powod is writeback._INNY_PLIK else 0)
    (wiersz,) = con.execute("SELECT reason, reason_code FROM pending_changes WHERE run_id = 'R'")
    assert tuple(wiersz) == (str(f.reason), kod)
    con.close()


# ============================================================ meta: bez gołej prozy, jeden pisarz


def _ksztalt_wyjatku(wezel):
    """Czy f-string to surowy tekst wyjątku `f"{type(X).__name__}: {X}"` (granica - tekst systemu)."""
    if not isinstance(wezel, ast.JoinedStr) or len(wezel.values) != 3:
        return False
    a, sep, b = wezel.values
    return (isinstance(sep, ast.Constant) and sep.value == ": "
            and ast.unparse(a.value).startswith("type(") and ast.unparse(a.value).endswith(
                ").__name__") and ast.unparse(b.value) == ast.unparse(a.value)[5:-10])


def test_meta_wyniki_pisarza_bez_golej_prozy():
    """AST `writeback`: konstruktor wyniku (`WriteResult`, `FileResult`, `RenameFileResult`,
    `Fallback`), wyjątki pisarza i pomocnicy rozliczenia (`_mark`, `_blok`, `_pad`, `_stop`,
    `_odmowa`) oraz klingi zapisu powodu w bazie nie biorą literału ani f-stringu jako powodu -
    nowe miejsce z gołą prozą to zdanie, którego okno nie powie w języku UI. Wyjątek: surowy tekst
    wyjątku systemu `f"{type(exc).__name__}: {exc}"` (granica)."""
    pozycje = {"WriteResult": 1, "FileResult": 3, "RenameFileResult": 1, "Fallback": 0,
               "_XisfRefusal": 0, "_PodmianaOdbita": 0, "_PodmianaRozdarta": 0,
               "_WypartaDoPowrotu": 0, "_mark": 2, "_blok": 2, "_pad": 2, "_stop": 2,
               "_odmowa": 1, "set_pending_status": "reason", "set_rename_status": "reason",
               "settle_rename_intent": "reason", "withhold_write": "reason",
               "revert_inplace_op": "reason", "_rename_pod_straza": "reason",
               "_przenies_wstecz": "reason"}
    drzewo = ast.parse(inspect.getsource(writeback))
    golych, wywolan = [], 0
    for w in ast.walk(drzewo):
        if not isinstance(w, ast.Call):
            continue
        nazwa = w.func.attr if isinstance(w.func, ast.Attribute) else getattr(w.func, "id", None)
        if nazwa not in pozycje:
            continue
        gdzie = pozycje[nazwa]
        arg = (next((k.value for k in w.keywords if k.arg == gdzie), None) if isinstance(gdzie, str)
               else next((k.value for k in w.keywords if k.arg == "reason"),
                         w.args[gdzie] if len(w.args) > gdzie else None))
        wywolan += 1
        if arg is None or (isinstance(arg, ast.Constant) and arg.value is None):
            continue
        if isinstance(arg, (ast.Constant, ast.JoinedStr)) and not _ksztalt_wyjatku(arg):
            golych.append(f"{w.lineno}: {ast.unparse(w)[:90]}")
    assert wywolan > 150, wywolan
    assert not golych, "\n".join(golych)


def test_przepowiednia_drogi_FITS_mowi_kodem():
    """`inplace_route` (podgląd drogi bez pliku) i obraz karty (`_fits_card_image`) oddają powód
    przez `return`, poza strażą konstruktorów wyżej - każdy niesie kod, a PL jest zdaniem rdzenia."""
    przypadki = [
        (writeback.inplace_route("fits", "OBJECT", "NGC 7635", "str", None, op="add"),
         "route_depends", {"keyword": "OBJECT"}),
        (writeback.inplace_route("fits", "FOCALLEN", "800", "int", None, op="add"),
         "fb_op_kind", {"op": "add", "value_type": "int", "keyword": "FOCALLEN"}),
        (writeback.inplace_route("fits", "FOCALLEN", "800", "int", None),
         "fb_value_not_text", {"keyword": "FOCALLEN"}),
        (writeback.inplace_route("fits", "OBJECT", "V" * 20, "str", "k" * 60),
         "fb_card_too_long", {"keyword": "OBJECT"}),
        (writeback._fits_card_image("OBJECT", "V" * 20, "k" * 60)[1],
         "fb_card_too_long", {"keyword": "OBJECT"}),
    ]
    for powod, kod, params in przypadki:
        assert isinstance(powod, PowodPozycji) and powod.code == kod, powod
        assert dict(powod.params) == params, powod.params
        assert str(powod) == CATALOG[f"objchg.item.{kod}"]["pl"].format(**params), powod


def test_meta_jeden_pisarz_trojki_kart_renamu_i_wstrzymania():
    """AST `repo`: powód wpisu stagingu karty ustawia WYŁĄCZNIE `_set_pending_reason_tx`, renamu -
    `_set_rename_reason_tx`, a wstrzymanie powstaje z trójką w jednym INSERT (`_withhold_write_tx`) i
    żaden UPDATE nie zmienia jego powodu. Sklejenie powodu w SQL (`reason || '; '`) rozjechałoby
    prozę z kodem (0042)."""
    wzorce = {"karty": re.compile(r"UPDATE pending_changes SET[^;]*\breason\b"),
              "renamu": re.compile(r"UPDATE pending_renames SET[^;]*\breason\b"),
              "wstrzymania": re.compile(r"UPDATE withheld_write SET[^;]*\breason\b"),
              "insert": re.compile(r"INSERT INTO withheld_write")}
    trafienia = {k: [] for k in wzorce}
    for f in (n for n in ast.walk(ast.parse(inspect.getsource(repo)))
              if isinstance(n, ast.FunctionDef)):
        for c in ast.walk(f):
            if isinstance(c, ast.Constant) and isinstance(c.value, str):
                for k, wz in wzorce.items():
                    if wz.search(c.value):
                        trafienia[k].append((f.name, c.value))
    assert [n for n, _ in trafienia["karty"]] == ["_set_pending_reason_tx"], trafienia["karty"]
    assert [n for n, _ in trafienia["renamu"]] == ["_set_rename_reason_tx"], trafienia["renamu"]
    assert trafienia["wstrzymania"] == []
    assert [n for n, _ in trafienia["insert"]] == ["_withhold_write_tx"]
    assert "reason_code" in trafienia["insert"][0][1] and "reason_args" in trafienia["insert"][0][1]


# ============================================================ baza: dopisek, odczyt totalny


def _wstrzymanie_z_wpisami(con):
    """Wiersz `withheld_write` i dwa wpisy stagingu z nim związane: jeden z kodem (od 0042), drugi
    z samą prozą (wiersz sprzed 0042)."""
    con.execute("INSERT INTO frame(id, sha1_data, kind, first_seen_at) VALUES (1, 'a', 'light', 't')")
    con.execute("INSERT INTO location(id, frame_id, volume, path) VALUES (1, 1, 'V', 'X:\\L\\a.fits')")
    con.execute("INSERT INTO commits(id, run_id, applied_at) VALUES (1, 'R', 't')")
    con.execute("INSERT INTO withheld_write(id, kind, location_id, frame_id, commit_id, header_hash, "
                "object_written, reason, actor, opened_at) VALUES (1, 'commit', 1, 1, 1, 'h', 0, "
                "'x', 'user:local', 't')")
    for i in (1, 2):
        con.execute("INSERT INTO pending_changes(id, run_id, location_id, keyword, op, status, "
                    "withheld_id) VALUES (?, 'R', 1, 'OBJECT', 'set', 'failed', 1)", (i,))
    zdanie = repo.withheld_reason(con, location_id=1, commit_id=1)
    repo._set_pending_reason_tx(con, [1], zdanie)
    con.execute("UPDATE pending_changes SET reason = 'proza sprzed 0042' WHERE id = 2")
    con.commit()
    return zdanie


@pytest.mark.parametrize("zamkniecie, nota", [
    ("cofniete", "withheld_undone"), ("inna_klatka", "withheld_other_frame"),
    ("nowszy_stan", "withheld_newer_header")])
def test_dopisek_zamkniecia_wstrzymania_trzyma_proze_i_kod_razem(tmp_path, zamkniecie, nota):
    """Zamknięcie wstrzymania dokleja notę do powodu wpisów: proza = dawne `COALESCE(reason || '; ',
    '') || nota` znak w znak, a kod zostaje - nota na liście `notes` (wiersz z kodem) albo w kopercie
    `prose` (wiersz sprzed 0042). Falsyfikator: sklejenie w SQL - proza rośnie, kod i `notes` nie."""
    from horreum.item_reasons import z_bazy
    con = db.open_db(str(tmp_path / "h.db"))
    zdanie = _wstrzymanie_z_wpisami(con)
    dopisek = {"cofniete": repo._WSTRZYMANIE_COFNIETE, "inna_klatka": repo._WSTRZYMANIE_INNA_KLATKA,
               "nowszy_stan": repo._WSTRZYMANIE_NOWSZY_STAN}[zamkniecie]
    with con:
        repo._zamknij_wstrzymanie(con, 1, "undone" if zamkniecie == "cofniete" else "superseded",
                                  NOW, dopisek)
    w1, w2 = (z_bazy(*r) for r in con.execute(
        "SELECT reason, reason_code, reason_args FROM pending_changes ORDER BY id"))
    assert str(w1) == f"{zdanie}; {dopisek}" and w1.code == "testimony_withheld"
    assert [n.code for n in dict(w1.params)["notes"]] == [nota]
    assert str(w2) == f"proza sprzed 0042; {dopisek}" and w2.code == "prose"
    assert [n.code for n in dict(w2.params)["notes"]] == [nota]
    con.close()


def test_odczyt_wierszy_stagingu_i_wstrzymania_jest_totalny(tmp_path):
    """Czytelnicy powodu z bazy w rdzeniu (`writeback._powod_wiersza`, `repo.open_undo_withheld_for_item`)
    oddają `PowodPozycji` z kodem, a wiersz sprzed 0042, kod spoza zbioru i parametry spoza kodeka
    - zachowaną prozę, bez wyjątku."""
    con = db.open_db(str(tmp_path / "h.db"))
    zdanie = _wstrzymanie_z_wpisami(con)
    w1, w2 = writeback.pending_for_run(con, "R")
    assert writeback._powod_wiersza(w1) == zdanie and writeback._powod_wiersza(w1).code == \
        "testimony_withheld"
    assert type(writeback._powod_wiersza(w2)) is str
    for kod, args in (("kod_spoza_zbioru", "{}"), ("copy_gone", '{"notes": "nie-lista"}'),
                      # zagnieżdżony kod nie-tekst: niehaszowalny obiekt JSON nie wywraca odczytu
                      ("copy_gone", '{"inner": {"text": "x", "code": [1], "args": {}}}'),
                      ("copy_gone", '{"inner": {"text": "x", "code": {}, "args": {}}}')):
        con.execute("UPDATE pending_changes SET reason = 'p', reason_code = ?, reason_args = ? "
                    "WHERE id = 2", (kod, args))
        (w2,) = [w for w in writeback.pending_for_run(con, "R") if w["id"] == 2]
        assert writeback._powod_wiersza(w2) == "p" and not hasattr(writeback._powod_wiersza(w2),
                                                                   "code")
    # szczyt: kod z kolumny nie jest tekstem (zapis spoza kodeka) - proza, bez wyjątku
    from horreum.item_reasons import z_bazy, z_czesci
    for kod in ([1], {}, 5):
        assert type(z_czesci("p", kod, {})) is str and z_czesci("p", kod, {}) == "p", kod
    assert type(z_bazy("p", [1], "{}")) is str
    con.execute("INSERT INTO object_change_run(run_id, mode, created_at) VALUES ('R', 'align', 't')")
    con.execute("INSERT INTO pending_object_change(id, run_id, frame_id, location_id, old_path, "
                "object_change) VALUES (7, 'R', 1, 1, 'X:\\L\\a.fits', 0)")
    con.commit()
    nota = repo.withheld_reason(con, location_id=1, commit_id=1, undo=True)
    repo.withhold_write(con, kind="undo", location_id=1, commit_id=1, header_hash="h", reason=nota,
                        now=NOW)
    wstrzymanie = repo.open_undo_withheld_for_item(con, 7)
    assert wstrzymanie["reason"] == nota and wstrzymanie["reason"].code == "testimony_withheld_undo"
    con.close()


def test_odmowa_zwolnienia_przez_baze_ma_ten_sam_status_i_tekst(tmp_path, monkeypatch):
    """Klinga `repo.release_inplace_op` odmawia `OdmowaZPowodem` (podklasa `ValueError` - wołający
    łapią jak dotąd): zwolnienie ręką oddaje 'blocked' z tekstem wyjątku znak w znak, a do tego kod
    (`release_refused_db`)."""
    from test_writeback_inplace import _baza_z_plikiem, _fits
    p = _fits(tmp_path / "z.fits")
    con, _ = _baza_z_plikiem(tmp_path, p)
    assert writeback.commit(con, "R", now=NOW, inplace=True).in_place
    (op_id,) = con.execute("SELECT id FROM inplace_op").fetchone()
    with pytest.raises(ValueError) as odmowa:
        repo.release_inplace_op(con, op_id=op_id, now=NOW, reason="test")
    monkeypatch.setattr(repo, "inplace_op_phase", lambda con_, op: "written")  # widziana „izolująca”
    status, powod = writeback._zwolnij_reka(con, op_id, now=NOW, reason="test")
    assert (status, str(powod)) == ("blocked", str(odmowa.value))
    assert str(odmowa.value) == f"operacja {op_id} nie izoluje lokacji - nie ma czego zwalniać"
    assert powod.code == "release_refused_db" and dict(powod.params) == {"op_id": op_id}
    con.close()


def test_cli_mowi_proza_PL_znak_w_znak():
    """CLI drukuje powód jak dotąd - `str(PowodPozycji)` to zdanie PL rdzenia (kod zostaje w bazie
    i w obiekcie, CLI nie ma wyjścia maszynowego dla zapisu)."""
    powod = writeback._dysk_milczy(OSError("udział milczy"))
    res = SimpleNamespace(applied=[], blocked=[writeback.FileResult(1, "X:/L/a.fits", "blocked",
                                                                     powod)],
                          failed=[], skipped=[], reconciled=[])
    tekst = cli._format_rename_apply("h.db", SimpleNamespace(skipped=[]), res, "r1")
    assert f"    BLOCKED a.fits: {powod}" in tekst.splitlines()
    assert str(powod) == "dysk nie odpowiada (udział milczy) - zamiar zostaje"


def test_kodek_listy_cech_i_zagniezdzen_przezywa_baze():
    """Parametr-lista (`features`) z powodami z kodem i powód zagnieżdżony (`change`, `way`) wracają
    z kolumn tym samym powodem - kodek z listami (JSON) bez zmian kształtu."""
    from horreum.item_reasons import do_bazy, z_bazy
    zmiana = writeback._zmiana_w_oknie([writeback._CECHA_ROZMIAR, writeback._CECHA_PROBKA])
    powod = PowodPozycji(f"{zmiana} - wersja innego pisarza wróciła na miejsce, zmiana NIE zapisana; "
                         f"ponów po odświeżeniu stagingu", "other_writer_returned", change=zmiana)
    wrocil = z_bazy(*do_bazy(powod))
    assert wrocil == powod and wrocil.code == "other_writer_returned"
    cechy = dict(dict(wrocil.params)["change"].params)["features"]
    assert [c.code for c in cechy] == ["feat_size", "feat_sample"]
    assert json.loads(do_bazy(powod)[2])["change"]["args"]["features"][0]["code"] == "feat_size"


@pytest.mark.parametrize("fmt, koperta", [("fits", True), ("fits", False), ("xisf", True),
                                          ("xisf", False)],
                         ids=["fits_bajtowo", "fits_semantycznie", "xisf_bajtowo",
                              "xisf_semantycznie"])
def test_cofniecie_atomowe_odmawia_kodem_cofniecia_na_kazdej_drodze(tmp_path, fmt, koperta):
    """Kontrola `header_hash` cofnięcia atomowego (`write_full_header`) porównuje z nagłówkiem
    zapisanym przez COMMIT - każda z czterech dróg (koperta bajtowa / tekst semantycznie, FITS /
    XISF) odmawia kodem `undo_header_changed` i prozą „od commitu”. Zapis (`write_changes`) na tym
    samym pliku mówi kodem i prozą zapisu („od stagingu”) - obie zdaniem po polsku, nie gołym
    „header_hash mismatch”."""
    from test_writeback_inplace import _fits, _xisf
    p = str(_fits(tmp_path / "a.fits") if fmt == "fits" else _xisf(tmp_path / "a.xisf"))
    op = writeback.WriteOp("OBJECT", "set", "IC 405", "str")
    zapis = writeback.write_changes(p, [op], "zly")
    assert zapis.status == "blocked" and zapis.reason.code == "header_hash_mismatch", zapis
    commit = writeback.write_changes(p, [op], None)
    assert commit.status == "applied" and commit.backup_text, commit
    tekst = commit.backup_text if koperta else "nagłówek sprzed kopert"
    assert (writeback.RegionBackup.decode(tekst) is not None) is koperta
    res = writeback.write_full_header(p, tekst, "zly")
    assert res.status == "blocked" and res.reason.code == "undo_header_changed", res
    assert str(res.reason) == "nagłówek pliku zmienił się od commitu (header_hash niezgodny)"
    assert str(zapis.reason) == "nagłówek pliku zmienił się od stagingu (header_hash niezgodny)"


def test_wpis_mnogi_wolnych_rekordow_PL_jak_rdzen_EN_odmienia():
    """Brak miejsca w nagłówku FITS mówi liczbę rekordów z odmianą (dawniej „potrzebuje 1 wolnych
    rekordów”): fragment `free_records` - PL każdej liczby = zdanie rdzenia, EN liczba pojedyncza
    i mnoga; zdanie nadrzędne `fb_no_room` składa fragment w języku UI."""
    pytest.importorskip("PySide6")
    from horreum.gui import i18n
    from horreum.gui.wb_worker import tekst_powodu
    try:
        for n, en in ((1, "1 free record"), (2, "2 free records"), (5, "5 free records"),
                      (22, "22 free records")):
            fragment = writeback._wolne_rekordy(n)
            i18n.set_lang("pl")
            assert tekst_powodu(fragment) == str(fragment), fragment
            i18n.set_lang("en")
            assert tekst_powodu(fragment) == en
        assert str(writeback._wolne_rekordy(1)) == "1 wolnego rekordu"
        assert str(writeback._wolne_rekordy(2)) == "2 wolnych rekordów"
        brak = PowodPozycji(f"brak miejsca w nagłówku FITS: dopisanie potrzebuje "
                            f"{writeback._wolne_rekordy(1)} za END w ostatnim bloku 2880 B, a jest 0 "
                            f"- nagłówek urósłby o blok i przesunął dane", "fb_no_room",
                            needed=writeback._wolne_rekordy(1), free=0)
        assert "needs 1 free record after END" in tekst_powodu(brak), tekst_powodu(brak)
    finally:
        i18n.set_lang("pl")


def test_ostrzezenie_rekoncyliacji_renamu_niesie_powod_z_kodem_z_prawdziwej_drogi(tmp_path):
    """Gest „Zmień obiekt…” zbiera ostrzeżenia z rekoncyliacji przerwanych renamów
    (`_ostrzezenia_rekoncyliacji`): zamiar, którego plik stoi pod OBIEMA nazwami, daje ostrzeżenie
    `rename_reconcile`, a jego `detail` to powód rekoncyliacji Z KODEM - nie proza."""
    import shutil
    from test_writeback_inplace import _fits, _loc, _scan_in
    con = db.open_db(str(tmp_path / "h.db"))
    p = _fits(tmp_path / "a.fits")
    _scan_in(con, p)
    nowa = tmp_path / "b.fits"
    rid = repo.stage_rename(con, run_id="N", location_id=_loc(con, p)["id"], old_path=str(p),
                            new_path=str(nowa), expected_mtime=None)
    repo.open_rename_intent(con, rename_id=rid, direction="commit")
    shutil.copyfile(p, nowa)
    (ostrzezenie,) = writeback._ostrzezenia_rekoncyliacji(con, now=NOW)
    assert ostrzezenie.code == "rename_reconcile"
    detail = dict(ostrzezenie.params)["detail"]
    assert detail.code == "intent_both_names", detail
    assert str(ostrzezenie) == f"{dict(ostrzezenie.params)['path']}: {detail}"
    con.close()


# ============================================================ odmowy czytnika XISF i reguł karty (AR-158)
# Zdanie odmowy rodzi się z kodem w `scan` (`XisfFormatError`) i w `card_rules` (`CardViolation`),
# pisarz przenosi gotowy powód do wyniku - okno EN mówi po angielsku, PL znak w znak jak rdzeń.


def _okno(powod):
    """Zdanie okna w obu językach: `(pl, en)`; PL == `czytelny_powod(proza rdzenia)`."""
    from horreum.gui import i18n
    from horreum.gui.wb_worker import czytelny_powod, tekst_powodu
    try:
        i18n.set_lang("pl")
        pl = tekst_powodu(powod)
        i18n.set_lang("en")
        en = tekst_powodu(powod)
    finally:
        i18n.set_lang("pl")
    assert pl == czytelny_powod(str(powod)), (pl, str(powod))
    assert not set(en) & _POLSKIE and en != pl, en
    return pl, en


def _zla_sygnatura(tmp_path):
    from test_writeback import _xisf
    p = _xisf(tmp_path, "sygn.xisf")
    with open(p, "r+b") as fh:
        fh.write(b"XISF0200")
    return p, [writeback.WriteOp("TELESCOP", "set", "ED120R", "str")]


def _bez_wzorca(tmp_path):
    from test_writeback import _xisf
    return (_xisf(tmp_path, "gole.xisf", keywords=[("FOCALLEN", "796"), ("XBINNING", "1")],
                  props=""), [writeback.WriteOp("OBJECT", "add", "NGC 7000", "str")])


def _ciasno(tmp_path):
    from test_writeback import _xisf
    return _xisf(tmp_path, "ciasno.xisf", pad=8), [writeback.WriteOp("OBJECT", "add", "NGC 7000",
                                                                     "str")]


@pytest.mark.parametrize("buduj, kod, pl, en", [
    (_zla_sygnatura, "xisf_unreadable_reader",
     "nagłówek XISF nieczytelny - ValueError: nie XISF monolithic (sygnatura b'XISF0200')",
     "XISF header unreadable - not a monolithic XISF file (signature b'XISF0200')"),
    (_bez_wzorca, "xisf_no_text_template",
     "XISF: żadna karta tego pliku nie trzyma wartości w apostrofach FITS - konwencji wartości "
     "tekstowej NIE ZNAM, więc nowej karty nie składam",
     "XISF: no card in this file keeps its value in FITS quotes - I do NOT KNOW the convention "
     "for text values, so I do not build a new card"),
    (_ciasno, "xisf_no_room",
     "XISF: nagłówek nie mieści się w rezerwie (628 B > 578 B) - attachmenty się nie ruszają",
     "XISF: the header does not fit in the reserve (628 B > 578 B) - the attachments do not move"),
], ids=["read_xisf_or_refuse", "build_fits_keyword_element", "build_xisf_header_region"])
def test_odmowa_czytnika_XISF_mowi_w_oknie_kodem_na_kazdej_drodze(tmp_path, buduj, kod, pl, en):
    """Trzy drogi odmowy czytnika do okna: odczyt nagłówka (`_read_xisf_or_refuse` - kod czytnika
    zagnieżdżony w zdaniu „nieczytelny”, PL jak dawne `ValueError: …`), wstawka karty
    (`build_fits_keyword_element`) i bramka mieszczenia się (`build_xisf_header_region`). Wynik
    'blocked' z kodem, plik nietknięty; PL okna = zdanie rdzenia, EN po angielsku."""
    pytest.importorskip("PySide6")
    p, ops = buduj(tmp_path)
    przed = p.read_bytes()
    res = writeback.write_xisf_changes(str(p), ops, None)
    assert res.status == "blocked" and res.reason.code == kod, res
    assert p.read_bytes() == przed
    zdanie_pl, zdanie_en = _okno(res.reason)
    assert str(res.reason) == zdanie_pl == pl
    assert zdanie_en == en, zdanie_en
    if kod == "xisf_unreadable_reader":
        assert dict(res.reason.params)["inner"].code == "xisf_signature"
    if kod == "xisf_no_room":
        assert {k for k, _ in res.reason.params} == {"length", "limit"}


def test_odmowa_czytnika_z_kodem_zostaje_ValueError_z_dawnym_zdaniem(tmp_path):
    """Wołający czytnika łapią `ValueError` jak dotąd (`XisfFormatError` to jego podklasa), a tekst
    wyjątku to dotychczasowe zdanie PL. Diagnoza „Typ: opis” (miękkie lądowanie skanu →
    `location.unreadable_reason`, pozycja `unreadable` żniw) mówi `ValueError`, jak wiersze sprzed
    AR-158 i zdanie okna `xisf_unreadable_reader` - nie nazwą podklasy."""
    from horreum import harvest, scan
    p, _ = _zla_sygnatura(tmp_path)
    with pytest.raises(ValueError) as odmowa:
        scan.read_xisf_meta_full(str(p))
    assert str(odmowa.value) == "nie XISF monolithic (sygnatura b'XISF0200')"
    assert odmowa.value.powod.code == "xisf_signature"
    rec = scan.scan_file(str(p))
    assert rec.header is None
    assert rec.error == "ValueError: nie XISF monolithic (sygnatura b'XISF0200')"
    assert scan.unreadable_reason_of(scan.XisfTargetMissing(PowodPozycji(
        "brak location w bazie", "no_location"))) == "ValueError: brak location w bazie"
    assert scan.unreadable_reason_of(KeyError("k")) == "KeyError: 'k'"
    wbpp = tmp_path / "wbpp"
    (wbpp / "master").mkdir(parents=True)
    (wbpp / "master" / "masterFlat_X.xisf").write_bytes(p.read_bytes())
    con = db.open_db(str(tmp_path / "h.db"))
    (it,) = harvest.plan(con, str(wbpp), archive_root="A",
                         read=lambda src: scan.read_xisf_meta_full(src)).items
    assert (it.reason, it.detail) == ("unreadable",
                                      "ValueError: nie XISF monolithic (sygnatura b'XISF0200')")
    con.close()


def test_plan_karty_ze_sciezki_mowi_regule_karty_w_jezyku_UI(tmp_path):
    """Gest „Zatwierdź ze ścieżki…” (`app.plan_kart_sciezki`) pomija klatki, gdy forma karty łamie
    reguły FITS - powód reguły w zdaniu okna idzie przez `tekst_powodu`: EN po angielsku, PL znak
    w znak jak dawne zdanie reguły."""
    pytest.importorskip("PySide6")
    from horreum.gui import app as app_mod
    from horreum.gui import i18n
    con = db.open_db(str(tmp_path / "h.db"))
    try:
        zdania = {}
        for lang in ("pl", "en"):
            i18n.set_lang(lang)
            value, touched, skipped = app_mod.plan_kart_sciezki(con, "Café", [1])
            assert value == "Café" and touched == [] and len(skipped) == 1
            zdania[lang] = skipped[0][2]
    finally:
        i18n.set_lang("pl")
    assert ("wartość karty OBJECT ma znak 'é' spoza drukowalnego ASCII - karta FITS go nie "
            "przyjmie, a w nagłówku XISF łamie XML 1.0") in zdania["pl"]
    assert "the value of card OBJECT has the character 'é' outside printable ASCII" in zdania["en"]
    assert not set(zdania["en"]) & _POLSKIE, zdania["en"]
    con.close()


def test_brak_celu_dalej_pomija_a_cel_nieosiagalny_dalej_blokuje(tmp_path):
    """Typy `XisfTargetMissing`/`XisfValueUnreachable` (pisarz steruje nimi przepływem) dostały kod
    przez dziedziczenie: własność NIEOBECNA dalej = pominięcie ('applied' bez niej), własność
    w `location=` dalej = blokada - teraz z kodem; `set` karty nieobecnej niesie kod czytnika
    w `detail`, okno EN mówi całość po angielsku."""
    pytest.importorskip("PySide6")
    from horreum import scan
    from test_writeback import _xisf
    assert issubclass(scan.XisfTargetMissing, scan.XisfFormatError)
    assert issubclass(scan.XisfValueUnreachable, scan.XisfFormatError)
    bez = _xisf(tmp_path, "bez.xisf", keywords=[("TELESCOP", "'ED'")], props="")
    res = writeback.write_xisf_changes(str(bez), [writeback.WriteOp("TELESCOP", "set", "ED120R",
                                                                     "str")], None)
    assert res.status == "applied", res
    loc = _xisf(tmp_path, "loc.xisf", keywords=[("TELESCOP", "'ED'")],
                props='<Property id="Instrument:Telescope:Name" type="String" '
                      'location="attachment:900:4"/>')
    res = writeback.write_xisf_changes(str(loc), [writeback.WriteOp("TELESCOP", "set", "ED120R",
                                                                     "str")], None)
    assert res.status == "blocked" and res.reason.code == "xisf_prop_location", res
    assert str(res.reason) == ("XISF: własność Instrument:Telescope:Name trzyma wartość "
                               "w location= - poza nagłówkiem")
    _okno(res.reason)
    res = writeback.write_xisf_changes(str(bez), [writeback.WriteOp("FILTER", "set", "Ha", "str")],
                                       None)
    assert res.status == "blocked" and res.reason.code == "xisf_set_missing", res
    assert dict(res.reason.params)["detail"].code == "xisf_card_missing"
    assert str(res.reason) == ("XISF: karta FILTER[0] nieobecna w nagłówku - 'set' nie zakłada "
                               "karty; dopisanie idzie przez 'add' (P6d)")
    _, en = _okno(res.reason)
    assert en.startswith("XISF: card FILTER[0] is not in the header - 'set' does not create"), en


@pytest.mark.parametrize("fmt, op, pl, kod, pole", [
    ("fits", writeback.WriteOp("TELESCOP", "set", "Café", "str"),
     "wartość karty TELESCOP ma znak 'é' spoza drukowalnego ASCII - karta FITS go nie przyjmie, "
     "a w nagłówku XISF łamie XML 1.0", "card_value_chars", "value"),
    ("xisf", writeback.WriteOp("TELESCOP", "set", "ED", "str", comment="opisé"),
     "komentarz karty TELESCOP ma znak 'é' spoza drukowalnego ASCII - karta FITS go nie "
     "przyjmie, a w nagłówku XISF łamie XML 1.0", "card_comment_chars", "comment"),
    ("xisf", writeback.WriteOp("TELESCOP", "set", "ED", "str", comment="c" * 60),
     "komentarz karty TELESCOP ma 60 znaków, a przy tej wartości rekord FITS mieści 47",
     "card_comment_long", "comment"),
    ("fits", writeback.WriteOp("OBJECTNAM", "add", "x", "str"),
     "nazwa karty 'OBJECTNAM' łamie reguły FITS 4.0 - do 8 znaków spośród A-Z, 0-9, '_' i '-'",
     "card_name", "name"),
    ("xisf", writeback.WriteOp("TELESCOP", "set", "X" * 69, "str"),
     "wartość karty TELESCOP ma 69 znaków, a jeden rekord FITS mieści 68", "card_value_long",
     "value"),
], ids=["fits_znak_wartosci", "xisf_znak_komentarza", "xisf_dlugi_komentarz", "fits_nazwa",
        "xisf_dluga_wartosc"])
def test_naruszenie_reguly_karty_mowi_w_oknie_kodem(tmp_path, fmt, op, pl, kod, pole):
    """`_ops_violation` niesie `CardViolation.reason` - `PowodPozycji` z kodem `card_*` (oba
    formaty): PL znak w znak jak dawne zdanie reguły, EN po angielsku; pola naruszenia (`field`,
    `char`, `length`/`limit`) dla powierzchni mówiących własnym językiem."""
    pytest.importorskip("PySide6")
    from horreum import card_rules
    from test_writeback import _plik
    p = _plik(tmp_path, fmt)
    res = writeback.write_changes(str(p), [op], None)
    assert res.status == "blocked" and res.reason.code == kod, res
    assert str(res.reason) == pl
    _okno(res.reason)
    naruszenie = card_rules.card_violation(op.keyword, op.value, op.comment,
                                           new_card=op.op == "add")
    assert naruszenie.reason == res.reason and naruszenie.field == pole
    if kod in ("card_value_chars", "card_comment_chars"):
        assert naruszenie.char == "é" and naruszenie.kind == "chars"


# ============================================================ AR-166: suma kontrolna na obu drogach


def _fits_z_suma(path, seed=0):
    """FITS z poprawnymi kartami `CHECKSUM`/`DATASUM` (astropy `writeto(checksum=True)`)."""
    import numpy as np
    from astropy.io import fits
    hdu = fits.PrimaryHDU(data=(np.arange(64, dtype=np.int16).reshape(8, 8) + seed)
                          .astype(np.int16))
    hdu.header["IMAGETYP"] = "Light"
    hdu.header["OBJECT"] = ("NGC6992", "nazwa obiektu")
    hdu.writeto(path, checksum=True)
    return path


def _sumy_zgodne(path):
    import warnings
    from astropy.io import fits
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with fits.open(path) as h:
            return h[0].verify_checksum() == 1 and h[0].verify_datasum() == 1


def test_FITS_z_suma_odmowa_na_OBU_drogach_tym_samym_powodem(tmp_path):
    """AR-166 (sonda: droga atomowa `applied 1`, `verify_checksum` 0): FITS z sumą odmawia
    w OBU drogach tym samym powodem z nazwami kart, plik bajt w bajt, suma zgodna, bez backupu.
    Falsyfikator: zdejmij `_odmowa_sumy` z `write_changes` → 'applied', suma niezgodna."""
    p = _fits_z_suma(tmp_path / "s.fits")
    przed = p.read_bytes()
    op = [writeback.WriteOp("OBJECT", "set", "NGC 6992", "str", idx=0)]
    atom = writeback.write_changes(str(p), op, None)
    miejsce = writeback.write_changes_inplace(str(p), op, None)
    for res in (atom, miejsce):
        assert res.status == "blocked" and res.backup_text is None, res
        assert res.reason.code == "checksum_present", res
        assert dict(res.reason.params)["sums"] == ["CHECKSUM", "DATASUM"]
    assert str(atom.reason) == str(miejsce.reason)
    assert p.read_bytes() == przed and _sumy_zgodne(p)


@pytest.mark.parametrize("inplace", [True, False], ids=["szuflada_w_miejscu", "droga_atomowa"])
def test_szuflada_commit_FITS_z_suma_blokuje_bez_commit_id(tmp_path, inplace):
    """AR-166: op szuflady Zbiorów - zapis W MIEJSCU od AR-161 (`commit` = `commit_inplace`) - i droga
    atomowa rdzenia na FITS z sumą: 'blocked', commit bez `commit_id` (nic nie podmieniono), bez
    operacji w dzienniku zapisu w miejscu (odmowa przed dziennikiem), wpis stagingu niesie kod i nazwy
    kart (trójka 0042)."""
    from test_writeback_inplace import _baza_z_plikiem
    p = _fits_z_suma(tmp_path / "s.fits")
    przed = p.read_bytes()
    con, _ = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW, inplace=inplace)
    (fr,) = res.blocked
    assert not res.applied and res.commit_id is None and fr.reason.code == "checksum_present"
    (w,) = con.execute("SELECT status, reason_code, reason_args FROM pending_changes "
                       "WHERE run_id = 'R'")
    assert (w[0], w[1]) == ("blocked", "checksum_present")
    assert json.loads(w[2])["sums"] == ["CHECKSUM", "DATASUM"]
    assert con.execute("SELECT count(*) FROM inplace_op").fetchone()[0] == 0
    assert p.read_bytes() == przed and _sumy_zgodne(p)
    con.close()


def test_jedna_regula_sumy_dla_obu_drog():
    """AR-166: odmowę sumy mówi JEDEN predykat (`_odmowa_sumy`) - obie drogi FITS go wołają, a literał
    kodu `checksum_present` stoi w module raz. Falsyfikator: kopia literału w `_fits_inplace_plan`."""
    for fn in (writeback.write_changes, writeback._fits_inplace_plan):
        assert any(isinstance(w, ast.Call) and getattr(w.func, "id", None) == "_odmowa_sumy"
                   for w in ast.walk(ast.parse(inspect.getsource(fn)))), fn.__name__
    literaly = [w for w in ast.walk(ast.parse(inspect.getsource(writeback)))
                if isinstance(w, ast.Constant) and w.value == "checksum_present"]
    assert len(literaly) == 1, len(literaly)


# ============================================================ AR-168: błędy systemu klasą


_KLASY_WINERROR = [(5, "os_denied"), (19, "os_denied"), (65, "os_denied"), (2, "os_missing"),
                   (3, "os_missing"), (112, "os_no_space"), (39, "os_no_space"),
                   (64, "os_share_lost"), (59, "os_share_lost"), (53, "os_share_lost"),
                   (67, "os_share_lost"), (121, "os_share_lost"), (1231, "os_share_lost"),
                   (21, "os_share_lost")]


@pytest.mark.parametrize("winerror, kod", _KLASY_WINERROR, ids=[str(w) for w, _ in _KLASY_WINERROR])
def test_blad_systemu_klasa_po_winerror_przed_errno(winerror, kod):
    """AR-168: klasa po kodzie Windows - podklasa i errno CPythona tu kłamią: 53/67 (ścieżka
    sieciowa) to `FileNotFoundError`, 21 (urządzenie niegotowe) to `PermissionError`, 39 i błędy
    sieci to EINVAL (mapa CPythona z konstruktora `OSError`, numery z Microsoft Learn). Zdanie: fraza z numerem,
    surowy tekst systemu w `detail`. Falsyfikator: klasa po podklasie → 53 = `os_missing`."""
    exc = OSError(None, "komunikat systemu", r"X:\L\a.fits", winerror)
    powod = writeback._blad_systemu(exc)
    assert isinstance(powod, PowodPozycji) and powod.code == kod, (winerror, powod)
    p = dict(powod.params)
    assert p["os_code"] == f"WinError {winerror}" and p["detail"] == f"{type(exc).__name__}: {exc}"
    assert f"(WinError {winerror})" in powod


@pytest.mark.parametrize("nazwa, kod", [("EACCES", "os_denied"), ("EPERM", "os_denied"),
                                        ("ENOENT", "os_missing"), ("ENOSPC", "os_no_space")])
def test_blad_systemu_bez_winerror_po_errno(nazwa, kod):
    """AR-168: funkcje CRT (`open()`, plik tymczasowy, zapis strumienia) dają samo `errno` - klasa
    po nim. Falsyfikator: zdejmij `_OS_ERRNO` → ENOSPC surowo."""
    import errno
    exc = OSError(getattr(errno, nazwa), "komunikat")
    powod = writeback._blad_systemu(exc)
    assert isinstance(powod, PowodPozycji) and powod.code == kod, powod
    assert dict(powod.params)["os_code"] == f"Errno {exc.errno}"


@pytest.mark.parametrize("exc", [
    OSError(None, "zajęty", None, 32), OSError(None, "blokada", None, 33),
    OSError(None, "błąd urządzenia", None, 1117), OSError(None, "x", None, 1177),
    OSError(5, "I/O error"), OSError(22, "Invalid argument"), OSError("gołe"),
    ValueError("nie system")],
    ids=["32", "33", "1117", "1177", "EIO", "EINVAL", "gole", "ValueError"])
def test_nieznany_blad_systemu_zostaje_uczciwy(exc):
    """AR-168: błąd spoza klas zostaje tekstem systemu znak w znak (bez zmyślonego kodu), a kod
    Windows spoza tabeli NIE schodzi do errno - 32 to EACCES, byłby „odmową dostępu” zamiast
    zajętości, którą mówi `czytelny_powod`. Falsyfikator: zejście do errno przy nieznanym `winerror`."""
    assert writeback._blad_systemu(exc) == f"{type(exc).__name__}: {exc}"
    assert not isinstance(writeback._blad_systemu(exc), PowodPozycji)
    assert writeback._blad_systemu(exc, z_typem=False) == str(exc)


def test_kazdy_kod_systemu_w_oknie_PL_i_EN():
    """AR-168: każdy kod błędu systemu w oknie - PL = zdanie rdzenia, EN po angielsku z numerem
    i BEZ komunikatu systemu (ten jest w języku systemu i schodzi do podpowiedzi)."""
    pytest.importorskip("PySide6")
    for kod_win in (5, 2, 112, 64):
        powod = writeback._blad_systemu(OSError(None, "Odmowa dostępu", None, kod_win))
        _pl, en = _okno(powod)
        assert f"WinError {kod_win}" in en and "Odmowa" not in en, en


def test_plik_tylko_do_odczytu_mowi_kodem_na_obu_drogach_i_w_bazie(tmp_path):
    """AR-168 (wizytacja natywna): prawdziwy plik tylko do odczytu - obie drogi i commit przez
    bazę mówią kodem `os_denied` z numerem, a surowy tekst systemu zostaje w bazie (`reason_args`,
    pole `detail`). Falsyfikator: `_pod_blokada`/`write_changes` z gołym tekstem wyjątku."""
    import os
    import stat
    from test_writeback_inplace import _baza_z_plikiem, _fits
    p = _fits(tmp_path / "ro.fits")
    con, _ = _baza_z_plikiem(tmp_path, p)
    os.chmod(p, stat.S_IREAD)
    try:
        op = [writeback.WriteOp("OBJECT", "set", "NGC 6992", "str", idx=0)]
        for res in (writeback.write_changes(str(p), op, None),
                    writeback.write_changes_inplace(str(p), op, None)):
            assert res.status == "failed" and res.reason.code == "os_denied", res
            assert dict(res.reason.params)["os_code"] == "WinError 5"
        (fr,) = writeback.commit(con, "R", now=NOW).failed
        assert fr.reason.code == "os_denied"
        (w,) = con.execute("SELECT reason, reason_code, reason_args FROM pending_changes "
                           "WHERE run_id = 'R'")
        assert w[0] == str(fr.reason) and w[1] == "os_denied"
        assert json.loads(w[2])["detail"].startswith("PermissionError: [WinError 5]")
    finally:
        os.chmod(p, stat.S_IREAD | stat.S_IWRITE)
        con.close()


def test_brak_miejsca_i_zerwany_udzial_na_prawdziwej_drodze(tmp_path, monkeypatch):
    """AR-168: klasa z prawdziwej drogi pisarza - blokada pliku pada zerwanym udziałem
    (`ctypes.WinError(64)`), plik tymczasowy drogi atomowej brakiem miejsca (CRT: samo errno 28)."""
    import ctypes
    import errno
    from test_writeback_inplace import _fits
    p = _fits(tmp_path / "a.fits")
    op = [writeback.WriteOp("OBJECT", "set", "NGC 6992", "str", idx=0)]

    def _zerwany(path):
        raise ctypes.WinError(64)
    monkeypatch.setattr(writeback, "_exclusive", _zerwany)
    res = writeback.write_changes_inplace(str(p), op, None)
    assert res.status == "failed" and res.reason.code == "os_share_lost", res
    assert "WinError 64" in res.reason
    monkeypatch.undo()

    def _pelny(*a, **kw):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(writeback.tempfile, "mkstemp", _pelny)
    res = writeback.write_changes(str(p), op, None)
    assert res.status == "failed" and res.reason.code == "os_no_space", res
    assert "Errno 28" in res.reason


# Drogi plików, których powód widzi człowiek (AR-168, AR-184): plik → handlery łapiące błąd
# nie-systemowy (funkcja, typ handlera), które składają tekst z wyjątku - każdy z uzasadnieniem.
_DROGI_PLIKOW = {
    # parser XML łaty XISF: `ET.ParseError` to werdykt o bajtach, nie błąd systemu; `ValueError`
    # z tym zdaniem trafia do wyniku przez `_blad_systemu` w `write_xisf_changes` (surowo)
    "writeback.py": {("_xisf_verify", "ET.ParseError")},
    # właściciel: `powod_systemu`, `blad_systemu`; poza nim - powód odmowy KLINGI (`powod_wyjatku`:
    # `OdmowaZPowodem.powod` albo tekst odmowy, nie system) i nazwa TYPU wartości w komunikacie
    # EXPECT kodeka (`_do_slownika`, nie tekst wyjątku); `_surowy` - jedyne złożenie `Typ: opis`,
    # wołane wyłącznie przez właścicieli klas systemu i bazy (`powod_systemu`, `powod_bazy`, AR-198)
    # i regułę wyjątku okna (`powod_okna` - szczegół błędu programu, AR-214)
    "item_reasons.py": {("powod_wyjatku", None), ("_do_slownika", None), ("_surowy", None)},
    # `e` to etykieta zestawu w składaniu nazwy folderu (`zestawy_configow`), nie wyjątek
    "projection.py": {("zestawy_configow", None)},
    # `naming.stack_name` (segment siedziby pusty) i diagnoza czytnika żniw poza klasą błędu
    # systemu (odmowa parsera, `scan.nazwa_typu_diagnozy`) - handler czytnika pyta najpierw o klasę
    "harvest.py": {("_plan_stack", "ValueError"), ("plan", "Exception")},
    # odmowa klingi relacji wariantu i reguła formy folderu (`ValueError`) - nie system
    "stack_variants.py": {("link_from_testimonies", "ValueError"), ("_standalone_item", "ValueError")},
    "lead_copy.py": set(),
    # reguła formy folderu kanonu (`FolderFormError` z kodem i `ValueError`) - nie system
    "object_change.py": {("plan_object_change", "FolderFormError"), ("plan_object_change", "ValueError")},
    # strażnik korzenia klingi i sonda hardlinka mówią powodem z kodem (`powod_wyjatku`, AR-200)
    "gui/projection_dialog.py": set(),
    # workery spoza dróg zapisu (AR-198): Dostawa, teczki Domu, liczniki Porządków, planer, Pola
    # i skład zbioru - błąd systemu albo bazy klasą
    "gui/pipeline.py": set(),
    "gui/home.py": set(),
    "gui/tasks.py": set(),
    "gui/grid_workers.py": set(),
    # brak stanowiska (AR-48), błąd bazy i EXPECT rdzenia planera - jedną regułą `powod_okna` (AR-214)
    "gui/planner.py": set(),
    # ścieżka katalogu nieprzeczytanego (`errors_out` walkera, nie powód); właściciel DIAGNOZY odczytu
    # do `location.unreadable_reason` i `failed_paths` (P4-2, P4-6: kod Windows przed errno, bez
    # ścieżki); odmowy klingi rodzaju i generacji zapisu w miejscu
    "scan.py": {("_on_error", None), ("unreadable_reason_of", None),
                ("rederive_kinds", "repo.KindWitnessStale"),
                ("backfill_xisf_headers", "repo.StaleScanRecord")},
    # odmowy domeny w drukach CLI: baza nowsza (AR-69), stanowisko, wzór nazwy, korzeń wydania (§0),
    # dawca, werdykt sondy hardlinka, drzwi raportu, obserwatorium, klinga rodzaju, przebieg zmiany
    # obiektu, plan nagłówków; `streaks` - wiersz ASCII z kontraktu (typ + numer od właściciela)
    "cli.py": {("main", "db.SchemaTooNew"), ("_main", "ValueError"), ("_main", "ImportAbort"),
               ("_main", "projection.ProjectionAbort"), ("_cmd_streaks", "raport.RaportOdmowa"),
               ("_cmd_streaks", "OSError"), ("_cmd_observatory", "ValueError"),
               ("_cmd_rederive_kind", "repo.KindWitnessStale"), ("_cmd_object_change", "ValueError"),
               ("_cmd_header_fix", "ValueError")},
    # wspólny korzeń dawcy (`os.path.commonpath` - różne dyski) i odmowa generacji zapisu w miejscu
    "import_fitsmirror.py": {("preflight", "ValueError"), ("run_import", "repo.StaleScanRecord")},
    "gui/harvest_dialog.py": set(),
    "gui/wb_worker.py": set(),                     # wykonawca zapisu: wyjątek całej operacji (AR-185)
    # odmowa stagingu mówi powodem (`zdanie_odmowy_stagingu`, AR-200) - bez sklejki z wyjątku
    "gui/object_change_dialog.py": set(),
}
# `powod_okna` - reguła wyjątku okna (AR-209, AR-214): pyta `blad_systemu`, więc okno, które woła
# tylko ją, woła właściciela klasy
_WLASCICIEL = {"powod_systemu", "blad_systemu", "powod_okna"}
_SZEROKIE = {"Exception", "BaseException", "OSError"}
# Podklasy `OSError` - klasyfikacja nimi kłamie (53/67 to `FileNotFoundError`, 21 `PermissionError`)
_PODKLASY_OS = {"PermissionError", "FileNotFoundError", "FileExistsError", "IsADirectoryError",
                "NotADirectoryError", "ConnectionError", "TimeoutError", "BrokenPipeError",
                "InterruptedError", "BlockingIOError"}


def _drzewo_drogi(plik):
    from pathlib import Path
    import horreum
    return ast.parse((Path(horreum.__file__).parent / plik).read_text(encoding="utf-8"))


def test_meta_tekst_wyjatku_tylko_przez_blad_systemu():
    """AR-168, AR-184 (bramka zamiast wyliczanki): w drogach plików (`_DROGI_PLIKOW` - pisarz kart,
    projekcja, żniwa, wersje stosów, kopia wiodąca, planer zmiany obiektu i ich okna) tekst wyjątku
    staje się powodem WYŁĄCZNIE u właściciela (`item_reasons.powod_systemu`/`blad_systemu`) -
    f-string z `type(X).__name__`, f-string z gołym `{exc|exc2|err|e}` albo nazwą z `except … as N`,
    `str(exc|exc2|blad)` poza nim = czerwień. Wyjątki: handler błędu nie-systemowego z uzasadnieniem;
    handler szeroki (`Exception`/`OSError`) z wyjątku MUSI zapytać właściciela o klasę. Klasyfikacja
    podklasą `OSError` (`isinstance(x, FileNotFoundError)`) poza właścicielem = czerwień (AR-183).
    Każda droga woła właściciela, pisarz ≥ 45 razy. Falsyfikator: `f"{type(exc).__name__}: {exc}"`
    w `projection._link_to`, `isinstance(wynik, FileNotFoundError)` w `object_change`, handler
    czytnika `harvest.plan` bez `powod_systemu`."""
    poza, wolania = [], {}
    for plik, wyjatki in _DROGI_PLIKOW.items():
        drzewo = _drzewo_drogi(plik)
        rodzic = {d: n for n in ast.walk(drzewo) for d in ast.iter_child_nodes(n)}

        def _otoczenie(w):
            """(funkcja, typ najbliższego handlera `except` albo None, nazwy z `except … as N`)."""
            handler, nazwy = None, set()
            while w in rodzic:
                w = rodzic[w]
                if isinstance(w, ast.ExceptHandler):
                    if handler is None:
                        handler = ast.unparse(w.type) if w.type is not None else ""
                    if w.name:
                        nazwy.add(w.name)
                if isinstance(w, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return w.name, handler, nazwy
            return None, handler, nazwy
        for w in ast.walk(drzewo):
            funkcja, handler, nazwy = _otoczenie(w)
            u_wlasciciela = plik == "item_reasons.py" and funkcja in _WLASCICIEL
            if isinstance(w, ast.Call):
                nazwa = w.func.attr if isinstance(w.func, ast.Attribute) else getattr(w.func, "id", None)
                if nazwa in _WLASCICIEL or nazwa == "_blad_systemu":
                    wolania[plik] = wolania.get(plik, 0) + 1
                if (nazwa == "isinstance" and len(w.args) == 2 and not u_wlasciciela
                        and {getattr(n, "id", None) for n in ast.walk(w.args[1])} & _PODKLASY_OS):
                    poza.append(f"{plik}:{w.lineno}: klasa podklasą - {ast.unparse(w)[:70]}")
            typ = isinstance(w, ast.JoinedStr) and any(
                isinstance(v, ast.FormattedValue) and ast.unparse(v.value).startswith("type(")
                and ast.unparse(v.value).endswith(").__name__") for v in w.values)
            goly = isinstance(w, ast.JoinedStr) and any(
                isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name)
                and v.value.id in ({"exc", "exc2", "err", "e"} | nazwy) for v in w.values)
            tekst = (isinstance(w, ast.Call) and getattr(w.func, "id", None) == "str"
                     and len(w.args) == 1 and isinstance(w.args[0], ast.Name)
                     and w.args[0].id in ({"exc", "exc2", "blad"} | nazwy))
            if (typ or goly or tekst) and not u_wlasciciela and (funkcja, handler) not in wyjatki:
                poza.append(f"{plik}:{w.lineno}: {ast.unparse(w)[:80]}")
        # Handler szeroki z listy wyjątków składa tekst z wyjątku dopiero PO pytaniu o klasę.
        for w in ast.walk(drzewo):
            if not (isinstance(w, ast.ExceptHandler) and w.type is not None
                    and ast.unparse(w.type) in _SZEROKIE):
                continue
            funkcja = next((n.name for n in _przodkowie(rodzic, w)
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
            if (funkcja, ast.unparse(w.type)) in wyjatki and not any(
                    isinstance(c, ast.Call) and getattr(c.func, "id", None) in _WLASCICIEL
                    for c in ast.walk(w)):
                poza.append(f"{plik}:{w.lineno}: handler szeroki bez właściciela klasy")
    assert not poza, "\n".join(poza)
    assert wolania.get("writeback.py", 0) >= 45, wolania
    bez = [p for p in _DROGI_PLIKOW if p not in ("item_reasons.py", "writeback.py") and not wolania.get(p)]
    assert not bez, bez


def _przodkowie(rodzic, w):
    while w in rodzic:
        w = rodzic[w]
        yield w


def test_przerwane_cofniecie_w_miejscu_zostawia_surowy_szczegol_w_bazie(tmp_path, monkeypatch):
    """AR-168: kolumna prozowa `inplace_op.reason` nie ma `reason_args` - zdanie błędu
    systemu niesie za sobą surowy tekst systemu, więc diagnoza z bazy nie ginie razem z kodem.
    Prawdziwe cofnięcie w miejscu przerwane błędem systemu po pierwszym bajcie (`os.fsync`).
    Falsyfikator: `_faza` bez `_proza_z_diagnoza` → w bazie samo zdanie z numerem."""
    from test_writeback_inplace import _baza_z_plikiem, _fits
    p = _fits(tmp_path / "u.fits")
    con, _ = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.in_place) == 1, res

    def _fsync(fd):
        raise OSError(None, "Okreslona nazwa sieciowa jest juz niedostepna", None, 64)
    monkeypatch.setattr(writeback.os, "fsync", _fsync)
    u = writeback.undo(con, res.commit_id, now=NOW)
    monkeypatch.undo()
    (fr,) = u.failed
    assert writeback._szczegoly_systemu(fr.reason) == [
        "OSError: [WinError 64] Okreslona nazwa sieciowa jest juz niedostepna"]
    (op,) = con.execute("SELECT phase, reason FROM inplace_op WHERE kind = 'undo'")
    assert op["phase"] == "unverified", tuple(op)
    assert "udział sieciowy albo dysk nie odpowiada (WinError 64)" in op["reason"]
    assert op["reason"].endswith(" - OSError: [WinError 64] Okreslona nazwa sieciowa jest juz "
                                 "niedostepna"), op["reason"]
    con.close()


# ============================================================ AR-169: region sprzed commitu w miejscu


def _zewnetrzny_powrot(con, commit_id, path):
    """Region nagłówka z koperty backupu commitu wpisany z zewnątrz - plik wraca do stanu sprzed
    commitu bez Horreum (np. kopia z archiwum)."""
    (txt,) = con.execute("SELECT header_text FROM header_backups WHERE commit_id = ?",
                         (commit_id,)).fetchone()
    env = writeback.RegionBackup.decode(txt)
    with open(path, "r+b") as fh:
        fh.seek(env.offset)
        fh.write(env.region)
    return env


def _fits_dwa_hdu(path):
    """FITS z obrazem w głównym HDU (to wybiera skan) i drugim HDU z kartą `NOTE` - `sha1_data`
    nie widzi drugiego HDU."""
    import numpy as np
    from astropy.io import fits
    glowne = fits.PrimaryHDU(data=np.arange(64, dtype=np.int16).reshape(8, 8))
    glowne.header["IMAGETYP"] = "Light"
    glowne.header["OBJECT"] = ("NGC6992", "nazwa obiektu")
    drugie = fits.ImageHDU(data=np.zeros((2, 2), dtype=np.int16), name="EXTRA")
    drugie.header["NOTE"] = "aaaa"
    fits.HDUList([glowne, drugie]).writeto(path)
    return path


def test_region_sprzed_i_baza_sprzed_to_juz_cofniete(tmp_path):
    """AR-169: region nagłówka na dysku już sprzed commitu w miejscu, CAŁY plik = plik sprzed commitu
    (kotwica operacji), a baza opisuje ten plik (skan) → „już cofnięte” (`already`), cofnięcie
    domknięte, uchwyt znika; plik nietknięty. Falsyfikator: bez `juz=True` → `already == []`."""
    from test_writeback_inplace import _baza_z_plikiem, _fits, _scan_in
    p = _fits(tmp_path / "a.fits")
    przed = p.read_bytes()
    con, _ = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.in_place) == 1, res
    _zewnetrzny_powrot(con, res.commit_id, p)
    assert p.read_bytes() == przed
    _scan_in(con, p)
    u = writeback.undo(con, res.commit_id, now=NOW)
    assert u.blocked == u.already != [] and u.complete, u
    assert u.already[0].reason.code == "undo_already_region"
    assert p.read_bytes() == przed
    con.close()


def test_region_sprzed_a_baza_po_commicie_resync_z_pelnym_skutkiem(tmp_path):
    """AR-169: region i CAŁY plik sprzed commitu, baza jeszcze po commicie → re-sync
    z dowodem całego pliku: `header_hash` i `mtime` lokacji, karta `OBJECT` klatki, ta sama klatka
    (bez rozdwojenia), nagrobek ręki AR-38 odtworzony, bez nowego wstrzymania; drugie `undo` - „już
    cofnięte”, domknięte. Falsyfikator: `_baza_opisuje` zawsze prawdą → blokada zamiast re-syncu."""
    from horreum import scan
    from test_undo_nagrobek import _baza_z_nagrobkiem, _commit_karty, _ev, _stan
    import os
    con, p, lid, fid, cos = _baza_z_nagrobkiem(tmp_path)
    karta_przed = con.execute("SELECT value_raw FROM cards WHERE frame_id = ? AND "
                              "keyword = 'OBJECT'", (fid,)).fetchone()[0]
    res = _commit_karty(con, lid, "R", inplace=True)
    assert res.in_place and _stan(con, fid) == (None, None, None)        # commit zgasił nagrobek
    env = _zewnetrzny_powrot(con, res.commit_id, p)
    ramki = con.execute("SELECT count(*) FROM frame").fetchone()[0]
    wstrzymania = con.execute("SELECT count(*) FROM withheld_write").fetchone()[0]
    u = writeback.undo(con, res.commit_id, now=NOW)
    (fr,) = u.restored
    assert not u.blocked and not u.failed and u.complete, u
    assert fr.reason.code == "undo_sync_finished", fr.reason
    loc = con.execute("SELECT header_hash, mtime, frame_id FROM location WHERE id = ?",
                      (lid,)).fetchone()
    assert loc["header_hash"] == env.pre_hash and loc["mtime"] == scan._mtime_iso(os.stat(p))
    assert loc["frame_id"] == fid and con.execute("SELECT count(*) FROM frame").fetchone()[0] == ramki
    assert con.execute("SELECT value_raw FROM cards WHERE frame_id = ? AND keyword = 'OBJECT'",
                       (fid,)).fetchone()[0] == karta_przed
    assert _stan(con, fid) == (None, "user_cleared", cos) and _ev(con, "object.tombstone_restored") == 1
    assert con.execute("SELECT count(*) FROM withheld_write").fetchone()[0] == wstrzymania
    drugie = writeback.undo(con, res.commit_id, now=NOW)
    assert drugie.blocked == drugie.already != [] and drugie.complete, drugie
    con.close()


@pytest.mark.parametrize("skan", [False, True], ids=["baza_po_commicie", "baza_po_skanie"])
def test_region_sprzed_bez_dowodu_calego_pliku_nie_jest_juz_cofniety(tmp_path, skan):
    """AR-169 (falsyfikator dowodu): region głównego HDU sprzed commitu, ale DRUGIE HDU zmienione poza
    regionem (`sha1_data` bez zmian) - cały plik nie jest stanem sprzed commitu. Ani „już
    cofnięte”, ani re-sync: blokada z receptą skanu, cofnięcie NIEdomknięte (uchwyt zostaje), baza
    nietknięta - także po skanie, który wyrównał nagłówek. Falsyfikator: `_region_sprzed` bez
    kontroli danych → `already` (po skanie) albo `restored` (przed skanem)."""
    from test_writeback_inplace import _baza_z_plikiem, _scan_in
    p = _fits_dwa_hdu(tmp_path / "d.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.in_place) == 1, res
    _zewnetrzny_powrot(con, res.commit_id, p)
    bajty = bytearray(p.read_bytes())
    i = bajty.index(b"'aaaa ")                # wartość FITS dopełniona do 8 znaków
    bajty[i:i + 5] = b"'bbbb"
    p.write_bytes(bytes(bajty))
    if skan:
        _scan_in(con, p)
    sha1_data = con.execute("SELECT sha1_data FROM frame").fetchone()[0]
    naglowek = con.execute("SELECT header_hash FROM location").fetchone()[0]
    u = writeback.undo(con, res.commit_id, now=NOW)
    (fr,) = u.blocked
    assert u.already == [] and not u.complete and not u.restored, u
    assert fr.reason.code == "undo_region_unproven", fr.reason
    assert dict(fr.reason.params)["inner"].code == "check_outside_changed"
    assert con.execute("SELECT header_hash FROM location").fetchone()[0] == naglowek
    assert con.execute("SELECT count(*), max(sha1_data) FROM frame").fetchone()[:] == (1, sha1_data)
    con.close()


def test_juz_cofniete_jedna_regula_obu_drog():
    """AR-169, AR-182: „baza opisuje plik” to jedna reguła (`_baza_opisuje`) każdej drogi cofnięcia -
    trzy wołania: szybka ścieżka wyniku własnego drogi atomowej, dowód całego pliku
    (`_region_sprzed`, obie drogi commitu) i backup tekstowy bez śladu. Falsyfikator: kopia warunku
    `header_hash`/`mtime` w jednej gałęzi albo czwarte wołanie."""
    zrodlo = ast.parse(inspect.getsource(writeback._cofnij_lokacje))
    wolania = [w for w in ast.walk(zrodlo)
               if isinstance(w, ast.Call) and getattr(w.func, "id", None) == "_baza_opisuje"]
    assert len(wolania) == 3, len(wolania)


# ============================================================ AR-176: przerwane cofnięcie liczy resztę


@pytest.mark.parametrize("inplace", [False, True], ids=["atomowo", "w_miejscu"])
def test_przerwane_cofniecie_liczy_reszte_z_bazy(tmp_path, inplace):
    """AR-176 pkt 4 (sonda: ponowienie przerwane, a reszta już cofnięta, szuflada obiecywała
    „dokończy resztę”): rdzeń przy przerwaniu liczy z bazy, ile nieprzetworzonych backupów NIE ma
    trwałego dowodu zakończenia - przed pierwszym: wszystkie; po części: reszta; po pełnym
    cofnięciu: zero, bo dowód jest w obu drogach (operacja cofnięcia w miejscu zamknięta; ślad
    cofnięcia atomowego wciągnięty przez bazę, AR-182). Bez przerwania `None`. Falsyfikator:
    `remaining` z samej liczby nieprzetworzonych albo `_cofniecie_zakonczone` bez śladu → 2 zamiast 0."""
    from test_writeback_inplace import _fits, _loc, _scan_in, _stage
    con = db.open_db(str(tmp_path / "h.db"))
    for i in range(3):
        p = _fits(tmp_path / f"f{i}.fits", seed=i)
        _scan_in(con, p)
        _stage(con, "R", _loc(con, p)["id"], "NGC 6992", _loc(con, p)["header_hash"])
    res = writeback.commit(con, "R", now=NOW, inplace=inplace)
    assert len(res.applied) == 3 and res.commit_id is not None, res

    def _po(n):
        pytania = []

        def _pytaj():
            pytania.append(1)
            return len(pytania) > n
        return _pytaj
    przed = writeback.undo(con, res.commit_id, now=NOW, should_cancel=_po(0))
    assert przed.cancelled and przed.remaining == 3 and not przed.complete, przed
    czesc = writeback.undo(con, res.commit_id, now=NOW, should_cancel=_po(1))
    assert len(czesc.restored) == 1 and czesc.remaining == 2, czesc
    pelne = writeback.undo(con, res.commit_id, now=NOW)
    assert pelne.complete and pelne.remaining is None, pelne
    ponowione = writeback.undo(con, res.commit_id, now=NOW, should_cancel=_po(1))
    assert len(ponowione.already) == 1, ponowione
    assert ponowione.remaining == 0, ponowione
    con.close()


def test_przerwane_cofniecie_naglowek_wyrownany_skanem_to_nie_dowod_zakonczenia(tmp_path):
    """AR-176 pkt 4: plik po commicie w miejscu wrócił z zewnątrz do regionu sprzed commitu, ale ma
    zmienione DRUGIE HDU, a skan wyrównał `header_hash` lokacji - zgodny nagłówek NIE jest dowodem
    zakończenia cofnięcia (to cofnięcie odmówi: cały plik inny). Przerwanie przed pierwszym backupem
    liczy go jako wymagający sprawdzenia. Falsyfikator: `_cofniecie_zakonczone` po `header_hash` →
    `remaining` 0 i zdanie „nie wymagają cofnięcia”, a ponowienie i tak zwraca niedomknięte."""
    from test_writeback_inplace import _baza_z_plikiem, _scan_in
    p = _fits_dwa_hdu(tmp_path / "d.fits")
    con, _loc = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    _zewnetrzny_powrot(con, res.commit_id, p)
    bajty = bytearray(p.read_bytes())
    i = bajty.index(b"'aaaa ")
    bajty[i:i + 5] = b"'bbbb"
    p.write_bytes(bytes(bajty))
    _scan_in(con, p)
    przerwane = writeback.undo(con, res.commit_id, now=NOW, should_cancel=lambda: True)
    assert przerwane.cancelled and przerwane.remaining == 1, przerwane
    ponowione = writeback.undo(con, res.commit_id, now=NOW)
    assert not ponowione.complete and ponowione.blocked[0].reason.code == "undo_region_unproven"
    con.close()


@pytest.mark.parametrize("zmiana", [True, False], ids=["drugie_HDU_inne", "kopia_wierna"])
def test_region_sprzed_po_Fallback_tylko_z_dowodem_calego_pliku(tmp_path, zmiana):
    """AR-169: po commicie W MIEJSCU pod ścieżką staje KOPIA (inny `st_ino` → cofnięcie w miejscu
    spada na drogę atomową przez `Fallback`) z regionem sprzed commitu. Z innym drugim HDU - ani
    „już cofnięte”, ani re-sync: blokada bez dowodu, cofnięcie niedomknięte, baza nietknięta;
    kopia wierna - dowód całego pliku przechodzi, baza dociąga stan (`restored`, domknięte).
    Falsyfikator: gałąź atomowa po commicie w miejscu bez `_region_sprzed` → `restored` dla
    zmienionej kopii."""
    import os
    from test_writeback_inplace import _baza_z_plikiem
    p = _fits_dwa_hdu(tmp_path / "d.fits")
    przed = p.read_bytes()
    con, _ = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.in_place) == 1, res
    kopia = bytearray(przed)
    if zmiana:
        i = kopia.index(b"'aaaa ")
        kopia[i:i + 5] = b"'bbbb"
    nowy = tmp_path / "kopia.fits"
    nowy.write_bytes(bytes(kopia))
    ino = os.stat(p).st_ino
    os.replace(nowy, p)
    assert os.stat(p).st_ino != ino                  # inny plik pod ścieżką - `Fallback`
    naglowek = con.execute("SELECT header_hash FROM location").fetchone()[0]
    u = writeback.undo(con, res.commit_id, now=NOW)
    if zmiana:
        (fr,) = u.blocked
        assert fr.reason.code == "undo_region_unproven" and not u.already and not u.complete, u
        assert con.execute("SELECT header_hash FROM location").fetchone()[0] == naglowek
    else:
        assert len(u.restored) == 1 and u.complete, u
    con.close()


@pytest.mark.parametrize("inplace", [False, True], ids=["atomowo", "w_miejscu"])
def test_juz_cofniete_po_skanie_odtwarza_nagrobek_raz(tmp_path, inplace):
    """AR-169 / AR-38: commit karty `OBJECT` gasi nagrobek ręki; plik wraca z zewnątrz do stanu
    sprzed commitu, a skan wyrównuje bazę - skan nagrobka nie odtwarza. „Już cofnięte” rozlicza
    skutki cofnięcia w bazie tą samą klingą co re-sync (obie drogi): nagrobek wraca, cofnięcie
    domknięte; drugie `undo` bez dubli zdarzeń. Falsyfikator: `_blok(juz=True)` bez
    `_rozlicz_cofniecie_w_bazie` → „Cofnij” znika, wykluczenia ręki brak."""
    from test_undo_nagrobek import _baza_z_nagrobkiem, _commit_karty, _ev, _stan
    from test_writeback_inplace import _scan_in
    con, p, lid, fid, cos = _baza_z_nagrobkiem(tmp_path)
    przed = p.read_bytes()
    res = _commit_karty(con, lid, "R", inplace=inplace)
    assert _stan(con, fid) == (None, None, None)                     # commit zgasił nagrobek
    p.write_bytes(przed)                                             # powrót spoza Horreum
    _scan_in(con, p)
    assert _stan(con, fid) == (None, None, None)                     # skan nagrobka nie odtwarza
    u = writeback.undo(con, res.commit_id, now=NOW)
    assert u.blocked == u.already != [] and u.complete, u
    assert _stan(con, fid) == (None, "user_cleared", cos), _stan(con, fid)
    assert _ev(con, "object.tombstone_restored") == 1
    drugie = writeback.undo(con, res.commit_id, now=NOW)
    assert drugie.complete and _ev(con, "object.tombstone_restored") == 1, drugie
    con.close()


# ============================================================ AR-209, AR-214: reguła wyjątku okna


def _cantopen(tmp_path):
    """PRAWDZIWY `sqlite3.OperationalError` z kodem (SQLITE_CANTOPEN): baza w katalogu, którego nie ma."""
    import sqlite3
    try:
        sqlite3.connect(str(tmp_path / "brak" / "x.db"))
    except sqlite3.OperationalError as exc:
        return exc
    raise AssertionError("sqlite3.connect nie rzucił")


def test_powod_okna_odmowa_system_baza_i_blad_programu(tmp_path):
    """Jedna reguła wyjątku drogi okna (`item_reasons.powod_okna`): odmowa z powodem (klinga,
    strażnik korzenia, sonda hardlinka) → ten powód; błąd systemu i bazy → klasa, a spoza klas →
    tekst systemu jak dotąd; każdy inny wyjątek (goły `ValueError` rdzenia, wyjątek biblioteki,
    `KeyError`, `AssertionError`, `BrakStanowiska` bez powodu) → błąd programu `prog_error`, zdanie
    PL = wpis katalogu, surowy `Typ: opis` w `detail`. `prog_error` nie jest błędem systemu - poza
    `SYSTEM_REASON_CODES`. Falsyfikator: gałąź programu oddająca surowy tekst wyjątku."""
    from horreum import item_reasons, projection, targets
    from horreum.item_reasons import OdmowaZPowodem, powod_okna
    odmowa = PowodPozycji("pierwszy link nie przeszedł sondy tożsamości (i-węzeł/rozmiar/treść) - "
                          "wolumen nie wspiera hardlinków? włącz tryb kopii", "proj_first_link")
    assert powod_okna(OdmowaZPowodem(odmowa)) is odmowa
    assert powod_okna(projection.ProjectionAbort(odmowa, None)) is odmowa
    assert powod_okna(OSError(None, "Komunikat", r"X:\L\a.fits", 64)).code == "os_share_lost"
    assert powod_okna(OSError("dysk odpięty")) == "OSError: dysk odpięty"
    assert not isinstance(powod_okna(OSError("dysk odpięty")), PowodPozycji)
    assert powod_okna(_cantopen(tmp_path)).code == "db_unavailable"
    try:
        json.loads("{")
    except json.JSONDecodeError as exc:
        z_biblioteki = exc
    for exc in (ValueError("nieznany obiekt: 9"), z_biblioteki, KeyError("lights"),
                AssertionError("wersja stosu 7 bez oryginału"), targets.BrakStanowiska("brak GPS")):
        powod = powod_okna(exc)
        assert isinstance(powod, PowodPozycji) and powod.code == "prog_error", (exc, powod)
        assert str(powod) == CATALOG["objchg.item.prog_error"]["pl"]
        assert dict(powod.params) == {"detail": f"{type(exc).__name__}: {exc}"}
    assert "prog_error" in ITEM_REASON_CODES
    assert "prog_error" not in item_reasons.SYSTEM_REASON_CODES


# ============================================================ AR-232: odmowa łaty `add` z kodem podglądu


def test_pisarz_add_na_istniejacej_karcie_odmawia_kodem_podgladu(tmp_path):
    """AR-232: `add` karty, która już jest (wołający bez kotwicy stagingu) - 'blocked' z kodem
    bliźniaczym podglądu makra (`macro_add_exists`), zdanie PL = wpis katalogu, w oknie PL i EN; plik
    bajt w bajt, bez pliku tymczasowego obok. Dawniej 'failed' z prozą ASCII `ValueError: add: keyword
    … juz istnieje (uzyj set)`, choć plik był nietknięty.

    Falsyfikator: `_apply_op` z gołym `ValueError` albo `write_changes` bez wąskiego
    `except OdmowaZPowodem` → 'failed' z tekstem wyjątku."""
    pytest.importorskip("PySide6")
    from test_writeback_inplace import _fits
    p = _fits(tmp_path / "a.fits")
    przed = p.read_bytes()
    res = writeback.write_changes(str(p), [writeback.WriteOp("OBJECT", "add", "NGC 6992", "str")],
                                  None)
    assert res.status == "blocked" and res.backup_text is None, res
    assert res.reason.code == "macro_add_exists" and dict(res.reason.params) == {"keyword": "OBJECT"}
    assert str(res.reason) == CATALOG["objchg.item.macro_add_exists"]["pl"].format(keyword="OBJECT")
    _okno(res.reason)
    assert p.read_bytes() == przed and sorted(x.name for x in tmp_path.iterdir()) == ["a.fits"]


def test_commit_bez_kotwicy_add_na_istniejacej_karcie_blokuje_z_kodem_w_bazie(tmp_path):
    """AR-232 przez `commit` w miejscu (op szuflady i okien, AR-161) przy stagingu BEZ kotwicy
    `header_hash`: plan w miejscu oddaje spadek (`fb_card_present`), droga atomowa odmawia - wpis
    stagingu 'blocked' z kodem `macro_add_exists`, bez `commit_id`, bez operacji w dzienniku, plik
    nietknięty. Falsyfikator: odmowa jako wyjątek łapany szeroko → wpis 'failed' bez kodu."""
    from test_writeback_inplace import _fits, _loc, _scan_in
    p = _fits(tmp_path / "a.fits")
    przed = p.read_bytes()
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    repo.stage_pending(con, run_id="R", location_id=_loc(con, p)["id"], keyword="OBJECT", idx=None,
                       op="add", old_value=None, new_value="NGC 6992", new_type="str",
                       new_comment=None, expected_header_hash=None)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    (fr,) = res.blocked
    assert res.commit_id is None and fr.reason.code == "macro_add_exists", fr.reason
    (w,) = con.execute("SELECT status, reason_code FROM pending_changes WHERE run_id = 'R'")
    assert tuple(w) == ("blocked", "macro_add_exists")
    assert con.execute("SELECT count(*) FROM inplace_op").fetchone()[0] == 0
    assert p.read_bytes() == przed
    con.close()


@pytest.mark.parametrize("inplace", [True, False], ids=["w_miejscu", "atomowo"])
def test_wyscig_karty_po_stagingu_lapie_kotwica_naglowka(tmp_path, inplace):
    """AR-232: karta dopisana przez innego pisarza MIĘDZY stagingiem `add` a zapisem - obie drogi
    odmawiają kotwicą stagingu (`header_hash_mismatch`, sha1 całego nagłówka) jeszcze przed łatą,
    więc odmowa `macro_add_exists` pisarza dotyczy wyłącznie wołającego bez kotwicy; plik zostaje
    w wersji tamtego pisarza. Falsyfikator: kontrola `header_hash` zdjęta → odmowa łaty zamiast
    kotwicy."""
    from astropy.io import fits
    from test_writeback_inplace import _fits, _loc, _scan_in
    p = _fits(tmp_path / "a.fits")
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    loc = _loc(con, p)
    repo.stage_pending(con, run_id="R", location_id=loc["id"], keyword="OBJNAME", idx=None,
                       op="add", old_value=None, new_value="NGC 6992", new_type="str",
                       new_comment=None, expected_header_hash=loc["header_hash"])
    fits.setval(str(p), "OBJNAME", value="cudzy")
    po_cudzym = p.read_bytes()
    (fr,) = writeback.commit(con, "R", now=NOW, inplace=inplace).blocked
    assert fr.reason.code == "header_hash_mismatch", fr.reason
    assert p.read_bytes() == po_cudzym
    con.close()


# ============================================================ AR-242: błąd Windows ze ścieżką pliku


@pytest.mark.parametrize("err", [5, 2, 3, 32, 64, 1177])
def test_blad_windows_ta_sama_klasa_co_ctypes_i_ze_sciezka(err):
    """AR-242: `_blad_windows` daje tę samą podklasę, `errno`, `winerror` i klasę błędu systemu co
    `ctypes.WinError` - a do tego ścieżkę (`filename`) i tekst systemu bez kropki końcowej.
    Falsyfikator: `OSError` bez czwartego argumentu (`winerror`) → inna podklasa i klasa."""
    import ctypes
    from horreum.item_reasons import powod_systemu
    sciezka = r"X:\L\a.fits"
    stary, nowy = ctypes.WinError(err), writeback._blad_windows(err, sciezka)
    assert (type(nowy), nowy.errno, nowy.winerror) == (type(stary), stary.errno, stary.winerror)
    assert getattr(powod_systemu(nowy), "code", None) == getattr(powod_systemu(stary), "code", None)
    assert nowy.filename == sciezka and not nowy.strerror.endswith(".")
    assert str(nowy).endswith(f": {sciezka!r}"), str(nowy)


def test_odmowa_blokady_niesie_nazwe_pliku_na_obu_drogach_i_w_bazie(tmp_path):
    """AR-242: prawdziwy plik tylko do odczytu - blokada pliku
    (`_exclusive`) odmawia `PermissionError` z kodem 5 i ŚCIEŻKĄ; obie drogi zapisu i commit przez
    bazę mówią klasą `os_denied`, a surowy szczegół (wynik i `reason_args` w bazie) niesie nazwę
    pliku. Dawniej `[WinError 5] Odmowa dostępu.` bez ścieżki.
    Falsyfikator: `_exclusive` z `ctypes.WinError(err)`."""
    import os
    import stat
    from test_writeback_inplace import _baza_z_plikiem, _fits
    p = _fits(tmp_path / "ro.fits")
    con, _ = _baza_z_plikiem(tmp_path, p)
    os.chmod(p, stat.S_IREAD)
    try:
        with pytest.raises(PermissionError) as blad:
            with writeback._exclusive(str(p)):
                pass
        assert blad.value.winerror == 5 and blad.value.filename == str(p)
        op = [writeback.WriteOp("OBJECT", "set", "NGC 6992", "str", idx=0)]
        for res in (writeback.write_changes(str(p), op, None),
                    writeback.write_changes_inplace(str(p), op, None)):
            assert res.status == "failed" and res.reason.code == "os_denied", res
            assert repr(str(p)) in dict(res.reason.params)["detail"], res.reason.params
        (fr,) = writeback.commit(con, "R", now=NOW, inplace=True).failed
        assert fr.reason.code == "os_denied"
        (w,) = con.execute("SELECT reason_args FROM pending_changes WHERE run_id = 'R'")
        assert repr(str(p)) in json.loads(w[0])["detail"]
    finally:
        os.chmod(p, stat.S_IREAD | stat.S_IWRITE)
        con.close()


def test_blad_podmiany_systemowej_niesie_sciezke(tmp_path):
    """AR-242: `ReplaceFileW` bez pliku zastępującego - `FileNotFoundError` z kodem 2 i ścieżką pliku
    archiwum (`filename`), plik nietknięty, kopia nie powstaje.
    Falsyfikator: `_replace_file_w` z `ctypes.WinError` → `filename` None."""
    p = tmp_path / "p.fits"
    p.write_bytes(b"P" * 2880)
    kopia = tmp_path / "p.fits.k.horreum-kopia"
    with pytest.raises(FileNotFoundError) as blad:
        writeback._replace_file_w(str(p), str(tmp_path / "brak.tmp"), str(kopia))
    assert blad.value.winerror == 2 and blad.value.filename == str(p)
    assert p.read_bytes() == b"P" * 2880 and not kopia.exists()


def test_szczegol_odmowy_w_oknie_niesie_sciezke_bez_repr():
    """AR-242: wiersz „Szczegół systemu” okna (`wiersz_systemu`) pokazuje plik, który padł - ścieżką
    bez podwojonych ukośników zapisu `repr`. Falsyfikator: błąd bez ścieżki → wiersz bez pliku."""
    pytest.importorskip("PySide6")
    from horreum.gui.wb_worker import wiersz_systemu
    sciezka = r"X:\L\a.fits"
    wiersz = wiersz_systemu(writeback._blad_systemu(writeback._blad_windows(5, sciezka)))
    assert f"'{sciezka}'" in wiersz and "\\\\" not in wiersz, wiersz
