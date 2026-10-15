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
    XISF) odmawia kodem `undo_header_changed`, a proza zostaje „header_hash mismatch” znak w znak.
    Zapis (`write_changes`) na tym samym pliku mówi kodem zapisu (od stagingu)."""
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
    assert str(res.reason) == str(zapis.reason) == "header_hash mismatch"


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
