"""Łańcuch etapów pochodnych z jednego rdzenia (AR-39) i backstop wjazdu importu (AR-46).

Parytet: GUI (gest bez skanu i Dostawa), CLI `presence --apply` i import z dawcy wołają etapy
pochodne w kolejności `derive.DERIVED_STAGES` - mierzone na wołaniach funkcji rdzenia, nie na
etykietach sygnałów, więc lista w którejś drodze, która ominie rdzeń, czerwieni test.
"""
import ast
import json
import os
from pathlib import Path

import pytest

from horreum import calibration, cli, db, derive, grouper, lineage, repo, resolver, scan, stacks
from horreum import import_fitsmirror as imp
from horreum.import_fitsmirror import ImportAbort, import_fitsmirror

from test_import_fitsmirror import NOW, SPECS, _mk_donor

PKG = Path(__file__).resolve().parent.parent / "horreum"
KANON = ["group", "resolve", "calibrate", "lineage", "stack_lineage"]
_FUNKCJE = {"run_grouper", "run_resolver", "run_calibration", "run_lineage", "run_stack_lineage"}


@pytest.fixture(autouse=True)
def historia_bez_dysku(monkeypatch):
    """Rodowód stosów czyta nagłówek XISF spod ścieżki stosu - w testach atrapa, zero odczytu
    z dysku (ścieżki dawcy i fikstur mogą wskazywać udział sieciowy)."""
    monkeypatch.setattr(stacks, "_read_history_xml", lambda _p: None)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def wolania(monkeypatch):
    """Podsłuch funkcji rdzenia etapów pochodnych (w ich modułach - rdzeń woła przez moduł)."""
    log = []
    for mod, nazwa, etap in ((grouper, "run_grouper", "group"),
                             (resolver, "run_resolver", "resolve"),
                             (calibration, "run_calibration", "calibrate"),
                             (lineage, "run_lineage", "lineage"),
                             (stacks, "run_stack_lineage", "stack_lineage")):
        prawdziwa = getattr(mod, nazwa)

        def _f(*a, _p=prawdziwa, _e=etap, **kw):
            log.append(_e)
            return _p(*a, **kw)
        monkeypatch.setattr(mod, nazwa, _f)
    return log


@pytest.fixture
def przejecie(monkeypatch):
    """Jedna klatka do przejęcia zeznania, przejęta (pochodne w gestach ruszają tylko wtedy)."""
    monkeypatch.setattr(scan, "copy_facts_candidates", lambda con, root=None: [])
    monkeypatch.setattr(scan, "adopt_candidates", lambda con, root=None: [1])
    monkeypatch.setattr(scan, "adopt_orphan_testimony",
                        lambda con, **kw: scan.AdoptSummary(rows=1, adopted=1))


def _baza(tmp_path):
    path = str(tmp_path / "h.db")
    db.open_db(path).close()
    return path


def test_kanon_kolejnosci_pochodnych():
    """Kolejność nie jest gustem: kalibracja po resolverze (`filter_canon`), rodowód po kalibracji
    (profile), rodowód stosów na końcu (okno stoi na osiach obiektu i teleskopu, AR-85).
    Falsyfikator: zamień dwa wpisy `DERIVED_STAGES` → test pada."""
    assert [n for n, _ in derive.DERIVED_STAGES] == KANON
    assert list(derive.DERIVED) == KANON


def test_rdzen_pomija_pochodne_bez_przejecia_chyba_ze_zawsze(tmp_path, wolania, monkeypatch):
    monkeypatch.setattr(scan, "copy_facts_candidates", lambda con, root=None: [])
    monkeypatch.setattr(scan, "adopt_candidates", lambda con, root=None: [])
    con = db.open_db(_baza(tmp_path))
    try:
        assert list(derive.adopt_and_derive(con, None, NOW)) == []
        assert wolania == []
        pary = list(derive.adopt_and_derive(con, None, lambda: NOW, derive_always=True))
        assert [n for n, _ in pary] == KANON and wolania == KANON
    finally:
        con.close()


def test_parytet_gui_gest_bez_skanu(qapp, tmp_path, wolania, przejecie):
    from horreum.gui.pipeline import PipelineWorker
    w = PipelineWorker(_baza(tmp_path), now_fn=lambda: NOW)
    w.configure("copy_facts")
    started, done, failed = [], [], []
    w.stage_started.connect(started.append)
    w.stage_done.connect(lambda n, s: done.append(n))
    w.failed.connect(lambda n, m: failed.append((n, m)))
    w.run()
    assert failed == []
    assert wolania == KANON
    assert started == done == ["adopt_testimony"] + KANON     # sygnał po elemencie, w kolejności


def test_parytet_gui_dostawa(qapp, tmp_path, wolania, przejecie):
    from horreum.gui.pipeline import PipelineWorker
    root = tmp_path / "ARCH"
    root.mkdir()
    w = PipelineWorker(_baza(tmp_path), now_fn=lambda: NOW)
    w.configure("all", root=str(root), volume="?", drive_letter=None, tier=None)
    done, failed = [], []
    w.stage_done.connect(lambda n, s: done.append(n))
    w.failed.connect(lambda n, m: failed.append((n, m)))
    w.run()
    assert failed == []
    assert wolania == KANON
    assert done == ["scan", "adopt_testimony"] + KANON + ["delta", "presence"]


def test_parytet_cli_ogon_obecnosci(tmp_path, wolania, przejecie):
    con = db.open_db(_baza(tmp_path))
    try:
        wiersze = list(cli._presence_tail(con, None, now=NOW))
    finally:
        con.close()
    assert wolania == KANON
    assert [w.split(":")[0].strip() for w in wiersze[1:]] == KANON
    assert wiersze[0].startswith("  przejecie zeznania ocalalej kopii: przejete 1 z 1")


def test_parytet_import_z_dawcy(tmp_path, wolania):
    donor_path, _ = _mk_donor(tmp_path, SPECS)
    s = import_fitsmirror(str(donor_path), str(tmp_path / "horreum.db"), now=NOW, rng_seed=1)
    assert s.gate_failures == []
    assert wolania == KANON
    assert None not in (s.group, s.resolve, s.calibration, s.lineage, s.stack_lineage)
    assert "rodowod stosow:" in cli._format_import(str(donor_path), "h.db", s)


def test_poza_rdzeniem_nikt_nie_lancuchuje_pochodnych():
    """Strażnik nawrotu czwartej kopii: funkcje etapów pochodnych woła wyłącznie rdzeń (`derive`)
    i pojedyncze komendy CLI (`main`, jedna gałąź = jeden etap). Falsyfikator: wpisz w
    `import_fitsmirror.run_import` `grouper.run_grouper(con, now)` → test wskazuje plik i funkcję."""
    naruszenia = []
    for src in sorted(PKG.rglob("*.py")):
        rel = src.relative_to(PKG).as_posix()
        if rel == "derive.py":
            continue
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if rel == "cli.py" and fn.name == "main":
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    f = node.func
                    nazwa = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
                    if nazwa in _FUNKCJE:
                        naruszenia.append(f"{rel}:{fn.name}:{node.lineno} {nazwa}")
    assert naruszenia == [], naruszenia


# --- AR-85: rodowód stosów w Dostawie ----------------------------------------------------------

_LATER = "2026-07-02T13:00:00+00:00"
_LATEST = "2026-07-02T14:00:00+00:00"
_ZAPIS_STOSOW = ("integration.recorded", "integration.updated", "integration.linked",
                 "integration.unlinked")


def _stos_bez_obiektu(con, tmp_path):
    """Stos, którego `OBJECT` żaden szczebel resolvera nie rozpozna, i dwa lighty jego nocy
    z obiektem już nadanym. Zeznania pełne (kamera, teleskop), żeby `group` i `resolve` Dostawy
    liczyły na nich naprawdę, a nie przechodziły obok pustych nagłówków."""
    def _klatka(sha1, kind, filetype, raw, path):
        fid = con.execute(
            "INSERT INTO frame(sha1_data, kind, filetype, first_seen_at) VALUES (?, ?, ?, ?)",
            (sha1, kind, filetype, NOW)).lastrowid
        repo.record_header(con, frame_id=fid, raw_json=json.dumps(raw), now=NOW,
                           **{**scan.extract_header(raw), "ccd_temp": -10.0})
        con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (fid, str(tmp_path / path)))
        return fid

    wspolne = {"INSTRUME": "ZWO ASI2600MM Pro", "TELESCOP": "A140R", "FILTER": "H",
               "EXPTIME": 600.0}
    m = _klatka("m1", "master_light", "xisf",
                {**wspolne, "IMAGETYP": "Master Light", "OBJECT": "qwzx nieznany",
                 "DATE-OBS": "2025-08-30T20:00:00", "DATE-END": "2025-08-30T23:00:00"},
                "stos.xisf")
    lighty = [_klatka(f"l{i}", "light", "fits",
                      {**wspolne, "IMAGETYP": "Light Frame", "OBJECT": "M 31", "DATE-OBS": d},
                      f"l{i}.fits")
              for i, d in enumerate(("2025-08-30T20:30:00", "2025-08-30T21:30:00"))]
    con.commit()
    return m, lighty


def _dostawa(con, now):
    return dict(derive.adopt_and_derive(con, None, now, derive_always=True))


def test_dostawa_odswieza_zamrozony_powod_stosu_po_nadaniu_obiektu_reka(tmp_path, monkeypatch):
    """Lekcja repo: werdykt `integration.unresolved_reason` stał zamrożony dobę po nadaniu obiektu
    ręką, bo rodowód stosów liczyła tylko droga „Stosy" i osobny przycisk. Gest ręki rodowodu nie
    przelicza (stan po nim: dalej `no_object`); Dostawa, która po nim przejdzie, ma go odświeżyć.

    Falsyfikator: zdejmij `stack_lineage` z `DERIVED_STAGES` → powód zostaje `no_object`."""
    monkeypatch.setattr(scan, "copy_facts_candidates", lambda con, root=None: [])
    monkeypatch.setattr(scan, "adopt_candidates", lambda con, root=None: [])
    con = db.open_db(_baza(tmp_path))
    try:
        m, lighty = _stos_bez_obiektu(con, tmp_path)
        _dostawa(con, NOW)
        powod = "SELECT unresolved_reason FROM integration WHERE master_frame_id = ?"
        assert con.execute(powod, (m,)).fetchone()[0] == stacks.REASON_NO_OBJECT
        obiekt = con.execute("SELECT o.canon, o.catalog, o.kind FROM frame f "
                             "JOIN object o ON o.id = f.object_id WHERE f.id = ?",
                             (lighty[0],)).fetchone()
        assert obiekt is not None, "lighty mają mieć obiekt z resolvera"

        repo.user_assign_object(con, alias_norm=None, canon=obiekt[0], catalog=obiekt[1],
                                kind=obiekt[2], frame_ids=[m], now=_LATER)
        assert con.execute(powod, (m,)).fetchone()[0] == stacks.REASON_NO_OBJECT   # zamrożony

        wyniki = _dostawa(con, _LATEST)
        assert con.execute(powod, (m,)).fetchone()[0] is None
        assert [r["input_frame_id"] for r in stacks.inputs_of(con, m)] == lighty
        assert wyniki["stack_lineage"].linked == 1
    finally:
        con.close()


def test_dostawa_drugi_raz_bez_zmian_nie_pisze_rodowodu_stosow(tmp_path, monkeypatch):
    """Etap w Dostawie ma koszt (nagłówki stosów z dysku), więc przebieg bez zmian nie może jeszcze
    pisać: zero zdarzeń zapisu integracji, zero nowych wierszy. Zbiorcze `lineage_summary` leci
    przy każdej powtórce celowo (opisuje STAN, `stacks.run_stack_lineage`)."""
    monkeypatch.setattr(scan, "copy_facts_candidates", lambda con, root=None: [])
    monkeypatch.setattr(scan, "adopt_candidates", lambda con, root=None: [])
    con = db.open_db(_baza(tmp_path))
    try:
        _stos_bez_obiektu(con, tmp_path)
        _dostawa(con, NOW)
        przed = con.execute("SELECT max(id) FROM event").fetchone()[0]
        wiersze = con.execute("SELECT count(*) FROM integration_input").fetchone()[0]
        drugi = _dostawa(con, _LATER)
        zapisy = con.execute(
            f"SELECT count(*) FROM event WHERE id > ? AND verb IN ({','.join('?' * 4)})",
            (przed, *_ZAPIS_STOSOW)).fetchone()[0]
        assert zapisy == 0
        assert (drugi["stack_lineage"].linked_new, drugi["stack_lineage"].unlinked) == (0, 0)
        assert con.execute("SELECT count(*) FROM integration_input").fetchone()[0] == wiersze
    finally:
        con.close()


# --- AR-46: backstop wjazdu importu --------------------------------------------------------------

_PADA = os.path.join("LIGHTS", "m31_2.fits")


def _wjazd_pada_na(monkeypatch, sciezka):
    prawdziwy = imp.ingest_record

    def _f(con, rec, **kw):
        if rec.path == sciezka:
            raise RuntimeError("wjazd padl")
        return prawdziwy(con, rec, **kw)
    monkeypatch.setattr(imp, "ingest_record", _f)


def test_import_awaria_wjazdu_zaklada_szkielet_i_liczy_go(tmp_path, monkeypatch):
    """Wjazd padł po odczycie → ten sam szkielet co w `scan_tree` (klatka 'unknown', lokacja
    z markerem 'db', review), import idzie dalej, raport liczy rekord, bramki go oczekują.

    Falsyfikator: zdejmij gałąź `except Exception` w pętli `run_import` → RuntimeError
    przerywa import."""
    donor_path, files = _mk_donor(tmp_path, SPECS)
    p, _fid = files[_PADA]
    _wjazd_pada_na(monkeypatch, str(p))
    s = import_fitsmirror(str(donor_path), str(tmp_path / "horreum.db"), now=NOW, rng_seed=1)
    assert s.gate_failures == []
    assert (s.ingest_failed, s.ingest_failed_paths, s.ingest_failed_frames) == (1, [str(p)], 1)
    assert s.imported == 4 and s.gates["frame"] == (4, 4) and s.gates["location"] == (4, 4)
    assert s.gates["frame.camera_id NULL"] == (1, 1)
    con = db.open_db(str(tmp_path / "horreum.db"))
    try:
        row = con.execute(
            "SELECT l.unreadable_kind, l.unreadable_since, f.kind FROM location l "
            "JOIN frame f ON f.id = l.frame_id WHERE l.path = ?", (str(p),)).fetchone()
        assert (row["unreadable_kind"], row["unreadable_since"], row["kind"]) == ("db", NOW, "unknown")
        ev = con.execute("SELECT reason FROM event WHERE verb = 'frame.review'").fetchall()
        assert len(ev) == 1
        # Szkielet importu podpisuje się aktorem importu, nie skanu (dziennik odróżnia drogi).
        aktorzy = {r[0] for r in con.execute(
            "SELECT actor FROM event WHERE verb IN ('frame.review', 'location.added') "
            "AND (target LIKE 'sha1:%' OR payload LIKE ?)", (f"%{p.name}%",))}
        assert aktorzy == {imp.ACTOR}, aktorzy
    finally:
        con.close()
    raport = cli._format_import(str(donor_path), "h.db", s)
    assert "AWARIA WJAZDU: 1" in raport and str(p) in raport


def test_import_szkielet_tez_pada_to_abort(tmp_path, monkeypatch):
    donor_path, files = _mk_donor(tmp_path, SPECS)
    p, _fid = files[_PADA]
    _wjazd_pada_na(monkeypatch, str(p))

    def _szkielet_pada(*a, **kw):
        raise RuntimeError("szkielet padl")
    monkeypatch.setattr(imp, "_szkielet_po_awarii_zapisu", _szkielet_pada)
    with pytest.raises(ImportAbort, match="szkielet tez nie wszedl"):
        import_fitsmirror(str(donor_path), str(tmp_path / "horreum.db"), now=NOW, rng_seed=1)


def test_import_odmowa_generacji_dalej_abort(tmp_path, monkeypatch):
    """Backstop nie łyka `StaleScanRecord`: zapis w miejscu w trakcie importu to złamanie ramy
    świeżej bazy, nie awaria wjazdu."""
    donor_path, files = _mk_donor(tmp_path, SPECS)
    p, _fid = files[_PADA]

    def _f(con, rec, **kw):
        raise repo.StaleScanRecord("generacja")
    monkeypatch.setattr(imp, "ingest_record", _f)
    with pytest.raises(ImportAbort, match="zapis w miejscu"):
        import_fitsmirror(str(donor_path), str(tmp_path / "horreum.db"), now=NOW, rng_seed=1)
