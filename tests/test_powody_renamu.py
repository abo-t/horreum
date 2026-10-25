"""Powody podglądu renamu i błędy wzoru nazwy z KODEM (AR-193): każde miejsce, w którym `naming`
rodzi powód pominięcia klatki (`SkippedRename.reason`, problem `compose_name`/`resolve_dt`/
`_flatgrp_segment`) albo odmowę wzoru (`validate_template`, `compose_name`), oddaje `PowodPozycji` -
zdanie PL znak w znak jak dotąd (CLI, testy, sklejenia biorą je jak tekst), kod `rename_*`
i parametry, a okno mówi je w języku UI (`gui.wb_worker.tekst_powodu`).

Test złoty: zdanie PL każdej drogi jest LITERAŁEM sprzed kodów (jedyna zmiana znaku: pauza
w zdaniu kolizji → dywiz) i zdanie EN jest DOKŁADNE. Bramka AST pilnuje, że w `naming` nie wraca
goła proza powodu - także zapasowa (`powod or "..."`): brak powodu to złamany inwariant (EXPECT)."""
import ast
import inspect
from datetime import datetime

import pytest

from horreum import naming
from horreum.item_reasons import PowodPozycji

SHA = "abc123def456789000"
DT = datetime(2026, 8, 8, 21, 58, 45)
MASTER = r"X:\C\MASTERFLAT_FLATGRP_202511010_FILTER_OIII_.xisf"
MASTER_INNY = r"X:\C\MASTERFLAT_FLATGRP_202511011_FILTER_OIII_.xisf"


def _wiersz(**kw):
    """Wiersz `queries.rename_frame_targets` jednej klatki z jedną obecną kopią."""
    w = {"frame_id": 1, "filetype": "fits", "kind": "light", "filter_canon": "Ha", "sha1_data": SHA,
         "object_canon": "NGC7000", "object_raw": None, "date_obs": "2024-03-15T21:30:45",
         "exptime": 300.0, "location_id": 10, "path": r"X:\L\stara.fits", "mtime": "111"}
    w.update(kw)
    return w


def _pominiecie(wiersze, ids=(1,), **polityka):
    """Powód pominięcia jedynej klatki przebiegu `run_rename` nad `wiersze`."""
    po_klatce = {}
    for w in wiersze:
        po_klatce.setdefault(w["frame_id"], []).append(w)
    run = naming.run_rename(list(ids), targets_fn=lambda i: [w for f in i for w in po_klatce.get(f, [])],
                            **{"source": "date_obs", "offset_hours": 0, **polityka})
    assert not run.touched, run.touched
    return run.skipped[0].reason


def _fakty(**kw):
    f = {"kind": "light", "object_canon": "CTB1", "filter_canon": "OIII", "exptime": 300.0,
         "sha1_data": SHA, "ext": ".fits", "path": r"X:\L\a.fits", "flat_master_id": 7,
         "flat_paths": [MASTER]}
    f.update(kw)
    return f


def _problem(fakty, wzor=("kind", "flatgrp"), dt=DT):
    nazwa, problem = naming.compose_name(fakty, dt, template=list(wzor))
    assert nazwa is None, nazwa
    return problem


def _odmowa_wzoru(wywolanie):
    with pytest.raises(ValueError) as info:
        wywolanie()
    return info.value.powod


def _pusta_grupa(monkeypatch):
    monkeypatch.setattr(naming, "parse_master_path", lambda path: {"flatgrp": "<>"})
    return naming._flatgrp_segment({"flat_master_id": 1, "flat_paths": [MASTER]})[1]


_KANON = r"X:\L\20240315_213045_NGC7000_light_Ha_300s_abc123def456.fits"

# (droga, powód z prawdziwego wywołania - `monkeypatch` dla jednej drogi, kod, zdanie PL, zdanie EN)
_DROGI = [
    ("resolve_dt bez źródła (bez fallbacku)",
     lambda mp: _pominiecie([_wiersz(date_obs=None)], fallback=False), "rename_no_time_source",
     "brak źródła czasu 'date_obs'", "no time source 'date_obs'"),
    ("compose_name bez daty", lambda mp: _problem(_fakty(), wzor=("datetime",), dt=None),
     "rename_no_datetime", "brak rozstrzygniętej daty-godziny", "no resolved date and time"),
    ("flatgrp master bez kopii", lambda mp: _problem(_fakty(flat_paths=[])), "rename_flat_no_copy",
     "flat podpięty, ale master bez obecnej kopii", "flat linked, but the master has no present copy"),
    ("flatgrp nazwa bez tokenu", lambda mp: _problem(_fakty(flat_paths=[r"X:\C\MasterFlat_OIII.xisf"])),
     "rename_flat_no_group", "brak FLATGRP w nazwie mastera flat: MasterFlat_OIII.xisf",
     "no FLATGRP in the master flat name: MasterFlat_OIII.xisf"),
    ("flatgrp pusta grupa", _pusta_grupa, "rename_flat_empty_group",
     "pusta grupa FLATGRP w nazwie mastera flat: MASTERFLAT_FLATGRP_202511010_FILTER_OIII_.xisf",
     "empty FLATGRP group in the master flat name: MASTERFLAT_FLATGRP_202511010_FILTER_OIII_.xisf"),
    ("flatgrp różne grupy", lambda mp: _problem(_fakty(flat_paths=[MASTER, MASTER_INNY])),
     "rename_flat_many_groups", "kopie mastera flat o różnych grupach: 202511010, 202511011",
     "master flat copies with different groups: 202511010, 202511011"),
    ("_resolve_target bez obecnej kopii", lambda mp: _pominiecie([_wiersz(location_id=None)]),
     "rename_no_present_copy", "brak obecnej kopii do renamu (wszystkie present=0)",
     "no present copy to rename (all present=0)"),
    ("_resolve_target wiele kopii",
     lambda mp: _pominiecie([_wiersz(), _wiersz(location_id=11, path=r"X:\M\stara.fits")]),
     "rename_many_copies", "wiele obecnych kopii (2) -- rename multi-location poza v1",
     "several present copies (2) - multi-location rename is outside v1"),
    ("run_rename klatka znikła", lambda mp: _pominiecie([]), "rename_frame_gone",
     "frame nieobecny w bazie", "frame missing from the database"),
    ("run_rename oba źródła czasu puste",
     lambda mp: _pominiecie([_wiersz(date_obs=None, path=r"X:\L\bez_czasu.fits")]), "rename_no_time",
     "brak DATE-OBS ani czasu w nazwie", "no DATE-OBS and no time in the name"),
    ("run_rename nazwa bez zmian", lambda mp: _pominiecie([_wiersz(path=_KANON)]), "rename_unchanged",
     "nazwa bez zmian", "name unchanged"),
    ("run_rename kolizja w wsadzie",
     lambda mp: _pominiecie([_wiersz(), _wiersz(frame_id=2, location_id=11, path=r"X:\L\druga.fits")],
                            ids=(1, 2)),
     "rename_collision",
     "kolizja nazwy w wsadzie: 20240315_213045_NGC7000_light_Ha_300s_abc123def456.fits - dodaj token "
     "disc lub zmień wzór",
     "name collision in the batch: 20240315_213045_NGC7000_light_Ha_300s_abc123def456.fits - add the "
     "disc token or change the pattern"),
    ("validate_template zły regex",
     lambda mp: _odmowa_wzoru(lambda: naming.validate_template([{"t": "orig", "re": "("}])),
     "rename_tpl_bad_regex",
     "zły regex w tokenie 'orig': '(' (missing ), unterminated subpattern at position 0)",
     "bad regex in token 'orig': '(' (missing ), unterminated subpattern at position 0)"),
    ("validate_template trail nie na końcu",
     lambda mp: _odmowa_wzoru(lambda: naming.validate_template(["trail", "kind"])),
     "rename_tpl_trail_not_last", "token 'trail' musi być ostatni we wzorze",
     "the 'trail' token must be last in the pattern"),
    ("compose_name trail nie na końcu",
     lambda mp: _odmowa_wzoru(lambda: naming.compose_name(_fakty(), DT, template=["trail", "kind"])),
     "rename_tpl_trail_not_last", "token 'trail' musi być ostatni we wzorze",
     "the 'trail' token must be last in the pattern"),
    ("validate_template wielkość liter",
     lambda mp: _odmowa_wzoru(lambda: naming.validate_template([{"t": "kind", "case": "title"}])),
     "rename_tpl_bad_case", "nieznana wielkość liter tokenu 'kind': 'title'",
     "unknown letter case for token 'kind': 'title'"),
    ("compose_name wielkość liter",
     lambda mp: _odmowa_wzoru(lambda: naming.compose_name(_fakty(), DT,
                                                          template=[{"t": "kind", "case": "title"}])),
     "rename_tpl_bad_case", "nieznana wielkość liter tokenu 'kind': 'title'",
     "unknown letter case for token 'kind': 'title'"),
    ("compose_name nieznany token",
     lambda mp: _odmowa_wzoru(lambda: naming.compose_name(_fakty(), DT, template=["planeta"])),
     "rename_tpl_unknown_token", "nieznany token szablonu: 'planeta'", "unknown pattern token: 'planeta'"),
    ("validate_template nieznany token",
     lambda mp: _odmowa_wzoru(lambda: naming.validate_template(["datetime", "planeta"])),
     "rename_tpl_unknown_token", "nieznany token szablonu: 'planeta'", "unknown pattern token: 'planeta'"),
]
_IDS = [d[0] for d in _DROGI]


@pytest.mark.parametrize("droga, wywolanie, kod, pl, _en", _DROGI, ids=_IDS)
def test_ZLOTE_powody_renamu_PL_znak_w_znak_z_kodem(monkeypatch, droga, wywolanie, kod, pl, _en):
    """Każda droga rodzenia powodu i odmowy wzoru w `naming`: zdanie PL = literał sprzed kodów,
    `PowodPozycji` z kodem drogi. Falsyfikator: miejsce z gołym f-stringiem albo znak zdania
    zmieniony (`--` → `-` w zdaniu wielu kopii)."""
    powod = wywolanie(monkeypatch)
    assert str(powod) == pl, (droga, str(powod))
    assert isinstance(powod, PowodPozycji) and powod.code == kod, (droga, powod)


@pytest.mark.parametrize("droga, wywolanie, kod, pl, en", _DROGI, ids=_IDS)
def test_powody_renamu_mowia_w_UI_PL_znak_w_znak_a_EN_dokladnie(monkeypatch, droga, wywolanie, kod, pl,
                                                                en):
    """Okno (podpowiedź „(pominięto)”, pasek błędu wzoru) mówi powód w języku UI: PL = zdanie
    rdzenia, EN = DOKŁADNE zdanie katalogu (tekst `re.error` Pythona znak w znak). Falsyfikator:
    wpis EN = kopia PL albo powód bez kodu → PL w EN."""
    pytest.importorskip("PySide6")
    from horreum.gui import i18n
    from horreum.gui.wb_worker import tekst_powodu
    powod = wywolanie(monkeypatch)
    try:
        i18n.set_lang("pl")
        assert tekst_powodu(powod) == pl, (droga, tekst_powodu(powod))
        i18n.set_lang("en")
        assert tekst_powodu(powod) == en, (droga, tekst_powodu(powod))
    finally:
        i18n.set_lang("pl")


def test_odmowa_wzoru_zostaje_ValueError_z_dawnym_zdaniem():
    """Błąd wzoru to `OdmowaZPowodem` - dalej `ValueError` z tym samym `str` (CLI `rename` łapie go
    jak dotąd i drukuje `błąd wzoru nazwy: …`)."""
    with pytest.raises(ValueError, match=r"^token 'trail' musi być ostatni we wzorze$") as info:
        naming.validate_template({"light": ["kind", "trail", "exp"]})
    assert info.value.powod.code == "rename_tpl_trail_not_last"


def test_meta_powody_renamu_bez_golej_prozy():
    """Bramka AST (żeby nie wracało): w `naming` drugi element krotki `return` (problem), trzeci
    argument `SkippedRename` (powód pominięcia) i argument `raise` w `validate_template`/`compose_name`
    nie są literałem, f-stringiem ani zapasem `x or "<literał>"`. Falsyfikator: `"nazwa bez zmian"`
    z powrotem jako goły literał albo `reason or ""` w pominięciu bez celu."""
    drzewo = ast.parse(inspect.getsource(naming))
    rodzic = {d: n for n in ast.walk(drzewo) for d in ast.iter_child_nodes(n)}

    def _funkcja(w):
        while w in rodzic:
            w = rodzic[w]
            if isinstance(w, ast.FunctionDef):
                return w.name
        return None

    def _goly(v):
        if isinstance(v, ast.JoinedStr) or (isinstance(v, ast.Constant) and isinstance(v.value, str)):
            return True
        return isinstance(v, ast.BoolOp) and any(_goly(x) for x in v.values)
    gole, pominiecia = [], 0
    for w in ast.walk(drzewo):
        if isinstance(w, ast.Return) and isinstance(w.value, ast.Tuple) and len(w.value.elts) == 2:
            if _goly(w.value.elts[1]):
                gole.append(f"{w.lineno}: {ast.unparse(w)[:80]}")
        if isinstance(w, ast.Call) and getattr(w.func, "id", None) == "SkippedRename":
            pominiecia += 1
            if _goly(w.args[2]):
                gole.append(f"{w.lineno}: {ast.unparse(w)[:80]}")
        if (isinstance(w, ast.Raise) and _funkcja(w) in ("validate_template", "compose_name")
                and not (isinstance(w.exc, ast.Call) and getattr(w.exc.func, "id", None) == "OdmowaZPowodem")):
            gole.append(f"{w.lineno}: {ast.unparse(w)[:80]}")
    assert pominiecia == 6, pominiecia
    assert not gole, "\n".join(gole)


def test_cli_rename_DRY_mowi_proza_PL_znak_w_znak():
    """CLI drukuje powody pominięć jak dotąd - `str(PowodPozycji)` to zdanie PL rdzenia; dwa powody
    o tym samym zdaniu (i kodzie) liczą się w jednym wierszu."""
    from types import SimpleNamespace
    from horreum import cli
    skipped = [naming.SkippedRename(1, "", PowodPozycji("nazwa bez zmian", "rename_unchanged")),
               naming.SkippedRename(2, "", PowodPozycji("nazwa bez zmian", "rename_unchanged")),
               naming.SkippedRename(3, "", PowodPozycji("frame nieobecny w bazie", "rename_frame_gone"))]
    tekst = cli._format_rename_dry("h.db", SimpleNamespace(touched=[], skipped=skipped), limit=5)
    wiersze = tekst.splitlines()
    assert "    pominieto 2: nazwa bez zmian" in wiersze, wiersze
    assert "    pominieto 1: frame nieobecny w bazie" in wiersze, wiersze


def test_cli_rename_zly_regex_pelne_zdanie_kod_2_zero_mutacji(tmp_path, capsys):
    """CLI `rename` ze złym regexem `orig`: PEŁNE zdanie PL znak w znak, kod wyjścia 2, pliki
    nietknięte - odmowa wzoru z kodem nie zmienia wydruku CLI."""
    from horreum import cli
    from test_cli_rename import _seed
    dbp, pliki = _seed(tmp_path)
    przed = {p: p.read_bytes() for p in pliki}
    rc = cli.main(["rename", str(dbp), "--template-json", '[{"t": "orig", "re": "("}]'])
    assert rc == 2
    assert capsys.readouterr().out.splitlines() == [
        "Horreum rename: błąd wzoru nazwy: zły regex w tokenie 'orig': '(' (missing ), unterminated "
        "subpattern at position 0)"]
    assert all(p.exists() and p.read_bytes() == b for p, b in przed.items())
