"""Klinga zbiorcza werdyktu ręki na kilku stosach i cofnięcie gestu w jednej transakcji (AR-178).

Gest „Odrzuć nowsze niż obraz we wszystkich obrazach" zapisuje się cały albo wcale, a „Cofnij"
wraca do stanu sprzed gestu jedną transakcją z CAS per wiersz - dawne cofnięcie szło osobną
transakcją na każdy wiersz i awaria w połowie zostawiała gest cofnięty częściowo."""
import pytest

from horreum import db, repo

NOW = "2026-10-16T12:00:00"


def _stos(con, fid, iid, wejscia):
    """Stos `fid` z integracją `iid` i wejściami ręki `(frame_id, excluded)`."""
    con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) "
                "VALUES (?, ?, 'master_light', 'xisf', ?)", (fid, f"s{fid}", NOW))
    con.execute("INSERT INTO integration (id, master_frame_id, created_at, degenerate, ambiguous, "
                "telescope_mismatch) VALUES (?, ?, ?, 0, 0, 0)", (iid, fid, NOW))
    for wid, wykl in wejscia:
        con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) "
                    "VALUES (?, ?, 'light', 'fits', ?)", (wid, f"w{wid}", NOW))
        con.execute("INSERT INTO integration_input (integration_id, input_frame_id, asserted_by, "
                    "excluded) VALUES (?, ?, 'user', ?)", (iid, wid, wykl))


@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "z.db"))
    _stos(c, 10, 11, [(12, 0), (13, 0), (14, 0)])
    _stos(c, 20, 21, [(22, 0), (23, 0)])
    c.commit()
    yield c
    c.close()


def _tabela(con):
    return [tuple(r) for r in con.execute(
        "SELECT integration_id, input_frame_id, asserted_by, excluded FROM integration_input "
        "ORDER BY rowid")]


def _zdarzenia(con, verb):
    return con.execute("SELECT COUNT(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


def _pada_przy(monkeypatch, verb, ktory):
    """`emit_event` pada przy `ktory`-tym zdarzeniu `verb` - awaria w środku gestu."""
    prawdziwa = repo.emit_event
    licznik = {"n": 0}

    def _emit(con_, **kw):
        if kw.get("verb") == verb:
            licznik["n"] += 1
            if licznik["n"] == ktory:
                raise RuntimeError("awaria w środku gestu")
        return prawdziwa(con_, **kw)
    monkeypatch.setattr(repo, "emit_event", _emit)
    return prawdziwa


def test_klinga_zbiorcza_to_jedna_transakcja_dla_wszystkich_stosow(con, monkeypatch):
    """Awaria przy trzecim werdykcie (drugi stos) - pierwszy stos też nietknięty.
    Falsyfikator: `atomic` per stos zamiast jednego wokół pętli."""
    przed = _tabela(con)
    prawdziwa = _pada_przy(monkeypatch, "integration.judged", 3)
    with pytest.raises(RuntimeError):
        repo.judge_stacks_inputs(con, inputs_by_master={10: (12, 13), 20: (22,)}, excluded=True,
                                 now=NOW)
    assert _tabela(con) == przed
    monkeypatch.setattr(repo, "emit_event", prawdziwa)
    assert _zdarzenia(con, "integration.judged") == 0


def test_klinga_zbiorcza_zwraca_zmiany_per_stos_a_powtorka_nic(con):
    """Zwrot: `(stos, integracja, zmiany)` stosów z realną zmianą, w kolejności wejścia; zdarzenie
    na każde zmienione wejście; ten sam gest drugi raz - pusto, bez zdarzeń.
    Falsyfikator: stos bez zmian w zwrocie (cofnięcie dostałoby pusty wpis)."""
    wynik = repo.judge_stacks_inputs(con, inputs_by_master={10: (12, 13), 20: (22,)},
                                     excluded=True, now=NOW)
    assert [(m, iid, [z.input_frame_id for z in zmiany]) for m, iid, zmiany in wynik] == [
        (10, 11, [12, 13]), (20, 21, [22])]
    assert all(z.before == ("user", 0) and z.excluded == 1 for _m, _i, zm in wynik for z in zm)
    assert _zdarzenia(con, "integration.judged") == 3
    assert repo.judge_stacks_inputs(con, inputs_by_master={10: (12, 13), 20: (22,)},
                                    excluded=True, now=NOW) == []
    assert _zdarzenia(con, "integration.judged") == 3


def test_stos_bez_integracji_to_blad_i_nic_nie_zapisuje(con):
    """Klatka bez wiersza `integration` to błąd wołającego (EXPECT) - gest wycofany w całości,
    także dla stosu, który stał w kolejności przed nią. Falsyfikator: cichy `continue`."""
    przed = _tabela(con)
    with pytest.raises(ValueError):
        repo.judge_stacks_inputs(con, inputs_by_master={10: (12,), 99: (22,)}, excluded=True,
                                 now=NOW)
    assert _tabela(con) == przed


def test_cofniecie_zbiorcze_jedna_transakcja_a_CAS_per_wiersz(con, monkeypatch):
    """Cofnięcie gestu na dwóch stosach: (1) awaria przy drugim przywróceniu - nic nie wraca, gest
    stoi cały i da się go cofnąć ponownie; (2) wiersz z nowszym werdyktem zostaje (CAS), reszta
    wraca, tabela poza nim = stan sprzed gestu. Falsyfikator: pętla `restore_integration_judgment`
    bez `atomic` (po awarii pierwszy wiersz już cofnięty)."""
    przed = _tabela(con)
    wynik = repo.judge_stacks_inputs(con, inputs_by_master={10: (12, 13), 20: (22,)},
                                     excluded=True, now=NOW)
    zmiany = [(iid, z) for _m, iid, zm in wynik for z in zm]
    po_gescie = _tabela(con)
    prawdziwa = _pada_przy(monkeypatch, "integration.judgment_restored", 2)
    with pytest.raises(RuntimeError):
        repo.restore_integration_judgments(con, changes=zmiany, now=NOW)
    assert _tabela(con) == po_gescie
    monkeypatch.setattr(repo, "emit_event", prawdziwa)
    repo.judge_integration_input(con, integration_id=11, input_frame_id=13, excluded=False,
                                 now=NOW)                     # nowsza decyzja ręki na 13
    assert repo.restore_integration_judgments(con, changes=zmiany, now=NOW) == 2
    stan = {r[1]: (r[2], r[3]) for r in con.execute(
        "SELECT integration_id, input_frame_id, asserted_by, excluded FROM integration_input")}
    assert stan[13] == ("user", 0)                           # nowszy werdykt nietknięty
    assert {k: v for k, v in stan.items() if k != 13} == {
        r[1]: (r[2], r[3]) for r in przed if r[1] != 13}
    assert _zdarzenia(con, "integration.judgment_restored") == 2
